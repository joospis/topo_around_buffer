from array import array
import math
import os
import dotenv
import rasterio
from rasterio.mask import mask
from shapely.geometry import Polygon
from shapely.geometry import mapping
from BBox import BBox
from urllib.request import urlretrieve
from osgeo import gdal, ogr, osr
from create_buffer import create_buffer
import numpy as np

dirname = os.path.dirname(__file__)
env_path = os.path.join(dirname, '../.env')
dotenv.load_dotenv(env_path)

DATASET = "NASADEM"

gdal.UseExceptions()

def get_open_topograpghy_url(bbox: BBox) -> str :
    try:
        api_key: str = os.environ['OPEN_TOPOGRAPHY_API_KEY']
        return f"https://portal.opentopography.org/API/globaldem?demtype={DATASET}&south={bbox.south}&north={bbox.north}&west={bbox.west}&east={bbox.east}&outputFormat=GTiff&API_Key={api_key}"
    except KeyError:
        print("OPEN_TOPOGRAPHY_API_KEY environment variable not set.")
        raise


def bbox_to_filename(bbox: BBox):
    # Convert floats to safe string: replace '.' with '_'
    def fmt(f): 
        return str(f).replace('.', '_')
    
    return f"{DATASET}_s_{fmt(bbox.south)}_n_{fmt(bbox.north)}_w_{fmt(bbox.west)}_e_{fmt(bbox.east)}.tif"

def download_from_bbox(bbox: BBox) -> str:
    """
    Download a GeoTIFF from OpenTopography for the given bounding box.

    Constructs an OpenTopography download URL using the provided bounding box,
    retrieves the dataset, and saves it locally as a GeoTIFF file.

    :param bbox: Geographic bounding box defining the area to download.
    :type bbox: BBox
    :return: Path to the downloaded GeoTIFF file.
    :rtype: str
    """
    url = get_open_topograpghy_url(bbox)
    filename = os.path.join(dirname, f'../data/dem', bbox_to_filename(bbox))
    if os.path.isfile(filename):
        print(f"DEM file for bounds already exists, skipping download")
        return filename
    return urlretrieve(url, filename)[0]

def crop_dem_to_buffer(input_path: str, buffer: Polygon, output_path: str | None = None):
    """
    Crop a DEM raster to the extent of a buffer polygon and save the result.

    :param input_path: Path to the input DEM GeoTIFF.
    :param output_path: Path where the cropped DEM will be saved.
    :param buffer: Shapely Polygon defining the crop area.
    :return: Path to the cropped DEM.
    :rtype: str
    """
    
    if output_path == None:
        output_path = './out/dem/cropped_dem.tif'
        os.makedirs('./out/dem', exist_ok=True)
    
    geom = [mapping(buffer)]

    with rasterio.open(input_path) as src:
        out_image, out_transform = mask(src, geom, crop=True)
        out_meta = src.meta.copy()

    out_meta.update({
        "driver": "GTiff",
        "height": out_image.shape[1],
        "width": out_image.shape[2],
        "transform": out_transform
    })

    with rasterio.open(output_path, "w", **out_meta) as dest:
        dest.write(out_image)
    
    return output_path

def generate_contours(input_path: str, output_path: str | None = None):
    METRIC_INTERVAL = 10 # contour line every nth meters
    IMPERIAL_INTERVAL = 30 # contour line every nth feet
    INDEX_EVERY = 5
    
    M_TO_FT = 3.28084
    FT_TO_M = 1 / M_TO_FT
    
    if output_path is None:
        os.makedirs("./out/layers/", exist_ok=True)
        output_path = "./out/layers/contours.fgb"
    
    raster_dataset: gdal.Dataset | None = gdal.Open(input_path)
    
    if raster_dataset is None:
        raise RuntimeError(f"Failed to open DEM: {input_path}")
    
    raster_band: gdal.Band = raster_dataset.GetRasterBand(1)
    projection: osr.SpatialReference = osr.SpatialReference(wkt=raster_dataset.GetProjection())
    elevation_array: np.ndarray = raster_band.ReadAsArray() # type: ignore
    dem_NaN = -32768 # represents any potential missing data in DEM
    
    dem_max = elevation_array.max() #finds max height in dem
    dem_min =elevation_array[elevation_array != dem_NaN].min() #filters out missing data and finds min height in dem
    
    dem_min_ft = dem_min * M_TO_FT # dem_min in feet
    dem_max_ft = dem_max * M_TO_FT# dem_max in feet
    
    driver: gdal.Driver = ogr.GetDriverByName("FlatGeobuf")
    output_dataset: gdal.Dataset = driver.CreateDataSource(output_path)
    
    layer: ogr.Layer = output_dataset.CreateLayer("contours", projection)
    layer.CreateField(ogr.FieldDefn("ele_m", ogr.OFTReal))
    layer.CreateField(ogr.FieldDefn("ele_ft", ogr.OFTReal))
    layer.CreateField(ogr.FieldDefn("type", ogr.OFTString))  # index / intermediate
    layer.CreateField(ogr.FieldDefn("units", ogr.OFTString))
    
    metric_start = math.ceil(dem_min / METRIC_INTERVAL) * METRIC_INTERVAL
    metric_end   = math.floor(dem_max / METRIC_INTERVAL) * METRIC_INTERVAL
    metric_levels = list(range(metric_start, metric_end + METRIC_INTERVAL, METRIC_INTERVAL))
    
    imperial_start = math.ceil(dem_min_ft / IMPERIAL_INTERVAL) * IMPERIAL_INTERVAL
    imperial_end   = math.floor(dem_max_ft / IMPERIAL_INTERVAL) * IMPERIAL_INTERVAL

    imperial_levels_m = [
        ft * FT_TO_M
        for ft in range(imperial_start, imperial_end + IMPERIAL_INTERVAL, IMPERIAL_INTERVAL)
    ]
    
    levels = [
        ("meters", metric_levels),
        ("feet", imperial_levels_m),
    ]
    
    for unit_name, level in levels:
        mem_drv = ogr.GetDriverByName("MEM")
        temp_ds = mem_drv.CreateDataSource("")
        temp_layer = temp_ds.CreateLayer(
            "",
            projection,
            geom_type=ogr.wkbLineString
        )
        temp_layer.CreateField(ogr.FieldDefn("ele", ogr.OFTReal))

        gdal.ContourGenerate(
            raster_band,
            0,                      # contourInterval (0 = fixed levels)
            0,                      # contourBase
            level,          # fixedLevels array
            1,                      # useNoData
            dem_NaN,
            temp_layer,
            -1,                     # idField (optional)
            0                       # elevField ("ele")
        )

        i = 0
        for feat in temp_layer:
            ele = feat.GetFieldAsDouble("ele")
            
            out_feat = ogr.Feature(layer.GetLayerDefn())
            
            if i % INDEX_EVERY == 0:
                out_feat.SetField("type", "index")
            else:
                out_feat.SetField("type", "intermediate")
                
            i += 1

            out_feat.SetGeometry(feat.GetGeometryRef().Clone())
            out_feat.SetField("ele_m", ele)
            out_feat.SetField("ele_ft", round(ele * M_TO_FT, 1))
            out_feat.SetField("units", unit_name)

            layer.CreateFeature(out_feat)
            out_feat = None

        temp_ds = None  # cleanup
    
    output_dataset.Destroy()


def generate_hillshade(input_path: str, output_path: str | None = None):
    """
    Generate a hillshade raster from an elevation raster.

    Parameters
    ----------
    input_path : str
        Path to input DEM (e.g. GeoTIFF).
    output_path : str
        Path where hillshade GeoTIFF will be written.
    """
    if output_path == None:
        output_path = './out/dem/hillshade.tif'
        os.makedirs('./out/dem', exist_ok=True)
        
    dem_ds = gdal.Open(input_path, gdal.GA_ReadOnly)
    if dem_ds is None:
        raise RuntimeError(f"Failed to open DEM: {input_path}")

    gdal.DEMProcessing(
        destName=output_path,
        srcDS=dem_ds,
        processing="hillshade",
        options=gdal.DEMProcessingOptions(
            azimuth=315,     # light from NW (standard cartographic default)
            altitude=45,     # sun angle
            zFactor=1.0,     # vertical exaggeration
            scale=1.0,       # set to 111120 if DEM is in degrees
            computeEdges=True
        ),
    )

    dem_ds = None

if __name__ == "__main__":
    buffer, bbox = create_buffer('./map.geojson')
    print("Fetching DEM for: " + str(bbox))
    raw = download_from_bbox(bbox)
    print("Cropping DEM to buffer")
    cropped = crop_dem_to_buffer(raw, buffer)
    print("Generating contours")
    generate_contours(cropped)
    print("Generating hillshade")
    generate_hillshade(cropped)
    print("Done")
    