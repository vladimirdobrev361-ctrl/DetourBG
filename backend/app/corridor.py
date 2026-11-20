"""Зарежда pois.geojson и намира обектите в коридор около маршрута."""
import json
from dataclasses import dataclass, field

import numpy as np
from shapely import LineString, Point, STRtree

from app import config
from app.geo import LocalProjection
from app.routing import Route

PROJ = LocalProjection(42.7)  # средата на България


@dataclass
class Candidate:
    poi: dict                 # properties от GeoJSON
    lat: float
    lon: float
    dist_km: float            # разстояние по права до маршрута
    route_idx: int            # най-близката точка от маршрута (тук е отбивката)
    t_along_s: float          # кога стигаме отбивката, секунди от тръгването
    detour_s: float = 0.0     # отиване + връщане, без престоя
    stay_min: int = 0
    weather: dict | None = None
    fit: float = 1.0
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    score: float = 0.0

    @property
    def id(self) -> str:
        return self.poi["id"]

    @property
    def extra_min(self) -> float:
        return self.detour_s / 60 + self.stay_min


class PoiStore:
    def __init__(self, path=config.POIS_PATH):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.features = data["features"]
        self.by_id = {f["properties"]["id"]: f for f in self.features}
        self.points = [Point(PROJ.xy(*f["geometry"]["coordinates"])) for f in self.features]
        self.tree = STRtree(self.points)

    def near(self, lat: float, lon: float, radius_km: float) -> list[tuple[dict, float, float, float]]:
        """Обектите до radius_km от точката: [(properties, lat, lon, км)]."""
        pt = Point(PROJ.xy(lon, lat))
        out = []
        for i in self.tree.query(pt, predicate="dwithin", distance=radius_km):
            f = self.features[i]
            flon, flat = f["geometry"]["coordinates"]
            out.append((f["properties"], flat, flon, float(pt.distance(self.points[i]))))
        return sorted(out, key=lambda x: x[3])

    def in_corridor(self, route: Route, corridor_km: float) -> list[Candidate]:
        xy = [PROJ.xy(lon, lat) for lon, lat in route.coords]
        line = LineString(xy)
        # дължина по маршрута до всеки връх → за да намерим най-близкия връх
        seg = np.hypot(*np.diff(np.array(xy), axis=0).T)
        cum_km = np.concatenate([[0], np.cumsum(seg)])
        out = []
        for i in self.tree.query(line, predicate="dwithin", distance=corridor_km):
            f, pt = self.features[i], self.points[i]
            along = line.project(pt)
            idx = int(min(np.searchsorted(cum_km, along), len(route.coords) - 1))
            lon, lat = f["geometry"]["coordinates"]
            out.append(Candidate(
                poi=f["properties"], lat=lat, lon=lon, dist_km=float(line.distance(pt)),
                route_idx=idx, t_along_s=route.cum_s[idx],
            ))
        return out
