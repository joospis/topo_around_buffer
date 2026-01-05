# Buffered Line to Vector Tiles

This project generates vector tiles for a geographic area defined by buffering a trail LineString into a Polygon.

## Overview

### 1. Define the Area of Interest
A trail is represented as a `LineString`, sourced from a GPX file for the trail being mapped.  
For example, a GPX file of the Long Trail can be downloaded from the Fastest Known Time (FKT) website.

### 2. Buffer the LineString
The LineString is buffered to create a Polygon that defines the area of interest for data extraction.

### 3. Download OpenStreetMap Features
Using the Python package **osmnx**, OpenStreetMap (OSM) features are downloaded within the buffered Polygon.

The following OSM features are included:
- Roads
- Trails
- Land cover
- Boundaries
- Hydrography
- Railways
- Building footprints
- Backcountry campsites, lean-tos, and wilderness huts
- Mountain names

### 4. Download and Process Elevation Data
Digital Elevation Model (DEM) data is downloaded from **OpenTopography**:

- The project uses **NASADEM Global DEM**, a modern, reprocessed, and more accurate version of the original SRTM 30 m dataset.
- This DEM is used to generate:
  - Contour lines
  - Hillshading

These derivatives are created using **GDAL** tools.

## Output

The processed vector and raster-derived features are prepared for conversion into vector tiles, suitable for use in web maps and GIS applications.


