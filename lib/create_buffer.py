import json
import shapely
from shapely.geometry import LineString, Polygon, shape
from BBox import BBox
from shapely.ops import transform
from pyproj import Transformer
from typing import cast

BUFFER_RADIUS = 4000

def create_buffer(file_path: str) -> tuple[Polygon, BBox]:
    """
    Load a LineString from GeoJSON, create a buffer polygon, and compute its bounding box.

    :param file_path: Path to a GeoJSON file containing a LineString geometry.
    :return: A tuple of (buffer polygon, bounding box).
    :raises TypeError: If the GeoJSON geometry is not a LineString.
    """
    with open(file_path) as f:
        geom = shape(json.load(f))    
    if not isinstance(geom, LineString):
        raise TypeError
    
    lon, lat = geom.centroid.coords[0]
    zone = int((lon + 180) / 6) + 1
    utm_crs = f"EPSG:{32600 + zone if lat >= 0 else 32700 + zone}"

    to_utm = Transformer.from_crs(4326, utm_crs, always_xy=True).transform
    to_wgs = Transformer.from_crs(utm_crs, 4326, always_xy=True).transform

    geom_utm = transform(to_utm, geom)
    buffer_utm = cast(Polygon, geom_utm.buffer(BUFFER_RADIUS).simplify(200))
    buffer = transform(to_wgs, buffer_utm)

    minx, miny, maxx, maxy = buffer.bounds

    bbox = BBox(
        south=miny,
        north=maxy,
        west=minx,
        east=maxx,
    )

    return buffer, bbox
    
    