import os
from typing import Any, Dict, Mapping
from geopandas import GeoDataFrame
import geopandas as gpd
import osmnx as ox
import json
from shapely import Polygon
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
        "tertiary_link"
    ]
}


trail_tags = {
    # Primary features
    "highway": [
        "path", "track", "footway", "cycleway", "bridleway", "steps", "via_ferrata"
    ],
    "route": "ferry",  # For essential water links/crossings

    # Explicit Trail Tags
    "trail": "yes",
    "hiking": ["yes", "designated"],
    "mtb": ["yes", "designated"],
    
    # Portage/Canoe Access (Needed for Ferry/Water Link context)
    # "portage": ["yes", "designated", "permissive", "permit", "private", "customers"],
    # "canoe": ["yes", "designated", "permissive", "permit", "private", "customers"],

    # # Access and Usage Tags
    # "atv": True,
    # "bicycle": True,
    # "dog": True,
    # "foot": True,
    # "horse": True,
    # "inline_skates": True,
    # "piste:type": True,
    # "ski:nordic": True,
    # "snowmobile": True,
    # "wheelchair": True,
    # "access": True,

    # # Geometry/Metadata Attributes
    # "name": True,
    # "surface": True,
    # "tracktype": True,
    # "trail_visibility": True,
    # "oneway": True,
    # "incline": True,
    # "sac_scale": True,
    # "tunnel": True,
    # "bridge": True,
    # "ford": True,
    # "lit": True,
    # "rapids": True,
}


landcover_tags = {
    # "natural": ["wood", "forest", "scrub", "grassland", "heath", "sand", "bare_rock"],
    # "landcover": ["grass", "meadow", "farmland", "bare_rock", "mud"]
    "landuse": ["forest"], #doesn't work
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

trail_poi_tags = {
    # Camping and Shelter
    "tourism": [
        "camp_site", "camp_pitch", "caravan_site", "wilderness_hut", "viewpoint"
    ],
    "shelter_type": "lean_to",
    
    # Access and Service Points
    "amenity": "ranger_station",
    "highway": "trailhead",
    "leisure": "slipway", # Assuming slipway is kept for water access POIs
    
    # Route/Navigation Markers and Environmental Obstacles
    "information": ["route_marker", "guidepost"],
    "man_made": ["cairn", "lock"],
    "natural": ["tree", "beaver_dam", "waterfall", "peak"],
    "waterway": ["dam", "weir", "access_point"],
    "historic": "wreck",
    
    # POI Attributes
    "name": True,
    "operator": True,
    "ele": True,
    "fee": True,
    "toilets": True,
    "shower": True,
    "opening_hours": True,
    "parking": True,
    "bicycle": True,
    "foot": True,
    "horse": True,
    "access": True,
}

    

def download_features_to_layer(polygon: Polygon, layer_name: str, tags: Mapping[str, bool | str | list[str]], output_path: str | None = None, simplification_tolerance: float = 0.00001):
    gdf_features = ox.features_from_polygon(polygon, tags) # type: ignore

    print(f"Downloaded {len(gdf_features)} features for layer '{layer_name}'")
    
    if not gdf_features.empty:
        gdf_features['geometry'] = gdf_features.simplify(
            tolerance=simplification_tolerance, 
            preserve_topology=True
        )
    
    if output_path == None:
        os.makedirs('./out/layers/', exist_ok=True)
        output_path = f'./out/layers/{layer_name}.fgb'
    try:
        gdf_features.to_file(output_path, driver="FlatGeobuf")
        # with open(output_path, 'w') as f:
        #     f.write(gdf_features.to_json(na='drop'))
        # strip_nulls_from_geojson(output_path)
        print(f"Successfully saved features to {output_path}")
    except Exception as e:
        print(f"An error occurred while saving: {e}")
        
def save_buffer_polygon(buffer: Polygon, output_path: str | None = None):
    gdf = gpd.GeoDataFrame(
        index=[0],
        crs='epsg:4326',
        geometry=[buffer]
    )
    if output_path == None:
        os.makedirs('./out/layers/', exist_ok=True)
        output_path = f'./out/layers/buffer.fgb'
    gdf.to_file(output_path, driver="FlatGeobuf")
    

if __name__ == "__main__":
    buffer, bbox = create_buffer('./map.geojson')
    print("Fetching OSM data for: " + str(bbox))
    
    print("Saving buffer")
    save_buffer_polygon(buffer)
    print("Downloading buildings")
    download_features_to_layer(buffer, "building", {"building" : True})
    print("Downloading roads")
    download_features_to_layer(buffer, "road", road_tags)
    print("Downloading trails")
    download_features_to_layer(buffer, "trail", trail_tags)
    print("Downloading landcover")
    download_features_to_layer(buffer, "landcover", landcover_tags)
    print("Downloading park areas")
    download_features_to_layer(buffer, "park", park_area_tags)
    print("Downloading hydrography")
    download_features_to_layer(buffer, "hydro", hydro_tags)
    print("Downloading railways")
    download_features_to_layer(buffer, "railway", railway_tags)
    
    
    # print("Downloading POIs")
    # download_features_to_layer(buffer, "poi", trail_poi_tags)

    print("Done")