import os
from dataclasses import dataclass
from typing import List

from utils_future import JSONFile


@dataclass
class Route:
    code: str
    name: str
    stops: List[str]

    @classmethod
    def get_data_file(cls) -> JSONFile:
        return JSONFile(os.path.join("data", "routes.json"))

    @classmethod
    def list(cls) -> list["Route"]:
        return [cls(**route_data) for route_data in cls.get_data_file().read()]
