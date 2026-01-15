
import argparse
from pathlib import Path
import os

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

def main():
    parser = argparse.ArgumentParser("update-db-pois")
    
    parser.add_argument(
            "pois_file", 
            help="A geojson feature collection containing all the POI features to be added or updated.", 
            type=Path
        )
    
    args = parser.parse_args()