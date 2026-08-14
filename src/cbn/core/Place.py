from dataclasses import dataclass
from functools import cache

from geopy.geocoders import Nominatim
from gig import Ent, EntType
from utils_future import JSONFile, Log

log = Log("Place")


@dataclass
class Place:
    name: str
    latlng: list[float]

    PRECISION = 6

    @classmethod
    def get_data_file(cls) -> JSONFile:
        return JSONFile("data", "places.json")

    @staticmethod
    def get_cmb_gnds():
        gnds = Ent.list_from_type(EntType.GND)
        cmb_gnds = [
            gnd for gnd in gnds if gnd.dsd_id in ["LK-1103", "LK-1127"]
        ]
        return cmb_gnds

    def get_gnd(self) -> str:
        cmb_gnds = self.get_cmb_gnds()
        min_distance = None
        min_gnd = []
        for gnd in cmb_gnds:
            gnd_latlng = [gnd.center_lat, gnd.center_lng]
            distance = (self.latlng[0] - gnd_latlng[0]) ** 2 + (
                self.latlng[1] - gnd_latlng[1]
            ) ** 2
            if min_distance is None or distance < min_distance:
                min_distance = distance
                min_gnd = gnd
        return min_gnd

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
        cmb_gnds = cls.get_cmb_gnds()
        cmb_gnd_ids = [gnd.id for gnd in cmb_gnds]
        covered_gnd_ids = [place.get_gnd().id for place in cls.list()]
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
