import json
from pathlib import Path
from typing import Iterable, Tuple, cast

import gpxpy
from shapely.geometry import (
    shape,
    GeometryCollection,
    Polygon,
    LineString,
    MultiLineString,
    MultiPolygon,
)
from shapely.ops import unary_union, transform
from pyproj import Transformer

from lib.BBox import BBox

# BUFFER_RADIUS = 500  # meters


def _load_geometries(path: Path):
    """Load geometries from GeoJSON or GPX."""
    if path.suffix.lower() == ".gpx":
        return _load_gpx(path)

    with open(path) as f:
        data = json.load(f)

    if data.get("type") == "FeatureCollection":
        return [
            shape(feature["geometry"])
            for feature in data["features"]
            if feature.get("geometry")
        ]

    if data.get("type") == "Feature":
        return [shape(data["geometry"])]

    return [shape(data)]


def _load_gpx(path: Path):
    """Convert GPX tracks/routes to LineStrings."""
    with open(path) as f:
        gpx = gpxpy.parse(f)

    geometries = []

    for track in gpx.tracks:
        for segment in track.segments:
            coords = [(p.longitude, p.latitude) for p in segment.points]
            if len(coords) >= 2:
                geometries.append(LineString(coords))

    for route in gpx.routes:
        coords = [(p.longitude, p.latitude) for p in route.points]
        if len(coords) >= 2:
            geometries.append(LineString(coords))

    return geometries


def create_buffer(file_path: str, buffer_radius) -> Tuple[Polygon, "BBox"]:
    """
    Create a buffer around GeoJSON or GPX geometries and compute a bounding box.

    Supports:
    - LineString / MultiLineString
    - Polygon / MultiPolygon
    - Feature / FeatureCollection
    - GPX tracks & routes

    :param file_path: Path to GeoJSON or GPX file
    :return: (buffer polygon, bounding box)
    """
    path = Path(file_path)
    geometries = _load_geometries(path)

    if not geometries:
        raise ValueError("No geometries found in input file")

    merged = unary_union(geometries)

    if not isinstance(
        merged,
        (
            LineString,
            MultiLineString,
            Polygon,
            MultiPolygon,
            GeometryCollection,
        ),
    ):
        raise TypeError(f"Unsupported geometry type: {type(merged)}")

    lon, lat = merged.centroid.coords[0]
    zone = int((lon + 180) / 6) + 1
    utm_epsg = 32600 + zone if lat >= 0 else 32700 + zone
    utm_crs = f"EPSG:{utm_epsg}"

    to_utm = Transformer.from_crs(4326, utm_crs, always_xy=True).transform
    to_wgs = Transformer.from_crs(utm_crs, 4326, always_xy=True).transform

    merged_utm = transform(to_utm, merged)
    buffer_utm = cast(
        Polygon,
        merged_utm.buffer(buffer_radius).simplify(200),
    )
    buffer = transform(to_wgs, buffer_utm)

    minx, miny, maxx, maxy = buffer.bounds

    bbox = BBox(
        south=miny,
        north=maxy,
        west=minx,
        east=maxx,
    )

    return buffer, bbox

    
    