import os
from pathlib import Path
import osmnx
from shapely import Polygon
import geopandas as gpd
from lib.create_buffer import create_buffer
import pandas as pd

from lib.graph_tools import add_z_to_points


poi_tags = {
    "natural": ["peak", "saddle"],
    "tourism": ["camp_site", "wilderness_hut", "alpine_hut"],
    "amenity": ["post_office", "shelter"],
    # "shelter_type": ["lean_to", "basic_hut"]
}

water_tags = {
    "drinking_water": ["yes", "conditional"]
}

def get_topo_app_type(row):
    # print() # Some are printing as 'nan' but comparing with 'nan', np.nan, and None does not work
    # if row['name'] == "Kid Gore Shelter":
    #     print(row)
    fee = ''
    if 'fee' in row and row['fee'] == 'yes':
        fee = '_fee'
    if 'natural' in row and row['natural'] == 'peak':
        return 'peak'
    if 'natural' in row and row['natural'] == 'saddle':
        return 'saddle'
    if 'amenity' in row and row['amenity'] == 'post_office':
        return 'post_office'
    # if 'amenity' in row and row['amenity'] == 'shelter' and ('shelter_type' not in row or row['shelter_type'] == 'lean_to'):
    #     return 'shelter'
    if (pd.isna(row['shelter_type'])) and row['amenity'] == 'shelter':
        return 'shelter' + fee
    if 'shelter_type' in row and row['shelter_type'] == 'lean_to':
        return 'shelter' + fee
    if 'tourism' in row and row['tourism'] == 'camp_site':
        return 'camp_site'
    if 'shelter_type' in row and row['shelter_type'] == 'basic_hut':
        return 'hut' + fee
    if 'tourism' in row and row['tourism'] in ['wilderness_hut', 'alpine_hut']:
        return 'hut' + fee
    return None

def download_pois(polygon: Polygon, output_path: Path):
    """
    Downloads peaks, campsites, shelters, and post offices.
    """
    print(f" - Downloading POIs to {output_path.name}...")
    
    gdf = osmnx.features_from_polygon(polygon, dict(poi_tags))
    
    if gdf.empty:
        print(f"Warning: No POIs found for {output_path.name}")
        return
    
    # gdf = gdf.to_crs(gdf.estimate_utm_crs())
    
    # Remove any features without a name
    gdf = gdf[gdf['name'].notna()]
    
    gdf["geometry"] = gdf.geometry.centroid # Convert non-points to points
    
    gdf['topo_app_type'] = gdf.apply(get_topo_app_type, axis=1)
    
    # Remove any features without a topo_app_type
    gdf = gdf[gdf['topo_app_type'].notna()]

    gdf = gdf.clip(polygon)
    
    gdf = add_z_to_points(gdf, output_path.parent / "temp/cropped_meters.tif")

    os.makedirs(str(output_path.parent), exist_ok=True)
    
    with open(output_path, "w") as f:
        f.write(gdf.to_json(na="drop"))

def download_water_sources(polygon: Polygon, output_path: Path):
    """
    Downloads drinking water sources, excluding shelters and wilderness huts.
    """
    print(f" - Downloading water sources to {output_path.name}...")
    
    gdf = osmnx.features_from_polygon(polygon, dict(water_tags))
    
    if gdf.empty:
        print(f"Warning: No water sources found for {output_path.name}")
        return
    
    # Exclude shelters and wilderness/alpine huts
    exclude_amenity = ['shelter']
    exclude_tourism = ['wilderness_hut', 'alpine_hut', 'camp_site']
    
    if 'amenity' in gdf.columns:
        gdf = gdf[~gdf['amenity'].isin(exclude_amenity)]
    if 'tourism' in gdf.columns:
        gdf = gdf[~gdf['tourism'].isin(exclude_tourism)]
    
    if gdf.empty:
        print(f"Warning: No water sources remain after filtering for {output_path.name}")
        return

    gdf["geometry"] = gdf.geometry.centroid
    gdf = gdf.clip(polygon)
    gdf = add_z_to_points(gdf, output_path.parent / "temp/cropped_meters.tif")
    
    os.makedirs(str(output_path.parent), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(gdf.to_json(na="drop"))

if __name__ == "__main__":
    buffer, bbox = create_buffer('./long_trail.gpx', 4000)
    # download_pois(buffer, Path('./out/pois.geojson'))
    download_water_sources(buffer, Path('./out/water_sources.geojson'))