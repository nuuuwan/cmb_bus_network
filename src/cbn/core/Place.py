import os
from dataclasses import dataclass
from math import floor
from typing import List

from geopy.geocoders import Nominatim
from utils_future import JSONFile, Log

log = Log("Place")


@dataclass
class Place:
    name: str
    latlng: List[float]

    PRECISION = 6
    GRID_LATITUDE = 0.01
    GRID_LONGITUDE = 0.01

    @classmethod
    def get_data_file(cls) -> JSONFile:
        return JSONFile(os.path.join("data", "places.json"))

    def fill_latlng(self):
        if self.latlng is not None:
            return False

        geolocator = Nominatim(user_agent="cmb_bus_network")
        location = geolocator.geocode(
            f"{self.name}, Colombo, Sri Lanka", timeout=10
        )
        if location is not None:
            self.latlng = [
                round(location.latitude, self.PRECISION),
                round(location.longitude, self.PRECISION),
            ]
            log.info(f"{self.name} -> {self.latlng}")
            return True

        log.error(f"Could not find latlng for {self.name}")
        return False

    @classmethod
    def list(cls) -> list["Place"]:
        data_file = cls.get_data_file()
        idx = data_file.read()
        return [cls(name, latlng) for name, latlng in idx.items()]

    @classmethod
    def fill_all_latlng(cls):
        places = cls.list()
        n_filled = 0
        for place in places:
            if place.fill_latlng():
                n_filled += 1
        if n_filled > 0:
            data_file = cls.get_data_file()
            places.sort(key=lambda p: p.name)
            idx = {
                place.name: [round(x, cls.PRECISION) for x in place.latlng]
                for place in places
            }
            data_file.write(idx)
            log.info(f"Filled latlng for {n_filled} places")

    @classmethod
    def analyze_coverage(cls):
        places = [place for place in cls.list() if place.latlng is not None]
        occupied = {
            (
                floor(place.latlng[0] / cls.GRID_LATITUDE),
                floor(place.latlng[1] / cls.GRID_LONGITUDE),
            )
            for place in places
        }
        latitude_cells = range(
            min(cell[0] for cell in occupied),
            max(cell[0] for cell in occupied) + 1,
        )
        longitude_cells = range(
            min(cell[1] for cell in occupied),
            max(cell[1] for cell in occupied) + 1,
        )
        all_cells = {
            (latitude, longitude)
            for latitude in latitude_cells
            for longitude in longitude_cells
        }
        uncovered = all_cells - occupied
        n_all = len(all_cells)
        n_covered = n_all - len(uncovered)
        log.info("-" * 32)
        log.info(f"Total grid cells: {n_all}")
        log.info(f"Covered grid cells: {n_covered}")
        log.info(f"Uncovered grid cells: {len(uncovered)}")
        log.info(f"Coverage: {n_covered / n_all:.2%}")
        return uncovered
