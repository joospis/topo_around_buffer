# An OpenTopograpghy key is required to fetch the global DEM
# In the shell, set the OPENTOPOGRAPHY_API_KEY environment variable to the API key value

import os
from pathlib import Path
import subprocess
import warnings
from bmi_topography import Topography
import rasterio
from rasterio.mask import mask
from shapely.geometry import Polygon, mapping
from lib.BBox import BBox
from lib.create_buffer import create_buffer
from lib import constants


CONTOUR_METER_INTERVAL = 10
CONTOUR_METER_INDEX_INTERVAL = 100
CONTOUR_FEET_INTERVAL = 20
CONTOUR_FEET_INDEX_INTERVAL = 80

warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    module="bmi_topography.api_key",
)

def download_from_bbox(bbox: BBox) -> Path:
    """
    Download a GeoTIFF from OpenTopography for the given bounding box.

    :return: Path to the downloaded GeoTIFF file.
    """
    parent_dir = os.path.dirname(os.path.abspath(__file__))
    area = Topography(
        dem_type = "NASADEM",
        south = bbox.south,
        north = bbox.north,
        west = bbox.west,
        east = bbox.east,
        output_format = "GTiff",
        cache_dir = f"{parent_dir}/../dem_cache"
    )
    return area.fetch()

def crop_dem_to_buffer(input_path: Path, buffer: Polygon, output_path: Path) -> None:
    """
    Crop a DEM raster to the extent of a buffer polygon and save the result.
    """
    os.makedirs(str(output_path.parent), exist_ok=True)
    
    geom = [mapping(buffer)]

    with rasterio.open(str(input_path)) as src:
        out_image, out_transform = mask(src, geom, crop=True)
        out_meta = src.meta.copy()

    out_meta.update({
        "driver": "GTiff",
        "height": out_image.shape[1],
        "width": out_image.shape[2],
        "transform": out_transform
    })

    with rasterio.open(str(output_path), "w", **out_meta) as dest:
        dest.write(out_image)
        
def dem_to_feet(input_path: Path, output_path: Path):
    """
    Executes gdal_calc.py via a subprocess to convert DEM units.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    command = [
        "gdal_calc",
        "-A", str(input_path),
        "--outfile", str(output_path),
        "--calc", "A*3.28084",
        "--overwrite"
    ]

    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error processing {input_path.name}:")
        print(e.stderr)
        raise

def generate_hillshade(input_path: Path, output_path: Path, azimuth: int = 315, altitude: int = 45):
    """
    Generates a hillshade from a DEM.
    """
    command = [
        "gdaldem",
        "hillshade",
        str(input_path),
        str(output_path),
        "-az", str(azimuth),
        "-alt", str(altitude),
        "-of", "GTiff"
    ]
    
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"GDAL Error: {e.stderr}")
        raise

def generate_contours(input_path: Path, output_path: Path, interval: int, index_interval: int):
    """
    Generates contours from a DEM.
    """
    if output_path.exists():
        output_path.unlink()
        
    temp_gpkg = output_path.with_suffix(".gpkg")
    contour_cmd = [
        "gdal_contour",
        "-a", "elev",
        str(input_path),
        str(temp_gpkg),
        "-i", str(interval)
    ]
    try:
        subprocess.run(contour_cmd, check=True, capture_output=True, text=True)
        
        sql = f"SELECT *, CAST((CAST(elev AS INT) % {index_interval} = 0) AS INTEGER) AS is_index FROM contour"
        
        fgb_command = [
            "ogr2ogr",
            "-f", "FlatGeobuf",
            str(output_path),
            str(temp_gpkg),
            "-sql", sql,
            "-nln", output_path.stem,
            "-overwrite"
        ]
        
        subprocess.run(fgb_command, check=True, capture_output=True)
        
        if temp_gpkg.exists():
            temp_gpkg.unlink()
        
    except subprocess.CalledProcessError as e:
        print(f"Error: {e.stderr}")
        raise

def main(output_dir: Path, bbox: BBox, polygon: Polygon):
    print(f"{constants.YELLOW}Downloading DEM...{constants.RESET}")
    raw_dem_path: Path = download_from_bbox(bbox)
    temp_dir = output_dir / "temp"
    cropped_dem_m_path: Path = temp_dir / "cropped_meters.tif"
    cropped_dem_ft_path: Path = temp_dir / "cropped_feet.tif"
    print(f"{constants.YELLOW}Cropping DEM to buffer...{constants.RESET}")
    crop_dem_to_buffer(raw_dem_path, polygon, cropped_dem_m_path)
    print(f"{constants.YELLOW}Generating hillshade...{constants.RESET}")
    generate_hillshade(cropped_dem_m_path, temp_dir / "hillshade.tif")
    print(f"{constants.YELLOW}Converting DEM into imperial units...{constants.RESET}")
    dem_to_feet(cropped_dem_m_path, cropped_dem_ft_path)
    print(f"{constants.YELLOW}Creating contour lines in meters...{constants.RESET}")
    generate_contours(cropped_dem_m_path, temp_dir / "contour_meter.fgb", CONTOUR_METER_INTERVAL, CONTOUR_METER_INDEX_INTERVAL)
    print(f"{constants.YELLOW}Creating contour lines in feet...{constants.RESET}")
    generate_contours(cropped_dem_ft_path, temp_dir / "contour_feet.fgb", CONTOUR_FEET_INTERVAL, CONTOUR_FEET_INDEX_INTERVAL)
    # cropped_dem_m_path.unlink()
    cropped_dem_ft_path.unlink()
    
if __name__ == "__main__":
    buffer, bbox = create_buffer('./long_trail.gpx', 4000)
    output_dir = Path("./out3").resolve()
    main(output_dir, bbox, buffer)