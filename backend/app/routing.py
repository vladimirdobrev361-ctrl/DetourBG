"""Маршрути без трафик през OSRM. При грешка или OFFLINE=1 — права линия с 60 км/ч."""
from dataclasses import dataclass

import httpx

from app import config
from app.geo import haversine_km

FALLBACK_SPEED_KMH = 60
ROAD_FACTOR = 1.3  # пътят е по-дълъг от правата линия


@dataclass
class Route:
    coords: list[tuple[float, float]]  # (lon, lat)
    cum_s: list[float]                 # секунди от началото до всяка точка
    duration_s: float
    distance_m: float
    source: str


def _fallback_route(points: list[tuple[float, float]]) -> Route:
    coords, cum = [points[0]], [0.0]
    for (lon1, lat1), (lon2, lat2) in zip(points, points[1:]):
        steps = 20
        seg_s = haversine_km(lat1, lon1, lat2, lon2) * ROAD_FACTOR / FALLBACK_SPEED_KMH * 3600
        for k in range(1, steps + 1):
            coords.append((lon1 + (lon2 - lon1) * k / steps, lat1 + (lat2 - lat1) * k / steps))
            cum.append(cum[-1] + seg_s / steps)
    dist = sum(haversine_km(a[1], a[0], b[1], b[0]) for a, b in zip(points, points[1:])) * ROAD_FACTOR * 1000
    return Route(coords, cum, cum[-1], dist, "fallback")


def _from_osrm(r: dict) -> Route:
    coords = [tuple(c) for c in r["geometry"]["coordinates"]]
    cum = [0.0]
    for leg in r["legs"]:
        for d in leg["annotation"]["duration"]:
            cum.append(cum[-1] + d)
    # при няколко крака OSRM повтаря точката на свързване
    if len(cum) != len(coords):
        cum = [r["duration"] * k / (len(coords) - 1) for k in range(len(coords))]
    return Route(coords, cum, r["duration"], r["distance"], "osrm")


def routes(points: list[tuple[float, float]], alternatives: int = 0) -> list[Route]:
    """points: [(lon, lat), …]. Връща основния маршрут и до `alternatives` обходни."""
    if not config.OFFLINE:
        path = ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in points)
        params = {"overview": "full", "geometries": "geojson", "annotations": "duration"}
        if alternatives and len(points) == 2:
            params["alternatives"] = str(alternatives)
        try:
            r = httpx.get(f"{config.OSRM_URL}/route/v1/driving/{path}", params=params,
                          headers={"User-Agent": config.USER_AGENT}, timeout=25)
            data = r.json()
            if data.get("code") == "Ok":
                return [_from_osrm(x) for x in data["routes"]]
        except (httpx.HTTPError, ValueError, KeyError):
            pass
    return [_fallback_route(points)]


def route(points: list[tuple[float, float]]) -> Route:
    return routes(points)[0]


def table(sources: list[tuple[float, float]], destinations: list[tuple[float, float]]) -> list[list[float | None]]:
    """Матрица с времена в секунди sources × destinations."""
    if not config.OFFLINE and sources and destinations:
        coords = sources + destinations
        path = ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in coords)
        try:
            r = httpx.get(
                f"{config.OSRM_URL}/table/v1/driving/{path}",
                params={
                    "sources": ";".join(str(i) for i in range(len(sources))),
                    "destinations": ";".join(str(len(sources) + j) for j in range(len(destinations))),
                },
                headers={"User-Agent": config.USER_AGENT}, timeout=25,
            )
            data = r.json()
            if data.get("code") == "Ok":
                return data["durations"]
        except (httpx.HTTPError, ValueError, KeyError):
            pass
    return [
        [haversine_km(s[1], s[0], d[1], d[0]) * ROAD_FACTOR / FALLBACK_SPEED_KMH * 3600 for d in destinations]
        for s in sources
    ]
