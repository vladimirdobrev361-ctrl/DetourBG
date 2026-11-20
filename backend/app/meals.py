"""Храна и нощувка по маршрута.

Обяд (11:30–14:30) и вечеря (18:00–21:00): ако пътуването минава през този час — заведения край пътя
около 12:30 / 19:00, с отбивка + време за хранене. Ако пристигате преди това — заведения в града на пристигане.

Нощувка: при късно пристигане (след 21:30), дълъг път (над 9 ч) или опасност по пътя вечерта —
места край пътя около 19:30 (или преди опасния участък). Иначе — места в града на пристигане.

Данни: OSM + регистрите на Министерството на туризма (категория, звезди/еделвайси, легла).
"""
import json
from datetime import datetime, timedelta

from app import config
from app.corridor import Candidate, PoiStore
from app.detour import compute_detours
from app.geo import haversine_km
from app.routing import Route
from app.scoring import is_open

AMENITIES_PATH = config.ROOT / "data" / "processed" / "amenities.geojson"
PLACES_PATH = config.ROOT / "data" / "processed" / "places.json"

MEALS = [  # ключ, надпис, цел, от, до (минути от полунощ)
    ("lunch", "Обяд", 12 * 60 + 30, 11 * 60 + 30, 14 * 60 + 30),
    ("dinner", "Вечеря", 19 * 60, 18 * 60, 21 * 60),
]
LATE_ARRIVAL = 21 * 60 + 30
OVERNIGHT_TARGET = 19 * 60 + 30
LONG_DRIVE_MIN = 9 * 60
OPTIONS = 5


class Amenities:
    def __init__(self):
        self.store = PoiStore(AMENITIES_PATH) if AMENITIES_PATH.exists() else None
        self.towns = json.loads(PLACES_PATH.read_text(encoding="utf-8")) if PLACES_PATH.exists() else []

    def town_label(self, lat: float, lon: float) -> str:
        best = min(self.towns, key=lambda t: haversine_km(lat, lon, t[1], t[2]), default=None)
        if not best:
            return ""
        d = haversine_km(lat, lon, best[1], best[2])
        return f"в {best[0]}" if d < 4 else f"край {best[0]}" if d < 25 else ""


def _clock(depart: datetime, stops: list[Candidate]):
    """Часът, в който сме в дадена точка от маршрута (с престоя на спирките преди нея)."""
    def at(t_s: float) -> datetime:
        extra = sum(c.extra_min * 60 for c in stops if c.t_along_s < t_s)
        return depart + timedelta(seconds=t_s + extra)
    return at


def _t_for(route: Route, at, when: datetime) -> float:
    for t in route.cum_s:
        if at(t) >= when:
            return t
    return route.duration_s


def _quality(p: dict) -> float:
    q = 1.0 + (p.get("stars") or 0) * 0.2
    if p.get("kind_bg") == "механа":
        q += 0.3
    if p.get("website"):
        q += 0.1
    if p.get("kind") == "fast_food":
        q *= 0.8
    if p.get("coord_quality") == "settlement":
        q *= 0.8
    return q


def _option(c: Candidate, arrive: datetime, near_stop: str | None, extra_reasons=()) -> dict:
    p = c.poi
    reasons = list(extra_reasons)
    if p.get("category_label"):
        reasons.append(p["category_label"])
    if p.get("cuisine"):
        reasons.append(p["cuisine"].replace(";", ", ").replace("_", " "))
    if near_stop:
        reasons.append(f"до спирка {near_stop}")
    warnings = ["приблизително местоположение"] if p.get("coord_quality") == "settlement" else []
    return {
        "id": p["id"], "name": p["name"], "lat": c.lat, "lon": c.lon, "category": p["category"],
        "kind": p.get("kind"), "kind_bg": p.get("kind_bg"), "stars": p.get("stars"), "beds": p.get("beds"),
        "website": p.get("website"), "phone": p.get("phone"), "address": p.get("address"),
        "dist_km": round(c.dist_km, 1), "t_along_min": round(c.t_along_s / 60, 1),
        "detour_min": round(c.detour_s / 60), "stay_min": c.stay_min, "extra_min": round(c.extra_min),
        "arrive": arrive.strftime("%H:%M"), "reasons": reasons, "warnings": warnings,
        "fit": 1.0, "score": round(c.score, 3), "outdoor": False, "image": None, "coord_quality": p.get("coord_quality"),
    }


def _near_stop(c: Candidate, stops: list[Candidate]) -> Candidate | None:
    return next((s for s in stops if haversine_km(c.lat, c.lon, s.lat, s.lon) <= 1.5), None)


def _at_destination(amen: Amenities, route: Route, category: str, radius_km: float) -> list[Candidate]:
    lon, lat = route.coords[-1]
    return [Candidate(poi=p, lat=plat, lon=plon, dist_km=d, route_idx=len(route.coords) - 1, t_along_s=route.duration_s)
            for p, plat, plon, d in amen.store.near(lat, lon, radius_km) if p["category"] == category]


def suggest_meals(amen: Amenities, route: Route, depart: datetime, stops: list[Candidate], meal_min: int = 45) -> list[dict]:
    if not amen.store:
        return []
    at = _clock(depart, stops)
    end = at(route.duration_s)
    day0 = depart.replace(hour=0, minute=0, second=0, microsecond=0)
    corridor = None
    out = []
    for key, label, target, lo, hi in MEALS:
        target_dt, lo_dt, hi_dt = (day0 + timedelta(minutes=m) for m in (target, lo, hi))
        if end < lo_dt or depart > hi_dt:
            continue
        if end < target_dt - timedelta(minutes=20):
            # пристигаме преди обяд/вечеря → заведения в града на пристигане
            cands = _at_destination(amen, route, "food", 3)[:20]
            for c in cands:
                c.stay_min = meal_min
                c.score = _quality(c.poi) / (1 + c.dist_km)
            best = sorted(cands, key=lambda c: c.score, reverse=True)[:OPTIONS]
            lon, lat = route.coords[-1]
            out.append({"key": key, "mode": "destination", "title": f"{label} след пристигане",
                        "where": amen.town_label(lat, lon),
                        "options": [_option(c, max(end, target_dt), None, [f"{c.dist_km:.1f} км от целта"]) for c in best]})
            continue
        t_target = _t_for(route, at, max(target_dt, depart + timedelta(minutes=20)))
        if corridor is None:
            corridor = [c for c in amen.store.in_corridor(route, 5) if c.poi["category"] == "food"]
        cands = [c for c in corridor if abs(c.t_along_s - t_target) <= 40 * 60 and lo_dt <= at(c.t_along_s) <= hi_dt]
        cands = sorted(cands, key=lambda c: _quality(c.poi) / (1 + c.dist_km), reverse=True)[:20]
        compute_detours(cands, route, meal_min)
        options = []
        for c in cands:
            stop = _near_stop(c, stops)
            if stop:
                c.detour_s = 0  # и без това се отбиваме там
            arrive = at(c.t_along_s) + timedelta(seconds=c.detour_s / 2)
            open_now = is_open(c.poi.get("opening_hours"), arrive)
            if open_now is False:
                continue
            c.score = _quality(c.poi) * (1.3 if stop else 1) / (c.extra_min / 60 + 0.3)
            options.append((c, arrive, stop.poi["name"] if stop else None, ["отворено"] if open_now else []))
        options.sort(key=lambda o: o[0].score, reverse=True)
        idx = min(range(len(route.cum_s)), key=lambda i: abs(route.cum_s[i] - t_target))
        lon, lat = route.coords[idx]
        out.append({"key": key, "mode": "route", "title": f"{label} около {at(t_target):%H:%M}",
                    "where": amen.town_label(lat, lon),
                    "options": [_option(*o) for o in options[:OPTIONS]]})
    return out


def suggest_overnight(amen: Amenities, route: Route, depart: datetime, stops: list[Candidate], conditions: dict) -> dict | None:
    if not amen.store:
        return None
    at = _clock(depart, stops)
    end = at(route.duration_s)
    day0 = depart.replace(hour=0, minute=0, second=0, microsecond=0)
    evening = day0 + timedelta(minutes=18 * 60)
    reasons = []
    target = day0 + timedelta(minutes=OVERNIGHT_TARGET)
    if end > day0 + timedelta(minutes=LATE_ARRIVAL):
        reasons.append(f"пристигане чак в {end:%H:%M}")
    if (end - depart).total_seconds() / 60 > LONG_DRIVE_MIN:
        reasons.append("над 9 ч път")
    for h in conditions.get("hazards", []):
        when = at(h["at_min"] * 60)
        if h["severity"] == "danger" and when >= evening:
            reasons.append(f"{h['title'].lower()} по пътя вечерта")
            target = min(target, when - timedelta(minutes=30))
            break

    if not reasons:
        cands = _at_destination(amen, route, "lodging", 6)[:40]
        for c in cands:
            # „в центъра на града“ от регистъра не е истинско разстояние — точните адреси първо
            exact = 1.0 if c.poi.get("coord_quality") == "exact" else 0.6
            c.score = exact * _quality(c.poi) / (1 + c.dist_km / 3)
        best = sorted(cands, key=lambda c: c.score, reverse=True)[:OPTIONS]
        lon, lat = route.coords[-1]
        return {"mode": "destination", "title": "Нощувка в края на пътя", "where": amen.town_label(lat, lon),
                "reason": None, "options": [_option(c, end, None, [f"{c.dist_km:.1f} км от целта"]) for c in best]}

    t_target = min(max(_t_for(route, at, target), 30 * 60), route.duration_s - 30 * 60)
    cands = [c for c in amen.store.in_corridor(route, 10)
             if c.poi["category"] == "lodging" and abs(c.t_along_s - t_target) <= 45 * 60]
    cands = sorted(cands, key=lambda c: _quality(c.poi) / (1 + c.dist_km), reverse=True)[:20]
    compute_detours(cands, route, 0)
    for c in cands:
        c.detour_s /= 2  # отиваме, но не се връщаме днес
        c.score = _quality(c.poi) / (c.extra_min / 60 + 0.3)
    best = sorted(cands, key=lambda c: c.score, reverse=True)[:OPTIONS]
    idx = min(range(len(route.cum_s)), key=lambda i: abs(route.cum_s[i] - t_target))
    lon, lat = route.coords[idx]
    return {"mode": "route", "title": f"Нощувка по пътя около {at(t_target):%H:%M}", "where": amen.town_label(lat, lon),
            "reason": ", ".join(reasons),
            "options": [_option(c, at(c.t_along_s) + timedelta(seconds=c.detour_s), None) for c in best]}
