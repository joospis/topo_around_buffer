import os
from pathlib import Path
import osmnx
from shapely import Polygon


poi_tags = {
    "natural": ["peak", "saddle"],
    "tourism": ["camp_site", "wilderness_hut", "alpine_hut"],
    "amenity": ["post_office", "shelter"],
    "shelter_type": ["lean_to", "basic_hut"]
}

def download_pois(polygon: Polygon, output_path: Path):
    """
    Downloads peaks, campsites, shelters, and post offices.
    """
    print(f" - Downloading POIs to {output_path.name}...")
    
    # Fetch features
    gdf = osmnx.features_from_polygon(polygon, dict(poi_tags))
    
    if gdf.empty:
        print(f"Warning: No POIs found for {output_path.name}")
        return

    gdf = gdf.clip(polygon)

    gdf["geometry"] = gdf.geometry.centroid
    os.makedirs(str(output_path.parent), exist_ok=True)
    
    # gdf.to_file(output_path, driver="GeoJSON")
    with open(output_path, "w") as f:
        f.write(gdf.to_json(na="drop"))