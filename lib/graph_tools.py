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
from lib.BackcountryMapGraph import Graph, Node, Edge
from lib import constants


def add_z_to_lines(gdf: gpd.GeoDataFrame, dem_path: Path) -> gpd.GeoDataFrame:
    print(f" - Sampling DEM Z values from {dem_path}...")

    total = len(gdf)
    last_pct = -1

    with rasterio.open(dem_path) as dem_ds:
        dem = dem_ds.read(1)
        nodata = dem_ds.nodata
        transform = dem_ds.transform
        
        # Get array dimensions
        height, width = dem.shape

        def line_with_z(line: LineString, idx: int):
            nonlocal last_pct
            
            # Progress tracking
            pct = int((idx / total) * 100)
            if pct != last_pct:
                print(f"\r   Progress: {pct:3d}%", end="", flush=True)
                last_pct = pct

            coords = np.asarray(line.coords)
            rows, cols = rowcol(transform, coords[:, 0], coords[:, 1], op=round)
            
            # Convert to numpy arrays for vectorized clipping
            rows = np.asarray(rows)
            cols = np.asarray(cols)

            # CLAMP INDICES: Ensure they fall within [0, size-1]
            # This prevents the IndexError for points on the very edge or slightly outside
            rows = np.clip(rows, 0, height - 1)
            cols = np.clip(cols, 0, width - 1)

            z = dem[rows, cols]
            
            if nodata is not None:
                z = np.where(z == nodata, 0.0, z)

            # Reconstruct 3D points
            new_coords = [(x, y, float(zv)) for (x, y), zv in zip(coords[:, :2], z)]
            return LineString(new_coords)

        gdf["geometry"] = [
            line_with_z(geom, i)  # type: ignore
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
    def get_node_id(x, y):
        nonlocal next_node_id
        # Rounding here acts as a second safety net for the tolerance
        key = (round(x, 5), round(y, 5)) 
        if key not in node_index:
            node_index[key] = next_node_id
            nodes[next_node_id] = (x, y)
            next_node_id += 1
        return node_index[key]

    TRAIL_FACTOR = {"path": 0.5, "track": 0.5, "footway": 0.5}
    MAIN_TRAIL_FACTOR = 0.1

    for _, row in gdf.iterrows():
        geom = row.geometry
        coords = list(geom.coords)
        
        # Extract 2D coordinates for node matching
        a_id = get_node_id(coords[0][0], coords[0][1])
        b_id = get_node_id(coords[-1][0], coords[-1][1])

        # Skip zero-length segments created by snapping
        if a_id == b_id: continue

        highway_type = row.get("highway", "")
        trail_factor = TRAIL_FACTOR.get(highway_type, 1.0)
        is_main = row.get("main_trail", "") == "yes"
        priority_factor = MAIN_TRAIL_FACTOR if is_main else 1.0

        weight = geom.length * trail_factor * priority_factor

        # Compute bounding box
        bounds = geom.bounds  # (minx, miny, maxx, maxy)

        edges.append({
            "start": a_id,
            "end": b_id,
            "weight": weight,
            "geometry": geom,
            "bbox_min_x": bounds[0],
            "bbox_min_y": bounds[1],
            "bbox_max_x": bounds[2],
            "bbox_max_y": bounds[3],
        })
        G.add_edge(a_id, b_id, weight=weight)

    return G, nodes, edges

def export_graph_flatbuffer(nodes, edges, output_path):
    builder: flatbuffers.Builder = flatbuffers.Builder(1024)

    # Serialize Nodes
    node_offsets = []
    for node_id, (x, y) in nodes.items():
        Node.Start(builder)
        Node.AddId(builder, node_id)
        Node.AddX(builder, x)
        Node.AddY(builder, y)
        node_offsets.append(Node.End(builder))

    Graph.StartNodesVector(builder, len(node_offsets))
    for off in reversed(node_offsets):
        builder.PrependUOffsetTRelative(off)
    nodes_vec = builder.EndVector()

    # Serialize Edges
    edge_offsets = []
    for e in edges:
        wkb_vec = builder.CreateByteVector(e["geometry"].wkb)

        Edge.Start(builder)
        Edge.AddStartNodeId(builder, e["start"])
        Edge.AddEndNodeId(builder, e["end"])
        Edge.AddWeight(builder, e["weight"])
        Edge.AddGeometryWkb(builder, wkb_vec)
        Edge.AddBboxMinX(builder, e["bbox_min_x"])
        Edge.AddBboxMinY(builder, e["bbox_min_y"])
        Edge.AddBboxMaxX(builder, e["bbox_max_x"])
        Edge.AddBboxMaxY(builder, e["bbox_max_y"])
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
    main(Path("./out4"))