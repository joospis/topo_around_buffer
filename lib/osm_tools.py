import json
import os
from pathlib import Path
from typing import Mapping, cast
import geopandas
import pandas as pd
import requests
from shapely import Polygon
import osmnx
import re
from create_buffer import create_buffer

def get_relation_way_ids(relation_id: int, cache_dir: Path = Path(__name__).parent / "trail_relation_cache") -> set[int]:
    """
    Fetches relation way IDs from a local cache if available, otherwise 
    queries Overpass and saves the result.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"relation_{relation_id}.json"

    # 1. Try to load from cache
    if cache_file.exists():
        print(f"Loading relation {relation_id} from cache...")
        with open(cache_file, "r") as f:
            data = json.load(f)
            return set(data)

    # 2. Fetch from Overpass if cache doesn't exist
    print(f"Fetching relation {relation_id} from Overpass...")
    url = "https://overpass-api.de/api/interpreter"
    query = f"""[out:json][timeout:60];
    rel({relation_id});
    (<<; >>;);
    way(r);
    out ids;"""
    
    headers = {"User-Agent": "PythonGeopandasScript/1.0"}
    
    try:
        response = requests.get(url, params={'data': query}, headers=headers)
        if response.status_code != 200:
            print(f"Overpass Error {response.status_code}: {response.text}")
            return set()
            
        data = response.json()
        way_ids = [
            element['id'] for element in data.get('elements', []) 
            if element['type'] == 'way'
        ]
        
        # 3. Save to cache (as a list, since JSON doesn't support sets)
        with open(cache_file, "w") as f:
            json.dump(way_ids, f)
        
        return set(way_ids)

    except Exception as e:
        print(f"Request failed: {e}")
        return set()

def add_main_trail_flag(gdf: geopandas.GeoDataFrame, way_ids: set[int], column_name: str = "main_trail"):
    """
    Adds a 'yes'/'no' column to the GDF if the way ID is in the provided set.
    """
    gdf = gdf.copy()
    
    # OSMnx GDFs usually use a MultiIndex where the second level is the OSM ID
    # We'll check if the index is a MultiIndex (standard for osmnx)
    if isinstance(gdf.index, pd.MultiIndex):
        gdf[column_name] = gdf.index.get_level_values(1).isin(way_ids)
    else:
        gdf[column_name] = gdf.index.isin(way_ids)
        
    # Convert True/False to yes/no to match OSM style if preferred
    gdf[column_name] = gdf[column_name].map({True: 'yes', False: 'no'})
    
    return gdf

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
    "route": ["hiking"],
    "type": "route",
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
    edit_highway_refs = False,
    way_ids: set[int] | None = None
):
    gdf = osmnx.features_from_polygon(polygon, dict(tags)).clip(polygon)
    
    if gdf.empty:
        print(f"Warning: No features found for {output_path.name}")
        return
    
    # Add highway shield data
    if "highway" in gdf.columns and edit_highway_refs:
        gdf = add_shield_fields(gdf)
        
    #Remove gold cart paths
    if 'golf' in gdf.columns:
        gdf = gdf[gdf['golf'] != 'cartpath']
        
    # If this is the trail layer, add the codes
    if way_ids:
        gdf = add_main_trail_flag(gdf, way_ids)
        
    
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

    
def main(output_dir: Path, polygon: Polygon, relation_id: int):
    layer_dir = output_dir / "temp/osm_layers"
    way_ids = get_relation_way_ids(relation_id)
    download_features_to_layer(polygon, road_tags, layer_dir / "road.fgb", edit_highway_refs=True, way_ids=way_ids)
    download_features_to_layer(polygon, trail_tags, layer_dir / "trail.fgb", way_ids=way_ids)
    download_features_to_layer(polygon, landcover_tags, layer_dir / "landcover.fgb")
    download_features_to_layer(polygon, park_area_tags, layer_dir / "park.fgb")
    download_features_to_layer(polygon, hydro_tags, layer_dir / "hydro.fgb")
    download_features_to_layer(polygon, railway_tags, layer_dir / "railway.fgb")
    download_features_to_layer(buffer, {"building" : True}, layer_dir / "building.fgb")
    save_buffer_polygon(polygon, layer_dir / "buffer.fgb")

if __name__ == "__main__":
    buffer, bbox = create_buffer('./map.geojson')
    output_dir = Path("./out2").resolve()
    main(output_dir, buffer, 391736)