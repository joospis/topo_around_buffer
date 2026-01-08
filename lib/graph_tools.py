import json
from pathlib import Path
import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, mapping
from shapely.ops import unary_union
import numpy as np
import networkx as nx
import flatbuffers
import rasterio
from rasterio.transform import rowcol
from shapely.geometry import LineString


# Import your FlatBuffer generated classes
from lib.BackcountryMapGraph import Graph, Node, Edge, CumulativeMeasure
from lib import constants

# def sample_dem_z(dem_ds, x, y):
#     """
#     Sample DEM at (x, y). Returns float Z or 0.0 if nodata.
#     """
#     try:
#         row, col = dem_ds.index(x, y)
#         z = dem_ds.read(1)[row, col]
#         if z == dem_ds.nodata or np.isnan(z):
#             return 0.0
#         return float(z)
#     except Exception:
#         return 0.0


def add_z_to_lines(gdf: gpd.GeoDataFrame, dem_path: Path) -> gpd.GeoDataFrame:
    """
    Fast DEM sampling with progress output.
    """
    print(f" - Sampling DEM Z values from {dem_path}...")

    total = len(gdf)
    last_pct = -1

    with rasterio.open(dem_path) as dem_ds:
        dem = dem_ds.read(1)        # ← READ ONCE
        nodata = dem_ds.nodata
        transform = dem_ds.transform

        def line_with_z(line: LineString, idx: int):
            nonlocal last_pct

            pct = int((idx / total) * 100)
            if pct != last_pct:
                print(f"\r   Progress: {pct:3d}%", end="", flush=True)
                last_pct = pct

            coords = np.asarray(line.coords)
            rows, cols = rowcol(
                transform, coords[:, 0], coords[:, 1], op=round
            )

            z = dem[rows, cols]
            if nodata is not None:
                z = np.where(z == nodata, 0.0, z)

            return LineString(
                [(x, y, float(zv)) for (x, y), zv in zip(coords[:, :2], z)]
            )

        gdf["geometry"] = [
            line_with_z(geom, i) # type: ignore
            for i, geom in enumerate(gdf.geometry, start=1)
        ]

    print("\r   Progress: 100%")
    return gdf




def load_data(dir_path: Path):
    dem_path = dir_path / "temp/cropped_meters.tif"

    print(f"Loading and Noderizing layers from {dir_path}...")
    
    roads_path = Path(dir_path) / "temp/osm_layers/road.fgb"
    trails_path = Path(dir_path) / "temp/osm_layers/trail.fgb"
    
    roads = gpd.read_file(roads_path)
    trails = gpd.read_file(trails_path)
    
    # 1. Combine into a single GeoDataFrame
    gdf_raw = gpd.GeoDataFrame(
        pd.concat([roads, trails], ignore_index=True),
        crs=roads.crs
    )
    
    # 2. Explode MultiLineStrings into simple LineStrings
    gdf_raw = gdf_raw.explode(index_parts=False)
    gdf_raw = gdf_raw[gdf_raw.geometry.type == "LineString"].copy()

    # 3. NODERIZATION: Split all lines at every intersection point
    # This ensures roads and trails share a node where they cross.
    print(" - Splitting lines at intersections...")
    merged_lines = unary_union(gdf_raw.geometry)
    
    # unary_union returns a MultiLineString or GeometryCollection; convert back to a list of LineStrings
    if hasattr(merged_lines, 'geoms'):
        split_geoms = [line for line in merged_lines.geoms] # type: ignore
    else:
        split_geoms = [merged_lines]
    
    new_gdf = gpd.GeoDataFrame(geometry=split_geoms, crs=gdf_raw.crs)

    # 4. PRESERVE ATTRIBUTES: Spatially join metadata back to the split segments
    # Since unary_union loses attributes, we join them back from the original lines.
    print(" - Re-attaching attributes...")
    gdf = gpd.sjoin(new_gdf, gdf_raw, how="left", predicate="within")
    gdf = gdf.drop_duplicates(subset=['geometry']).copy()

    # 5. ADD Z FROM DEM
    gdf = add_z_to_lines(gdf, dem_path)

    # 6. COORDINATE SNAPPING (Tolerance)
    # We round coordinates to 5 decimal places (~1.1m) to close digitization gaps.
    def snap_and_ensure_3d(line):
        coords = []
        for c in line.coords:
            x, y = round(c[0], 5), round(c[1], 5)
            z = c[2] if len(c) == 3 else 0.0
            coords.append((x, y, z))
        return LineString(coords)

    gdf["geometry"] = gdf.geometry.map(snap_and_ensure_3d)
    gdf = gdf[gdf.geometry.is_valid & ~gdf.geometry.is_empty]
    
    print(f" - Final graph edges: {len(gdf)}")
    return gdf

def build_graph(gdf: gpd.GeoDataFrame):
    G = nx.Graph()
    node_index = {}
    nodes = {}
    edges = []
    next_node_id = 0

    # Match nodes based on 2D coordinates only (X, Y)
    # This ensures connectivity even if elevation (Z) data is slightly noisy.
    def get_node_id(x, y, z):
        nonlocal next_node_id
        # Rounding here acts as a second safety net for the tolerance
        key = (round(x, 5), round(y, 5)) 
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
            # Simple Euclidean distance for weight (assuming UTM or small-area Lat/Lon)
            seg_dist = np.hypot(x2 - x1, y2 - y1)
            dz = z2 - z1
            dist += seg_dist
            if dz > 0: gain += dz
            else: loss += abs(dz)
            measures.append((dist, gain, loss))
        return measures

    TRAIL_FACTOR = {"path": 0.5, "track": 0.5, "footway": 0.5}
    MAIN_TRAIL_FACTOR = 0.1

    for _, row in gdf.iterrows():
        geom = row.geometry
        coords = list(geom.coords)
        
        a_id = get_node_id(*coords[0])
        b_id = get_node_id(*coords[-1])

        # Skip zero-length segments created by snapping
        if a_id == b_id: continue

        highway_type = row.get("highway", "")
        trail_factor = TRAIL_FACTOR.get(highway_type, 1.0)
        is_main = row.get("main_trail", "") == "yes"
        priority_factor = MAIN_TRAIL_FACTOR if is_main else 1.0

        weight = geom.length * trail_factor * priority_factor

        edges.append({
            "start": a_id,
            "end": b_id,
            "weight": weight,
            "geometry": geom,
            "measures_forward": compute_measures(coords),
            "measures_reverse": compute_measures(coords[::-1]),
        })
        G.add_edge(a_id, b_id, weight=weight)

    return G, nodes, edges

def export_graph_flatbuffer(nodes, edges, output_path):
    builder: flatbuffers.Builder = flatbuffers.Builder(1024)

    # Serialize Nodes
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

    # Serialize Edges
    edge_offsets = []
    for e in edges:
        wkb_vec = builder.CreateByteVector(e["geometry"].wkb)

        def build_m_vec(m_list):
            m_offs = []
            for d, g, l in m_list:
                CumulativeMeasure.Start(builder)
                CumulativeMeasure.AddCumulativeDistance(builder, d)
                CumulativeMeasure.AddCumulativeGain(builder, g)
                CumulativeMeasure.AddCumulativeLoss(builder, l)
                m_offs.append(CumulativeMeasure.End(builder))
            builder.StartVector(4, len(m_offs), 4)
            for mo in reversed(m_offs): builder.PrependUOffsetTRelative(mo)
            return builder.EndVector()

        fwd_vec = build_m_vec(e["measures_forward"])
        rev_vec = build_m_vec(e["measures_reverse"])

        Edge.Start(builder)
        Edge.AddStartNodeId(builder, e["start"])
        Edge.AddEndNodeId(builder, e["end"])
        Edge.AddWeight(builder, e["weight"])
        Edge.AddGeometryWkb(builder, wkb_vec)
        Edge.AddMeasuresForward(builder, fwd_vec)
        Edge.AddMeasuresReverse(builder, rev_vec)
        edge_offsets.append(Edge.End(builder))

    Graph.StartEdgesVector(builder, len(edge_offsets))
    for off in reversed(edge_offsets): builder.PrependUOffsetTRelative(off)
    edges_vec = builder.EndVector()

    Graph.Start(builder)
    Graph.AddNodes(builder, nodes_vec)
    Graph.AddEdges(builder, edges_vec)
    graph_root = Graph.End(builder)
    builder.Finish(graph_root)

    with open(output_path, "wb") as f:
        f.write(builder.Output())

def export_debug_geojson(edges, output_path):
    features = []
    for e in edges:
        features.append({
            "type": "Feature",
            "geometry": mapping(e["geometry"]),
            "properties": {"start": e["start"], "end": e["end"], "weight": e["weight"]}
        })
    with open(output_path, "w") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)

def main(output_dir: Path):
    print(f"Building graph in {output_dir}...")

    gdf = load_data(output_dir)
    G, nodes, edges = build_graph(gdf)

    export_graph_flatbuffer(nodes, edges, output_dir / "graph.bin")
    export_debug_geojson(edges, output_dir / "graph_debug.geojson")

    print(f"Success! Graph contains {len(nodes)} nodes and {len(edges)} edges.")


if __name__ == "__main__":
    main(Path("./out3"))
