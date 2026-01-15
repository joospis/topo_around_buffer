
import argparse
from pathlib import Path
import os
import pandas as pd
from supabase import create_client, Client
import geopandas as gpd
from dotenv import load_dotenv
import ast

from tqdm import tqdm

from lib import constants

def main():
    parser = argparse.ArgumentParser("update-db-pois")
    
    parser.add_argument(
            "geojson_path", 
            help="Path to a geojson feature collection containing all the POI features to be added or updated.", 
            type=Path
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
    
    gdf = gpd.read_file(str((Path)(args.geojson_path).absolute()))
    
    # Prepare records for insertion
    records = []
    for idx, row in gdf.iterrows():
        # Convert geometry to WKT (Well-Known Text) for PostGIS
        geom_wkt = row.geometry.wkt
        
        
        osm_type, osm_id = ast.literal_eval(row.get('id')) # type: ignore
        
        # Build record
        record = {
            "geom": f"SRID=4326;{geom_wkt}",  # PostGIS format with SRID
            "name": row.get('name') if 'name' in row and pd.notna(row.get('name')) else None,
            "category": row.get('topo_app_type'),
            # "description": (str)(row.get('description')) + " (Imported from OpenStreetMap; may be missing details)" if 'description' in row and pd.notna(row.get('description')) else None,
            "osm_type": osm_type,
            "osm_id": osm_id,
            "source": "osm"
        }
        
        records.append(record)
    count = 0
    for record in tqdm(records, desc="Upserting POIs"):
        try:
            if record['osm_id'] is not None and record['osm_type'] is not None:
                # Check if exists
                existing = supabase.table('pois').select('id').eq('osm_id', record['osm_id']).eq('osm_type', record['osm_type']).execute()
                
                if existing.data:
                    # Existing record found - prepare update
                    update_record = record.copy()
                    
                    # If existing record already has a description, don't overwrite it
                    # if existing.data[0].get('description') is not None: # type: ignore
                    #     update_record.pop('description', None)  # Remove description from update
                    
                    supabase.table('pois').update(update_record).eq('id', existing.data[0]['id']).execute() # type: ignore
                else:
                    # Insert new
                    supabase.table('pois').insert(record).execute()
            else:
                # No osm_id or osm_type, just insert
                supabase.table('pois').insert(record).execute()
        except Exception as e:
            tqdm.write(
                f"{constants.YELLOW}Failed to upsert POI {constants.RESET}"
                f"osm_id={record.get('osm_id')} "
                f"osm_type={record.get('osm_type')}: {e.message}" # type: ignore
            )
            continue
    
    print(f"Upserted {len(records)} POIs")
    
    