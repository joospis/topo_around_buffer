from pathlib import Path
import subprocess


def gen_hillshade_tiles(dir, zlevel: int = 9):

    input_hillshade = Path(dir + "/hillshade.tif")
    output_mbtiles = Path(dir + "/hillshade.mbtiles")
    temp_tif = Path(dir + "/hillshade_3857_alpha.tif")

    commands = [
        [
            "gdalwarp",
            "-t_srs", "EPSG:3857",
            "-srcnodata", "0",
            "-dstnodata", "0",
            "-dstalpha",
            str(input_hillshade),
            str(temp_tif),
        ],
        [
            "gdal_translate",
            "-of", "MBTiles",
            "-co", "TILE_FORMAT=WEBP",
            "-co", f"ZLEVEL={zlevel}",
            str(temp_tif),
            str(output_mbtiles),
        ],
        [
            "gdaladdo",
            "-r", "nearest",
            str(output_mbtiles),
            "2", "4", "8", "16", "32", "64", "128", "256",
        ],
    ]

    for cmd in commands:
        subprocess.run(cmd, check=True)

    return output_mbtiles


if __name__ == "__main__":
    gen_hillshade_tiles("./out")