from typing import NamedTuple

class BBox(NamedTuple):
    south: float
    north: float
    west: float
    east: float
    
    # Alias properties
    @property
    def min_lat(self) -> float:
        return self.south

    @property
    def max_lat(self) -> float:
        return self.north

    @property
    def min_lon(self) -> float:
        return self.west

    @property
    def max_lon(self) -> float:
        return self.east

    @property
    def xmin(self) -> float:
        return self.west

    @property
    def ymin(self) -> float:
        return self.south

    @property
    def xmax(self) -> float:
        return self.east

    @property
    def ymax(self) -> float:
        return self.north