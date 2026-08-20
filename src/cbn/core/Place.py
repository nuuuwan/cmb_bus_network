import os
import webbrowser
from dataclasses import dataclass
from functools import cache
from typing import List

import geopandas as gpd
import pandas as pd
from geopy.geocoders import Nominatim
from gig import Ent, EntType
from shapely.geometry import Point
from utils_future import JSONFile, Log

log = Log("Place")


@dataclass
class Place:
    name: str
    latlng: List[float]

    PRECISION = 6

    @classmethod
    def get_data_file(cls) -> JSONFile:
        return JSONFile(os.path.join("data", "places.json"))

    @classmethod
    def get_gnd_data_file(cls) -> JSONFile:
        return JSONFile(os.path.join("data", "places.gnd.json"))

    @staticmethod
    def get_cmb_gnds():
        gnds = Ent.list_from_type(EntType.GND)
        cmb_gnds = [
            gnd for gnd in gnds if gnd.dsd_id in ["LK-1103", "LK-1127"]
        ]
        return cmb_gnds

    @classmethod
    @cache
    def _get_cmb_gnd_geo(cls):
        cmb_gnds = cls.get_cmb_gnds()
        geo = gpd.GeoDataFrame(
            pd.concat([gnd.geo() for gnd in cmb_gnds], ignore_index=True)
        )
        geo["gnd"] = cmb_gnds
        return geo

    def get_gnd_id(self) -> str:
        gnd_data_file = self.get_gnd_data_file()
        if gnd_data_file.exists():
            idx = gnd_data_file.read()
            gnd_id = idx.get(self.name)
            if gnd_id is not None:
                return gnd_id

        if self.latlng is None:
            return None

        gnd_id = self._compute_gnd_id()
        return gnd_id

    def _compute_gnd_id(self) -> str:
        point = Point(self.latlng[1], self.latlng[0])
        gnd_geo = self._get_cmb_gnd_geo()
        containing = gnd_geo[gnd_geo.contains(point)]

        for _, row in containing.iterrows():
            gnd = row["gnd"]
            if self._is_within_centroid_distance(gnd):
                return gnd.id

        log.warning(
            f"{self.name} is not inside any Colombo GND within 500m of a "
            "centroid"
        )
        return None

    def _is_within_centroid_distance(self, gnd) -> bool:
        lat_diff = self.latlng[0] - gnd.center_lat
        lng_diff = self.latlng[1] - gnd.center_lng
        return (lat_diff**2 + lng_diff**2) ** 0.5 <= 0.0045

    def get_gnd(self):
        gnd_id = self.get_gnd_id()
        if gnd_id is None:
            return None
        return Ent.from_id(gnd_id)

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
    def save_gnd_map(cls):
        places = cls.list()
        gnd_map = {
            place.name: gnd_id
            for place in places
            if (gnd_id := place.get_gnd_id()) is not None
        }
        gnd_data_file = cls.get_gnd_data_file()
        gnd_data_file.write(gnd_map)
        log.info(f"Saved GND map for {len(gnd_map)} places")

    @classmethod
    def remove_too_far(cls):
        places = cls.list()
        kept = [place for place in places if place.get_gnd_id() is not None]
        removed = [place.name for place in places if place not in kept]

        data_file = cls.get_data_file()
        gnd_data_file = cls.get_gnd_data_file()

        data_file.write(
            {
                place.name: [round(x, cls.PRECISION) for x in place.latlng]
                for place in kept
            }
        )

        if gnd_data_file.exists():
            idx = gnd_data_file.read()
            for name in removed:
                idx.pop(name, None)
            gnd_data_file.write(idx)

        log.info(f"Removed {len(removed)} places that are too far")

    @staticmethod
    def _distance_to_gnd_centroid(place, gnd):
        return (
            (place.latlng[0] - gnd.center_lat) ** 2
            + (place.latlng[1] - gnd.center_lng) ** 2
        ) ** 0.5

    @classmethod
    def _group_places_by_gnd(cls, places):
        gnd_id_to_places = {}
        for place in places:
            gnd_id = place.get_gnd_id()
            if gnd_id is not None:
                gnd_id_to_places.setdefault(gnd_id, []).append(place)
        return gnd_id_to_places

    @classmethod
    def _find_closest_place(cls, group, gnd_id):
        gnd = Ent.from_id(gnd_id)
        closest = group[0]
        min_distance = cls._distance_to_gnd_centroid(closest, gnd)
        for place in group[1:]:
            distance = cls._distance_to_gnd_centroid(place, gnd)
            if distance < min_distance:
                min_distance = distance
                closest = place
        return closest

    @classmethod
    def remove_all_but_closest(cls):
        places = cls.list()
        gnd_id_to_places = cls._group_places_by_gnd(places)

        kept_names = {
            cls._find_closest_place(group, gnd_id).name
            for gnd_id, group in gnd_id_to_places.items()
        }

        kept_places = [place for place in places if place.name in kept_names]
        removed = [
            place.name for place in places if place.name not in kept_names
        ]

        data_file = cls.get_data_file()
        data_file.write(
            {
                place.name: [round(x, cls.PRECISION) for x in place.latlng]
                for place in kept_places
            }
        )

        gnd_data_file = cls.get_gnd_data_file()
        if gnd_data_file.exists():
            idx = gnd_data_file.read()
            for name in removed:
                idx.pop(name, None)
            gnd_data_file.write(idx)

        log.info(
            f"Kept {len(kept_places)} closest places "
            f"({len(removed)} removed from duplicated GNDs)"
        )

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
        cmb_gnds = cls.get_cmb_gnds()
        cmb_gnd_ids = [gnd.id for gnd in cmb_gnds]
        covered_gnd_ids = [
            place.get_gnd().id
            for place in cls.list()
            if place.get_gnd() is not None
        ]
        covered_cmb_gnd_ids = [
            gnd_id for gnd_id in covered_gnd_ids if gnd_id in cmb_gnd_ids
        ]
        n_all = len(cmb_gnd_ids)
        n_covered = len(set(covered_cmb_gnd_ids))
        p_covered = n_covered / n_all
        log.info("-" * 32)
        log.info(f"Total GNDs: {n_all}")
        log.info(f"Covered GNDs: {n_covered}")
        log.info(f"Coverage: {p_covered:.2%}")
        cls.save_gnd_map()

    @classmethod
    def open_uncovered_gnds_in_google_maps(cls, limit=10):
        cmb_gnds = cls.get_cmb_gnds()
        covered_gnd_ids = set(
            place.get_gnd().id
            for place in cls.list()
            if place.latlng is not None and place.get_gnd() is not None
        )
        uncovered_gnds = [
            gnd for gnd in cmb_gnds if gnd.id not in covered_gnd_ids
        ][:limit]

        if not uncovered_gnds:
            log.info("No uncovered GNDs to open")
            return

        log.info(
            f"Opening Google Maps for {len(uncovered_gnds)} uncovered GNDs"
        )
        for gnd in uncovered_gnds:
            url = (
                "https://www.google.com/maps/search/?api=1&query="
                + f"{gnd.center_lat},{gnd.center_lng}"
            )
            webbrowser.open(url, new=2)
