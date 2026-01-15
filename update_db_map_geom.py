import argparse
from pathlib import Path
import os
from supabase import create_client, Client
import geopandas as gpd
from dotenv import load_dotenv
from lib import constants

def main():
    parser = argparse.ArgumentParser("update-db-map-geom")
    parser.add_argument(
        "fgb_path", 
        help="Path to a .fgb file containing the bounding polygon of the map.", 
        type=Path
    )
    parser.add_argument(
        "map_name",
        help="The snake_case_name of the product/map to update (product.snake_case_name)"
    )
    parser.add_argument(
        "--env",
        type=Path,
        default=Path(__file__).parent / ".env",
        help="Path to a .env file containing the required SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY variables"
    )
    
    args = parser.parse_args()
    
    load_dotenv((Path)(args.env).absolute())
    
    SUPABASE_URL = os.environ["SUPABASE_URL"]
    SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # Read the FlatGeobuf file
    print(f"Reading geometry from {args.fgb_path}...")
    gdf = gpd.read_file(str((Path)(args.fgb_path).absolute()))
    
    if gdf.empty:
        print(f"{constants.YELLOW}Warning: No geometries found in {args.fgb_path}{constants.RESET}")
        return
    
    if len(gdf) > 1:
        print(f"{constants.YELLOW}Warning: Multiple geometries found, using the first one{constants.RESET}")
    
    # Get the first geometry and convert to WKT
    geom = gdf.iloc[0].geometry
    geom_wkt = geom.wkt
    
    # Check if product exists
    print(f"Looking up product: {args.map_name}...")
    existing = supabase.table('products').select('id, snake_case_name').eq('snake_case_name', args.map_name).execute()
    
    if not existing.data:
        print(f"{constants.YELLOW}Error: Product with snake_case_name '{args.map_name}' not found{constants.RESET}")
        return
    
    product_id = existing.data[0]['id'] # type: ignore
    
    # Update the product geometry
    print(f"Updating geometry for product: {args.map_name} (id: {product_id})...")
    
    try:
        supabase.table('products').update({
            "geom": f"SRID=4326;{geom_wkt}"
        }).eq('id', product_id).execute()
        
        print(f"{constants.YELLOW}Successfully updated geometry for {args.map_name}{constants.RESET}")
    except Exception as e:
        print(f"{constants.RED}Failed to update product geometry: {e}{constants.RESET}")

if __name__ == "__main__":
    main()