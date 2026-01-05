from pathlib import Path
from glob import glob
import shlex
import subprocess

from lib import constants

ZOOM_LEVEL=14
HILLSHADE_ZOOM=9
OSM_SIMPLIFICATION=5

def generate_hillshade_tiles(input_path: Path, output_path: Path):
    temp_tif = input_path.parent / "temp.tif"
    commands = [
        [
            "gdalwarp",
            "-t_srs", "EPSG:3857",
            "-srcnodata", "0",
            "-dstnodata", "0",
            "-dstalpha",
            str(input_path),
            str(temp_tif),
        ],
        [
            "gdal_translate",
            "-of", "MBTiles",
            "-co", "TILE_FORMAT=WEBP",
            "-co", f"ZLEVEL={HILLSHADE_ZOOM}",
            str(temp_tif),
            str(output_path),
        ],
        [
            "gdaladdo",
            "-r", "nearest",
            str(output_path),
            "2", "4", "8", "16", "32", "64", "128", "256",
        ],
    ]

    for cmd in commands:
        subprocess.run(cmd, check=True)
    
    if temp_tif.exists():
        temp_tif.unlink()

def generate_osm_tiles(layers_path: Path, output_path: Path):
    input_files = layers_path.glob("*")

    if not input_files:
        print(f"Error: No input files found")
        return

    input_files_string = " ".join([shlex.quote(str(f)) for f in input_files])
    
    command = f'tippecanoe -o {str(output_path)} -z{str(ZOOM_LEVEL)} -f {input_files_string} --drop-densest-as-needed --simplification={str(OSM_SIMPLIFICATION)} --detect-shared-borders --read-parallel'
    args = shlex.split(command)
    try:
        result = subprocess.run(
            args,
            check=True,
            text=True  
        )

    except subprocess.CalledProcessError as e:
        print(f"Tippecanoe failed with exit code {e.returncode}")
        print("Error Output:\n", e.stderr)
    except FileNotFoundError:
        print("\nError: tippecanoe command not found. Make sure it is installed and in your system PATH.")

def generate_contour_tiles(input_path: Path, output_path: Path):
    command = [
        "tippecanoe",
        "-o", str(output_path),
        f"-z{ZOOM_LEVEL}",
        "-f", str(input_path),
        "-l", "contour",
        "--drop-densest-as-needed",
        "--detect-shared-borders",
        "--read-parallel",
    ]
    try:
        subprocess.run(command, check=True, text=True)
    except subprocess.CalledProcessError as e:
        print(f"Tippecanoe failed with exit code {e.returncode}")
        print("Error Output:\n", e.stderr)
        
def main(output_dir: Path):
    print(f"{constants.YELLOW}Generating contour_meter.pmtiles...{constants.RESET}")
    generate_contour_tiles(output_dir / "temp/contour_meter.fgb", output_dir / "contour_meter.pmtiles")
    print(f"{constants.YELLOW}Generating contour_feet.pmtiles...{constants.RESET}")
    generate_contour_tiles(output_dir / "temp/contour_feet.fgb", output_dir / "contour_feet.pmtiles")
    print(f"{constants.YELLOW}Generating hillshade.mbtiles...{constants.RESET}")
    generate_hillshade_tiles(output_dir / "temp/hillshade.tif", output_dir / "hillshade.mbtiles")
    print(f"{constants.YELLOW}Generating osm.pmtiles...{constants.RESET}")
    generate_osm_tiles(output_dir / "temp/osm_layers", output_dir / "osm.pmtiles")

if __name__ == "__main__":
    output_dir = Path("./out3").resolve()
    main(output_dir)