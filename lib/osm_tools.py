import os
from pathlib import Path
from typing import Mapping, cast
import geopandas
from shapely import Polygon
import osmnx
import re


from create_buffer import create_buffer

road_tags = {
    "highway": [
        "motorway",
        "trunk",
        "primary",
        "secondary",
        "tertiary",
        "residential",
        "service",
        "motorway_link",
        "trunk_link",
        "primary_link",
        "secondary_link",
        "tertiary_link",
        "unclassified"
    ]
}
trail_tags = {
    "highway": [
        "path", "track", "footway", "cycleway", "bridleway", "steps", "via_ferrata"
    ],
    "route": "ferry",

    "trail": "yes",
    "hiking": ["yes", "designated"],
    "mtb": ["yes", "designated"],
}
landcover_tags = {
    "landuse": ["forest"],
    "natural": ["wood"]
}
hydro_tags = {
    "waterway": ["river", "stream", "canal", "drain"],
    "natural": ["water"],
    "intermittent": True,
    "wetland": True,
}
railway_tags = {
    "railway": ["rail", "tram", "light_rail", "narrow_gauge", "funicular"],
}
park_area_tags = {
    "leisure": ["park", "nature_reserve"],
    "boundary": ["national_park", "protected_area"],
    "protected_area": True,
}    

def download_features_to_layer(
    polygon: Polygon, 
    # layer_name: str, 
    tags: Mapping[str, bool | str | list[str]], 
    output_path: Path,
    edit_highway_refs = False
):
    gdf = osmnx.features_from_polygon(polygon, dict(tags)).clip(polygon)
    
    if "highway" in gdf.columns and edit_highway_refs:
        gdf = add_shield_fields(gdf)
    os.makedirs(str(output_path.parent), exist_ok=True) # Ensure directory exists
    gdf.to_file(output_path, driver="FlatGeobuf")
    
def save_buffer_polygon(buffer: Polygon, output_path: Path):
    gdf = geopandas.GeoDataFrame(
        index=[0],
        crs='epsg:4326',
        geometry=[buffer]
    )
    if output_path == None:
        os.makedirs('./out/layers/', exist_ok=True)
        output_path = f'./out/layers/buffer.fgb'
    gdf.to_file(output_path, driver="FlatGeobuf")

def derive_network(ref: str | None):
    if not ref:
        return None
    # Handle the first part of a multi-ref like "11;VT 30"
    primary_ref = ref.split(';')[0].strip()
    
    if primary_ref.startswith("I "):
        return "us-interstate"
    if primary_ref.startswith("US "):
        return "us-highway"
    # Matches "VT 30", "NY 5", etc.
    if re.match(r"^[A-Z]{2}\s\d+", primary_ref):
        return "us-state"
    return "road" # Default for other references

def clean_ref(ref: str | None):
    if not ref:
        return None
    # Take the first ref and strip the network prefix (e.g., "VT 30" -> "30")
    primary_ref = ref.split(';')[0].strip()
    return re.sub(r"^(I|US|[A-Z]{2})\s+", "", primary_ref).strip()

def ref_length(ref: str | None):
    cleaned = clean_ref(ref)
    return len(cleaned) if cleaned else None

def add_shield_fields(gdf: geopandas.GeoDataFrame):
    gdf = gdf.copy()
    gdf["network"] = None
    gdf["ref_length"] = None

    for idx, row in gdf.iterrows():
        # idx is ('way', 19675849)
        ref = row.get("ref")
        if not ref:
            continue

        ref = str(ref)
        network = derive_network(ref)
        if not network:
            continue

        gdf.loc[idx, "network"] = network # type: ignore
        gdf.loc[idx, "ref"] = clean_ref(ref) # type: ignore
        gdf.loc[idx, "ref_length"] = ref_length(ref) # type: ignore

    return gdf


    
def main(output_dir: Path, polygon: Polygon):
    layer_dir = output_dir / "temp/osm_layers"
    download_features_to_layer(polygon, road_tags, layer_dir / "road.fgb", edit_highway_refs=True)
    download_features_to_layer(polygon, trail_tags, layer_dir / "trail.fgb")
    download_features_to_layer(polygon, landcover_tags, layer_dir / "landcover.fgb")
    download_features_to_layer(polygon, park_area_tags, layer_dir / "park.fgb")
    download_features_to_layer(polygon, hydro_tags, layer_dir / "hydro.fgb")
    download_features_to_layer(polygon, railway_tags, layer_dir / "trailway.fgb")
    download_features_to_layer(buffer, {"building" : True}, layer_dir / "building.fgb")
    save_buffer_polygon(polygon, layer_dir / "buffer.fgb")

if __name__ == "__main__":
    buffer, bbox = create_buffer('./map.geojson')
    output_dir = Path("./out2").resolve()
    main(output_dir, buffer)