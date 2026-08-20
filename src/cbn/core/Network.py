import os
from dataclasses import dataclass, field
from heapq import heappop, heappush
from math import asin, cos, inf, isclose, radians, sin, sqrt
from typing import List

import geopandas as gpd
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D
from shapely.geometry import LineString, Point
from utils_future import File, Log

from cbn.core.Place import Place
from cbn.core.Route import Route

log = Log("Network")


@dataclass
class Network:
    routes: List[Route] = field(default_factory=Route.list)
    stops: List[Place] = field(default_factory=Place.list)

    ROUTE_SPEED_KMPH = 25
    WALKING_SPEED_KMPH = 5
    EARTH_RADIUS_KM = 6371.0088

    @classmethod
    def _distance_km(cls, start: Place, end: Place) -> float:
        start_lat, start_lng = map(radians, start.latlng)
        end_lat, end_lng = map(radians, end.latlng)
        lat_diff = end_lat - start_lat
        lng_diff = end_lng - start_lng
        haversine = (
            sin(lat_diff / 2) ** 2
            + cos(start_lat) * cos(end_lat) * sin(lng_diff / 2) ** 2
        )
        return 2 * cls.EARTH_RADIUS_KM * asin(sqrt(haversine))

    def _get_stop(self, stop: Place | str) -> Place:
        stop_name = stop.name if isinstance(stop, Place) else stop
        for candidate in self.stops:
            if candidate.name == stop_name:
                return candidate
        raise ValueError(f"Unknown stop: {stop_name}")

    def _get_graph(self):
        name_to_stop = {stop.name: stop for stop in self.stops}
        graph = {stop.name: {} for stop in self.stops}
        for route in self.routes:
            for start_name, end_name in zip(route.stops, route.stops[1:]):
                start = name_to_stop[start_name]
                end = name_to_stop[end_name]
                distance = self._distance_km(start, end)
                current = graph[start_name].get(end_name, inf)
                graph[start_name][end_name] = min(current, distance)
                graph[end_name][start_name] = min(current, distance)
        return graph

    @staticmethod
    def _get_shortest_distances(start_name, graph):
        distances = {start_name: 0.0}
        queue = [(0.0, start_name)]
        while queue:
            distance, stop_name = heappop(queue)
            if distance > distances[stop_name]:
                continue
            for neighbour, edge_distance in graph[stop_name].items():
                new_distance = distance + edge_distance
                if new_distance < distances.get(neighbour, inf):
                    distances[neighbour] = new_distance
                    heappush(queue, (new_distance, neighbour))
        return distances

    def get_travel_time(self, start: Place | str, end: Place | str) -> float:
        start_stop = self._get_stop(start)
        end_stop = self._get_stop(end)
        graph = self._get_graph()
        route_distances = self._get_shortest_distances(start_stop.name, graph)
        if end_stop.name in route_distances:
            distance = route_distances[end_stop.name]
            speed = self.ROUTE_SPEED_KMPH
        else:
            distance = self._distance_km(start_stop, end_stop)
            speed = self.WALKING_SPEED_KMPH
        return distance / speed * 60

    def Analyse(self):
        graph = self._get_graph()
        averages = {}
        for start in self.stops:
            route_distances = self._get_shortest_distances(start.name, graph)
            travel_times = [
                (
                    route_distances[end.name] / self.ROUTE_SPEED_KMPH * 60
                    if end.name in route_distances
                    else self._distance_km(start, end)
                    / self.WALKING_SPEED_KMPH
                    * 60
                )
                for end in self.stops
                if end.name != start.name
            ]
            averages[start.name] = sum(travel_times) / len(travel_times)

        ranked_averages = dict(
            sorted(averages.items(), key=lambda item: (item[1], item[0]))
        )
        for rank, (stop_name, average) in enumerate(
            ranked_averages.items(), start=1
        ):
            print(f"{rank}. {stop_name}: {average:.2f} minutes")
        global_average = sum(ranked_averages.values()) / len(ranked_averages)
        print(f"Global average: {global_average:.2f} minutes")
        return ranked_averages

    @staticmethod
    def _get_octilinear_segment(start, end):
        x1, y1 = start
        x2, y2 = end
        dx = x2 - x1
        dy = y2 - y1
        abs_dx = abs(dx)
        abs_dy = abs(dy)

        if isclose(dx, 0) or isclose(dy, 0) or isclose(abs_dx, abs_dy):
            return [end]

        if abs_dx > abs_dy:
            diagonal_dx = abs_dy if dx > 0 else -abs_dy
            outer_dx = (dx - diagonal_dx) / 2
            return [
                (x1 + outer_dx, y1),
                (x1 + outer_dx + diagonal_dx, y2),
                end,
            ]

        diagonal_dy = abs_dx if dy > 0 else -abs_dx
        outer_dy = (dy - diagonal_dy) / 2
        return [
            (x1, y1 + outer_dy),
            (x2, y1 + outer_dy + diagonal_dy),
            end,
        ]

    @classmethod
    def _get_octilinear_path(cls, coordinates):
        path = [coordinates[0]]
        for start, end in zip(coordinates, coordinates[1:]):
            path.extend(cls._get_octilinear_segment(start, end))
        return path

    def _get_route_geo(self) -> gpd.GeoDataFrame:
        name_to_stop = {stop.name: stop for stop in self.stops}
        return gpd.GeoDataFrame(
            {
                "code": [route.code for route in self.routes],
                "name": [route.name for route in self.routes],
                "stops": [route.stops for route in self.routes],
                "geometry": [
                    LineString(
                        self._get_octilinear_path(
                            [
                                (
                                    name_to_stop[name].latlng[1],
                                    name_to_stop[name].latlng[0],
                                )
                                for name in route.stops
                            ]
                        )
                    )
                    for route in self.routes
                ],
            },
            crs="EPSG:4326",
        )

    def _get_gnd_geo(self):
        cmb_gnds = Place.get_cmb_gnds()
        stop_gnd_ids = [
            stop.get_gnd().id
            for stop in self.stops
            if stop.latlng is not None and stop.get_gnd() is not None
        ]
        rows = []
        for gnd in cmb_gnds:
            gnd_geo = gnd.geo()
            gnd_geo["n_places"] = stop_gnd_ids.count(gnd.id)
            rows.append(gnd_geo)
        return gpd.GeoDataFrame(pd.concat(rows, ignore_index=True))

    def _get_stop_geo(self):
        stops = [
            stop
            for stop in self.stops
            if stop.latlng is not None and stop.get_gnd() is not None
        ]
        return gpd.GeoDataFrame(
            {
                "name": [stop.name for stop in stops],
                "geometry": [
                    Point(stop.latlng[1], stop.latlng[0]) for stop in stops
                ],
            },
            crs="EPSG:4326",
        )

    @staticmethod
    def _hue_to_rgb(hue):
        chroma = 1 - abs(2 * 0.85 - 1)
        x = chroma * (1 - abs((hue / 60) % 2 - 1))
        m = 0.85 - chroma / 2

        if hue < 60:
            red, green, blue = chroma, x, 0
        elif hue < 120:
            red, green, blue = x, chroma, 0
        elif hue < 180:
            red, green, blue = 0, chroma, x
        elif hue < 240:
            red, green, blue = 0, x, chroma
        else:
            red, green, blue = x, 0, chroma

        return (
            int((red + m) * 255),
            int((green + m) * 255),
            int((blue + m) * 255),
        )

    @staticmethod
    def _color_for_n(n, max_n):
        hue = 0 if max_n == 0 else 240 * (n / max_n)
        return Network._hue_to_rgb(hue)

    @staticmethod
    def _plot_gnds(ax, gnd_geo):
        max_n = gnd_geo["n_places"].max()
        for _, row in gnd_geo.iterrows():
            n = row["n_places"]
            color = Network._color_for_n(n, max_n)
            gpd.GeoDataFrame([row]).plot(
                ax=ax,
                color=f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}",
                edgecolor="gray",
                alpha=0.7,
                linewidth=0.5,
            )
        return max_n

    @staticmethod
    def _get_route_memberships(route_geo):
        route_memberships = {}
        for route_index, (_, route) in enumerate(route_geo.iterrows()):
            for stop in route["stops"]:
                route_memberships.setdefault(stop, set()).add(route_index)
        return route_memberships

    @staticmethod
    def _plot_stop_markers(ax, stop_geo, names, **style):
        stops = stop_geo[stop_geo["name"].isin(names)]
        if not stops.empty:
            stops.plot(ax=ax, **style)

    @staticmethod
    def _plot_non_route_stops(ax, stop_geo, route_memberships):
        unused_names = set(stop_geo["name"]) - set(route_memberships)
        Network._plot_stop_markers(
            ax,
            stop_geo,
            unused_names,
            color="black",
            markersize=50,
            edgecolor="black",
            linewidth=0.5,
        )

    @staticmethod
    def _plot_non_junctions(ax, stop_geo, route_geo, route_memberships):
        colors = plt.get_cmap("tab10").colors
        for route_index in range(len(route_geo)):
            stop_names = {
                name
                for name, memberships in route_memberships.items()
                if memberships == {route_index}
            }
            route_color = colors[route_index % len(colors)]
            Network._plot_stop_markers(
                ax,
                stop_geo,
                stop_names,
                color=route_color,
                markersize=50,
                edgecolor=route_color,
                linewidth=0.5,
            )

    @staticmethod
    def _plot_junctions(ax, stop_geo, route_memberships):
        junction_names = {
            name
            for name, memberships in route_memberships.items()
            if len(memberships) > 1
        }
        Network._plot_stop_markers(
            ax,
            stop_geo,
            junction_names,
            color="white",
            markersize=100,
            edgecolor="black",
            linewidth=1.5,
            zorder=4,
        )

    @staticmethod
    def _annotate_stops(ax, stop_geo):
        for _, row in stop_geo.iterrows():
            ax.annotate(
                row["name"],
                (row.geometry.x, row.geometry.y),
                xytext=(5, 5),
                textcoords="offset points",
                fontsize=7,
                color="black",
            )

    @staticmethod
    def _plot_stops(ax, stop_geo, route_geo):
        route_memberships = Network._get_route_memberships(route_geo)
        Network._plot_non_route_stops(ax, stop_geo, route_memberships)
        Network._plot_non_junctions(ax, stop_geo, route_geo, route_memberships)
        Network._plot_junctions(ax, stop_geo, route_memberships)
        Network._annotate_stops(ax, stop_geo)

    @staticmethod
    def _plot_routes(ax, route_geo):
        colors = plt.get_cmap("tab10").colors
        for route_index, (_, route) in enumerate(route_geo.iterrows()):
            x, y = route.geometry.xy
            ax.plot(
                x,
                y,
                color=colors[route_index % len(colors)],
                linewidth=4,
                alpha=0.85,
                solid_joinstyle="round",
                solid_capstyle="round",
            )

    @staticmethod
    def _add_legend(ax, gnd_geo, route_geo, max_n):
        unique_ns = sorted(gnd_geo["n_places"].unique())
        legend_patches = [
            mpatches.Patch(
                color=f"#{'%02x%02x%02x' % Network._color_for_n(n, max_n)}",
                label=f"{n} place{'s' if n != 1 else ''}",
            )
            for n in unique_ns
        ]
        colors = plt.get_cmap("tab10").colors
        route_lines = [
            Line2D(
                [0],
                [0],
                color=colors[route_index % len(colors)],
                linewidth=4,
                label=f'{route["code"]}: {route["name"]}',
            )
            for route_index, (_, route) in enumerate(route_geo.iterrows())
        ]
        ax.legend(
            handles=legend_patches + route_lines,
            title="Places and Routes",
            loc="upper left",
        )

    @staticmethod
    def _render_plot(gnd_geo, stop_geo, route_geo, image_path):
        fig, ax = plt.subplots(figsize=(24, 24))
        max_n = Network._plot_gnds(ax, gnd_geo)
        Network._plot_routes(ax, route_geo)
        Network._plot_stops(ax, stop_geo, route_geo)
        Network._add_legend(ax, gnd_geo, route_geo, max_n)
        ax.set_title("Bus Routes, Places, and GND Boundaries in Colombo")
        ax.set_aspect("equal")
        ax.axis("off")
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        plt.savefig(image_path, dpi=300, bbox_inches="tight")
        log.info(f"Wrote {File(image_path)}")
        plt.close(fig)

    def plot(self):
        gnd_geo = self._get_gnd_geo()
        stop_geo = self._get_stop_geo()
        route_geo = self._get_route_geo()
        image_path = os.path.join("images", "places.png")
        self._render_plot(gnd_geo, stop_geo, route_geo, image_path)
