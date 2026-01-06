import json
from pathlib import Path
import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, mapping
import numpy as np
import networkx as nx
import flatbuffers
from lib.BackcountryMapGraph import Graph, Node, Edge, CumulativeMeasure
from lib import constants

def load_data(dir: str):
    print(f"Loading layers from {dir}...")
    
    # Ensure these paths match your actual directory structure
    # Based on your snippet, it looks for ./out3/temp/osm_layers/road.fgb
    roads_path = dir + "/temp/osm_layers/road.fgb"
    trails_path = dir + "/temp/osm_layers/trail.fgb"
    
    roads = gpd.read_file(roads_path)
    trails = gpd.read_file(trails_path)
    
    print(f" - Raw Roads loaded: {len(roads)}")
    print(f" - Raw Trails loaded: {len(trails)}")
    
    # Combine
    gdf = gpd.GeoDataFrame(
        pd.concat([roads, trails], ignore_index=True),
        crs=roads.crs
    )
    
    # --- FIX: Explode MultiLineStrings into simple LineStrings ---
    # This ensures roads (often MultiLineStrings) aren't dropped by the next filter
    gdf = gdf.explode(index_parts=False)
    
    # Filter for LineStrings only (drops Points/Polygons)
    gdf = gdf[gdf.geometry.type == "LineString"].copy()
    
    def ensure_3d(line):
        coords = []
        for c in line.coords:
            if len(c) == 3:
                coords.append(c)
            else:
                coords.append((c[0], c[1], 0.0))
        return LineString(coords)

    gdf["geometry"] = gdf.geometry.map(ensure_3d)
    gdf = gdf[gdf.geometry.notnull()]
    gdf = gdf[gdf.geometry.is_valid]
    
    print(f" - Final valid edges after processing: {len(gdf)}")
    
    return gdf

def build_graph(gdf: gpd.GeoDataFrame):
    """
    Builds:
      - networkx.Graph (weighted)
      - node table: {node_id: (x, y, z)}
      - edge table: list of dicts (ready for FlatBuffers)
    """

    G = nx.Graph()

    node_index = {}
    nodes = {}
    edges = []

    next_node_id = 0

    def node_key(x, y, z, tol=1e-6):
        return (round(x / tol), round(y / tol), round(z / tol))

    def get_node_id(x, y, z):
        nonlocal next_node_id
        key = node_key(x, y, z)
        if key not in node_index:
            node_index[key] = next_node_id
            nodes[next_node_id] = (x, y, z)
            next_node_id += 1
        return node_index[key]

    def compute_measures(coords):
        dist = gain = loss = 0.0
        measures = [(0.0, 0.0, 0.0)]

        for i in range(1, len(coords)):
            x1, y1, z1 = coords[i - 1]
            x2, y2, z2 = coords[i]

            seg_dist = np.hypot(x2 - x1, y2 - y1)
            dz = z2 - z1

            dist += seg_dist
            if dz > 0:
                gain += dz
            else:
                loss += -dz

            measures.append((dist, gain, loss))

        return measures

    
    TRAIL_FACTOR = {
        "path": 0.5, 
        "track" : 0.5, 
        "footway" : 0.5
    }
    
    MAIN_TRAIL_FACTOR = 0.1

    for _, row in gdf.iterrows():
        geom: LineString = row.geometry
        coords = list(geom.coords)

        a_id = get_node_id(*coords[0])
        b_id = get_node_id(*coords[-1])

        length = geom.length

        highway_type = row.get("highway", "")
        trail_factor = TRAIL_FACTOR.get(highway_type, 1.0)
        
        # Check if this is a main trail directly from the properties
        is_main_trail = row.get("main_trail", "") == "yes"
        priority_factor = MAIN_TRAIL_FACTOR if is_main_trail else 1.0

        weight = length * trail_factor * priority_factor

        forward = compute_measures(coords)
        reverse = compute_measures(coords[::-1])

        edges.append({
            "start": a_id,
            "end": b_id,
            "weight": weight,
            "geometry": geom,
            "measures_forward": forward,
            "measures_reverse": reverse,
        })

        G.add_edge(a_id, b_id, weight=weight)

    return G, nodes, edges


def export_graph_flatbuffer(
    nodes: dict[int, tuple[float, float, float]],
    edges: list[dict],
    output_path: str,
):
    builder = flatbuffers.Builder(1024)

    # -----------------------------
    # Nodes
    # -----------------------------
    node_offsets = []

    for node_id, (x, y, z) in nodes.items():
        Node.Start(builder)
        Node.AddId(builder, node_id)
        Node.AddX(builder, x)
        Node.AddY(builder, y)
        Node.AddZ(builder, z)
        node_offsets.append(Node.End(builder))

    Graph.StartNodesVector(builder, len(node_offsets))
    for off in reversed(node_offsets):
        builder.PrependUOffsetTRelative(off)
    nodes_vec = builder.EndVector()

    # -----------------------------
    # Edges
    # -----------------------------
    edge_offsets = []

    for e in edges:
        # Geometry (WKB, 3D)
        geom: LineString = e["geometry"]
        wkb_vec = builder.CreateByteVector(geom.wkb)

        def build_measures(measures):
            m_offsets = []
            for dist, gain, loss in measures:
                CumulativeMeasure.Start(builder)
                CumulativeMeasure.AddCumulativeDistance(builder, dist)
                CumulativeMeasure.AddCumulativeGain(builder, gain)
                CumulativeMeasure.AddCumulativeLoss(builder, loss)
                m_offsets.append(CumulativeMeasure.End(builder))

            builder.StartVector(4, len(m_offsets), 4)
            for mo in reversed(m_offsets):
                builder.PrependUOffsetTRelative(mo)
            return builder.EndVector()

        forward_vec = build_measures(e["measures_forward"])
        reverse_vec = build_measures(e["measures_reverse"])

        Edge.Start(builder)
        Edge.AddStartNodeId(builder, e["start"])
        Edge.AddEndNodeId(builder, e["end"])
        Edge.AddWeight(builder, e["weight"])
        Edge.AddGeometryWkb(builder, wkb_vec)
        Edge.AddMeasuresForward(builder, forward_vec)
        Edge.AddMeasuresReverse(builder, reverse_vec)
        edge_offsets.append(Edge.End(builder))

    Graph.StartEdgesVector(builder, len(edge_offsets))
    for off in reversed(edge_offsets):
        builder.PrependUOffsetTRelative(off)
    edges_vec = builder.EndVector()

    # -----------------------------
    # Graph root
    # -----------------------------
    Graph.Start(builder)
    Graph.AddNodes(builder, nodes_vec)
    Graph.AddEdges(builder, edges_vec)
    graph = Graph.End(builder)

    builder.Finish(graph)

    with open(output_path, "wb") as f:
        f.write(builder.Output())
    

def export_debug_geojson(nodes, edges, output_path):
    features = []

    # 1. Export Nodes (Points)
    for node_id, (x, y, z) in nodes.items():
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [x, y, z]
            },
            "properties": {
                "type": "node",
                "id": node_id,
                "z": z
            }
        })

    # 2. Export Edges (Lines)
    for e in edges:
        features.append({
            "type": "Feature",
            "geometry": mapping(e["geometry"]),
            "properties": {
                "type": "edge",
                "start": e["start"],
                "end": e["end"],
                "weight": e["weight"]
            }
        })

    geojson = {
        "type": "FeatureCollection",
        "features": features
    }

    with open(output_path, "w") as f:
        json.dump(geojson, f)
    print(f"Debug GeoJSON written to: {output_path}")
    
def main(output_dir: Path):
    print(f"{constants.YELLOW}Creating weighted graph...{constants.RESET}")
    
    gdf = load_data(str(output_dir.absolute()))
    G, nodes, edges = build_graph(gdf)
    export_graph_flatbuffer(
        nodes,
        edges,
        str(output_dir / "graph.bin")
    )
    print(f"{constants.YELLOW}FlatBuffer written: backcountry_graph.bin{constants.RESET}")
    
    export_debug_geojson(nodes, edges, str(output_dir / "graph_debug.geojson"))
    print(f"{constants.YELLOW}GeoJSON written: graph_debug.geojson{constants.RESET}")

    

if __name__ == "__main__":
    gdf = load_data('./out3')
    
    G, nodes, edges = build_graph(gdf)
    
    export_graph_flatbuffer(
        nodes,
        edges,
        "./out3/graph.bin"
    )
    
    export_debug_geojson(nodes, edges, "./out3/graph_debug.geojson")

    print("FlatBuffer written: backcountry_graph.bin")