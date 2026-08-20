import os
import random
import webbrowser
from collections import defaultdict
from dataclasses import dataclass
from functools import cache
from math import floor
from typing import List

from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from gig import Ent, EntType
from shapely.geometry import Point
from shapely.ops import unary_union
from utils_future import File, JSONFile, Log

log = Log("Place")


@dataclass
class Place:
    name: str
    latlng: List[float]

    PRECISION = 6
    GRID_LATITUDE = 0.006
    GRID_LONGITUDE = 0.006
    COLOMBO_DSD_IDS = {"LK-1103", "LK-1127"}

    @classmethod
    def get_data_file(cls) -> JSONFile:
        return JSONFile(os.path.join("data", "places.json"))

    @classmethod
    def get_removed_data_file(cls) -> JSONFile:
        return JSONFile(os.path.join("data", "places.removed.json"))

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
    def get_grid_cell(cls, place):
        return (
            floor(place.latlng[0] / cls.GRID_LATITUDE),
            floor(place.latlng[1] / cls.GRID_LONGITUDE),
        )

    @classmethod
    def _distance_to_grid_center(cls, place):
        latitude, longitude = cls.get_grid_cell(place)
        center_latitude = (latitude + 0.5) * cls.GRID_LATITUDE
        center_longitude = (longitude + 0.5) * cls.GRID_LONGITUDE
        return (place.latlng[0] - center_latitude) ** 2 + (
            place.latlng[1] - center_longitude
        ) ** 2

    @classmethod
    def _rewrite_removed_route_stops(cls, replacements):
        from cbn.core.Route import Route

        data_file = Route.get_data_file()
        route_data_list = data_file.read()
        for route_data in route_data_list:
            rewritten = [
                replacements.get(stop, stop) for stop in route_data["stops"]
            ]
            route_data["stops"] = [
                stop
                for index, stop in enumerate(rewritten)
                if index == 0 or stop != rewritten[index - 1]
            ]
        data_file.write(route_data_list)

    @classmethod
    def remove_grid_duplicates(cls):
        groups = defaultdict(list)
        for place in cls.list():
            groups[cls.get_grid_cell(place)].append(place)

        kept = []
        removed = []
        replacements = {}
        for group in groups.values():
            group.sort(
                key=lambda place: (
                    cls._distance_to_grid_center(place),
                    place.name,
                )
            )
            keeper = group[0]
            kept.append(keeper)
            removed.extend(group[1:])
            replacements.update(
                {place.name: keeper.name for place in group[1:]}
            )

        cls.get_data_file().write(
            {
                place.name: place.latlng
                for place in sorted(kept, key=lambda place: place.name)
            }
        )
        removed_data_file = cls.get_removed_data_file()
        removed_idx = (
            removed_data_file.read() if removed_data_file.exists() else {}
        )
        removed_idx.update({place.name: place.latlng for place in removed})
        removed_data_file.write(dict(sorted(removed_idx.items())))
        cls._rewrite_removed_route_stops(replacements)
        log.info(f"Wrote {File(os.path.join('data', 'places.removed.json'))}")
        log.info(f"Removed {len(removed)} duplicate-grid places")
        return removed

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
