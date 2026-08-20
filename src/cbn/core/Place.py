import os
import random
import webbrowser
from dataclasses import dataclass
from functools import cache
from math import floor
from typing import List

from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from gig import Ent, EntType
from shapely.geometry import Point
from shapely.ops import unary_union
from utils_future import JSONFile, Log

log = Log("Place")


@dataclass
class Place:
    name: str
    latlng: List[float]

    PRECISION = 6
    GRID_LATITUDE = 0.007
    GRID_LONGITUDE = 0.007
    COLOMBO_DSD_IDS = {"LK-1103", "LK-1127"}

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
    @cache
    def get_colombo_boundary(cls):
        geometries = []
        for gnd in Ent.list_from_type(EntType.GND):
            if gnd.dsd_id in cls.COLOMBO_DSD_IDS:
                geometries.extend(gnd.geo().geometry)
        return unary_union(geometries)

    @classmethod
    def get_grid_cells(cls):
        boundary = cls.get_colombo_boundary()
        min_lng, min_lat, max_lng, max_lat = boundary.bounds
        latitude_cells = range(
            floor(min_lat / cls.GRID_LATITUDE),
            floor(max_lat / cls.GRID_LATITUDE) + 1,
        )
        longitude_cells = range(
            floor(min_lng / cls.GRID_LONGITUDE),
            floor(max_lng / cls.GRID_LONGITUDE) + 1,
        )
        return {
            (latitude, longitude)
            for latitude in latitude_cells
            for longitude in longitude_cells
            if boundary.covers(
                Point(
                    (longitude + 0.5) * cls.GRID_LONGITUDE,
                    (latitude + 0.5) * cls.GRID_LATITUDE,
                )
            )
        }

    @classmethod
    def get_uncovered_grid_cells(cls, places=None):
        places = cls.list() if places is None else places
        occupied = {
            (
                floor(place.latlng[0] / cls.GRID_LATITUDE),
                floor(place.latlng[1] / cls.GRID_LONGITUDE),
            )
            for place in places
            if place.latlng is not None
        }
        return cls.get_grid_cells() - occupied

    @classmethod
    def open_random_uncovered_cells_in_google_maps(cls, limit=10):
        uncovered = sorted(cls.get_uncovered_grid_cells())
        selected = random.sample(uncovered, min(limit, len(uncovered)))
        midpoints = [
            (
                (latitude + 0.5) * cls.GRID_LATITUDE,
                (longitude + 0.5) * cls.GRID_LONGITUDE,
            )
            for latitude, longitude in selected
        ]
        log.info(
            f"Opening {len(midpoints)} uncovered grid cells in Google Maps"
        )
        for latitude, longitude in midpoints:
            url = (
                "https://www.google.com/maps/search/?api=1&query="
                f"{latitude},{longitude}"
            )
            webbrowser.open(url, new=2)
        return midpoints

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
        colombo_cells = cls.get_grid_cells()
        uncovered = cls.get_uncovered_grid_cells()
        n_all = len(colombo_cells)
        n_covered = n_all - len(uncovered)
        centroid = cls.get_colombo_boundary().centroid
        latitude = centroid.y
        longitude = centroid.x
        height_km = geodesic(
            (latitude, longitude),
            (latitude + cls.GRID_LATITUDE, longitude),
        ).km
        width_km = geodesic(
            (latitude, longitude),
            (latitude, longitude + cls.GRID_LONGITUDE),
        ).km
        area_km2 = width_km * height_km
        log.info("-" * 32)
        log.info(
            f"Grid dimensions: {width_km * 1_000:.2f} m x "
            f"{height_km * 1_000:.2f} m"
        )
        log.info(
            f"Grid area: {area_km2:.4f} km² "
            f"({area_km2 * 1_000_000:.0f} m²)"
        )
        log.info(f"Total grid cells: {n_all}")
        log.info(f"Covered grid cells: {n_covered}")
        log.info(f"Uncovered grid cells: {len(uncovered)}")
        log.info(f"Coverage: {n_covered / n_all:.2%}")
        return uncovered
