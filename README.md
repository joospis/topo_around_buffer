#Buffered Line to Vector Tiles

First a geographic area will be represented by buffering LineString to form a Polygon. 
The linestring will come from a GPX of whichever trail is being mapped. For example, a GPX of the long trail can be
downloaded from the FKT (Fastest Known Time) website.

This will use python package osmnx to download OSM features from the Polygon (buffered LineString).
The features included from OSM (Open Street Map) will be:
 - Roads
 - Trails
 - Landcover
 - Boundries
 - Hydrography
 - Rail
 - Building footprints
 - Backcountry campsites, lean-tos, wilderness huts
 - Mountain names

DEM data will be downloaded from OpenTopography
 - It will download NASADEM Global DEM, a recent, more accurate, reproccesed verision of the original SRTM 30m data
 - This data will be used to generate contour lines and hillshading using GDAL functions

