import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString
import numpy as np
import networkx as nx
import flatbuffers
from BackcountryMapGraph import Graph, Node, Edge, CumulativeMeasure

def load_data(dir: str):
    roads = gpd.read_file(dir + "/layers/road.fgb")
    trails = gpd.read_file(dir + "/layers/trail.fgb")
    
    gdf = gpd.GeoDataFrame(
        pd.concat([roads, trails], ignore_index=True),
        crs=roads.crs
    )
    
    gdf = gdf[gdf.geometry.type == "LineString"].copy() #LineStrings only
    
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
    
    return gdf

def build_graph(gdf: gpd.GeoDataFrame, main_trail_names_factor = {}):
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

    for _, row in gdf.iterrows():
        geom: LineString = row.geometry
        coords = list(geom.coords)

        a_id = get_node_id(*coords[0])
        b_id = get_node_id(*coords[-1])

        length = geom.length

        highway_type = row.get("highway", "")
        trail_factor = TRAIL_FACTOR.get(highway_type, 1.0)
        
        name = row.get("name", "")
        
        name_factor = main_trail_names_factor.get(name, 1.0)

        weight = length * trail_factor * name_factor

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
    
    
if __name__ == "__main__":
    long_trail_names_factor = {
        "Long Trail" : 0.1,
        "Appalachian Trail;Long Trail"  : 0.1,
        "Appalachian Trail; Long Trail"  : 0.1
    }
    
    gdf = load_data('./out')
    
    G, nodes, edges = build_graph(gdf, long_trail_names_factor)
    
    export_graph_flatbuffer(
        nodes,
        edges,
        "./out/graph.bin"
    )

    print("FlatBuffer written: backcountry_graph.bin")
    
    