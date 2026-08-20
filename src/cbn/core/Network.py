import os
from dataclasses import dataclass, field
from heapq import heappop, heappush
from math import asin, cos, inf, isclose, radians, sin, sqrt
from typing import List

import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import MultipleLocator
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

    def _get_stop_geo(self):
        stops = [stop for stop in self.stops if stop.latlng is not None]
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
    def _add_route_legend(ax, route_geo):
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
            handles=route_lines,
            title="Routes",
            loc="upper left",
        )

    @staticmethod
    def _add_grid(ax):
        grid_color = "#dddddd"
        ax.xaxis.set_major_locator(MultipleLocator(Place.GRID_LONGITUDE))
        ax.yaxis.set_major_locator(MultipleLocator(Place.GRID_LATITUDE))
        ax.grid(color=grid_color, linewidth=0.6)
        ax.tick_params(colors=grid_color, labelsize=7, length=0)
        for spine in ax.spines.values():
            spine.set_visible(False)

    @staticmethod
    def _render_plot(stop_geo, route_geo, image_path, include_routes):
        fig, ax = plt.subplots(figsize=(24, 24))
        if include_routes:
            Network._plot_routes(ax, route_geo)
        Network._plot_stops(ax, stop_geo, route_geo)
        if include_routes:
            Network._add_route_legend(ax, route_geo)
        title = (
            "Bus Routes and Stops in Colombo"
            if include_routes
            else "Stops in Colombo"
        )
        ax.set_title(title)
        ax.set_aspect("equal")
        Network._add_grid(ax)
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        plt.savefig(image_path, dpi=300, bbox_inches="tight")
        log.info(f"Wrote {File(image_path)}")
        plt.close(fig)

    def plot(self, include_routes=True):
        stop_geo = self._get_stop_geo()
        route_geo = self._get_route_geo()
        image_name = "places.png" if include_routes else "stops.png"
        image_path = os.path.join("images", image_name)
        self._render_plot(stop_geo, route_geo, image_path, include_routes)
