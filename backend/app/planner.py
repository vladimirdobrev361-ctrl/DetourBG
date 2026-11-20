"""Целият план: маршрути → условия по пътя → коридор → отбивки → време → оценка → избор на спирки в бюджета."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlencode

from app import hazards, meals, routing, traffic, weather
from app.corridor import Candidate, PoiStore
from app.detour import compute_detours
from app.routing import Route
from app.scoring import interest_weight, score

MAX_CANDIDATES = 40   # колко обекта минават през OSRM /table
MAX_STOPS = 6
MIN_SCORE = 0.5
ENDPOINT_MIN = 15     # обектите в града на тръгване/пристигане не са „отбивки по пътя“
ALTERNATIVES = 2


@dataclass
class PlanRequest:
    origin: tuple[float, float]        # (lat, lon)
    destination: tuple[float, float]
    depart: datetime
    budget_min: float
    interests: list[str]
    corridor_km: float = 8.0
    stay_override_min: int | None = None
    exclude: tuple[str, ...] = ()
    sticky: tuple[str, ...] = ()      # спирки, които вече са приети — по-трудно отпадат
    from_start: bool = True           # False при преизчисляване по пътя (началото е текущата позиция)
    route_choice: int = 0             # 0 = най-бързият, 1–2 = обходните на OSRM
    meal_min: int = 45                # колко време за обяд/вечеря


def prefilter(cands: list[Candidate], interests: list[str], exclude: set[str], keep: set[str]) -> list[Candidate]:
    """Преди скъпите заявки: близки, популярни и по интересите. Приетите спирки (`keep`) остават винаги."""
    def rough(c: Candidate) -> float:
        return interest_weight(c.poi["category"], interests) * c.poi.get("popularity", 1) / (1 + c.dist_km)
    cands = [c for c in cands if c.id not in exclude]
    kept = [c for c in cands if c.id in keep]
    rest = sorted((c for c in cands if c.id not in keep), key=rough, reverse=True)
    return kept + rest[: max(0, MAX_CANDIDATES - len(kept))]


def select(cands: list[Candidate], budget_min: float) -> list[Candidate]:
    """Алчен избор по оценка, докато се събира в бюджета от време."""
    chosen, used = [], 0.0
    for c in sorted(cands, key=lambda c: c.score, reverse=True):
        if len(chosen) >= MAX_STOPS or c.score < MIN_SCORE:
            break
        if used + c.extra_min <= budget_min:
            chosen.append(c)
            used += c.extra_min
    return sorted(chosen, key=lambda c: c.t_along_s)


def links(origin, destination, stops: list[Candidate]) -> dict:
    params = {"api": 1, "origin": f"{origin[0]},{origin[1]}", "destination": f"{destination[0]},{destination[1]}",
              "travelmode": "driving"}
    if stops:
        params["waypoints"] = "|".join(f"{c.lat:.6f},{c.lon:.6f}" for c in stops)
    first = stops[0] if stops else None
    waze_target = (first.lat, first.lon) if first else destination
    return {
        "google": "https://www.google.com/maps/dir/?" + urlencode(params, safe=",|"),
        "waze": f"https://waze.com/ul?ll={waze_target[0]:.6f},{waze_target[1]:.6f}&navigate=yes",
    }


def candidate_json(c: Candidate) -> dict:
    p = c.poi
    return {
        "id": c.id, "name": p["name"], "lat": c.lat, "lon": c.lon,
        "category": p["category"], "kind": p.get("kind"), "outdoor": p["outdoor"], "length_km": p.get("length_km"),
        "image": p.get("image"), "description": p.get("description"), "wikipedia": p.get("wikipedia"),
        "coord_quality": p.get("coord_quality"), "sources": p.get("sources"),
        "dist_km": round(c.dist_km, 1), "t_along_min": round(c.t_along_s / 60, 1),
        "detour_min": round(c.detour_s / 60), "stay_min": c.stay_min, "extra_min": round(c.extra_min),
        "weather": c.weather, "fit": c.fit, "score": c.score, "reasons": c.reasons, "warnings": c.warnings,
    }


def downsample(route: Route, max_points: int) -> list[int]:
    step = max(1, len(route.coords) // max_points)
    idx = list(range(0, len(route.coords), step))
    if idx[-1] != len(route.coords) - 1:
        idx.append(len(route.coords) - 1)
    return idx


def alternative_json(i: int, r: Route, cond: dict, fastest: Route) -> dict:
    idx = downsample(r, 300)
    return {
        "index": i,
        "coords": [[r.coords[k][1], r.coords[k][0]] for k in idx],
        "duration_min": round(r.duration_s / 60), "distance_km": round(r.distance_m / 1000),
        "extra_min": round((r.duration_s - fastest.duration_s) / 60),
        "level": cond["level"],
        "danger": sum(1 for h in cond["hazards"] if h["severity"] == "danger"),
        "warnings": sum(1 for h in cond["hazards"] if h["severity"] == "warning"),
    }


def plan(store: PoiStore, req: PlanRequest, amenities: meals.Amenities | None = None) -> dict:
    all_routes = routing.routes(
        [(req.origin[1], req.origin[0]), (req.destination[1], req.destination[0])], alternatives=ALTERNATIVES
    )
    choice = min(max(req.route_choice, 0), len(all_routes) - 1)
    conds = hazards.check(all_routes, req.depart)
    recommended = hazards.recommend(conds, all_routes, choice)
    base = all_routes[choice]

    in_corridor = store.in_corridor(base, req.corridor_km)
    edge_s = min(ENDPOINT_MIN * 60, base.duration_s * 0.15)
    if req.from_start:
        in_corridor = [c for c in in_corridor if c.t_along_s >= edge_s]
    in_corridor = [c for c in in_corridor if c.t_along_s <= base.duration_s - edge_s]
    cands = prefilter(in_corridor, req.interests, set(req.exclude), set(req.sticky))
    compute_detours(cands, base, req.stay_override_min)
    forecast = weather.at([(c.lat, c.lon, req.depart + timedelta(seconds=c.t_along_s)) for c in cands])
    for c, w in zip(cands, forecast):
        c.weather = w
        score(c, req.interests, req.depart, sticky=c.id in req.sticky)

    jam = traffic.delay(req.origin, req.destination)
    # задръстването изяжда от бюджета за спирки
    stops = select(cands, req.budget_min - jam["delay_min"])
    base_min = base.duration_s / 60
    extra = sum(c.extra_min for c in stops)

    food = meals.suggest_meals(amenities, base, req.depart, stops, req.meal_min) if amenities else []
    lodging = meals.suggest_overnight(amenities, base, req.depart, stops, conds[choice]) if amenities else None

    idx = downsample(base, 1500)
    return {
        "route": {
            "coords": [[base.coords[i][1], base.coords[i][0]] for i in idx],
            "cum_min": [round(base.cum_s[i] / 60, 2) for i in idx],
            "duration_min": round(base_min), "distance_km": round(base.distance_m / 1000), "source": base.source,
        },
        "route_choice": choice,
        "recommended_route": recommended,
        "alternatives": [alternative_json(i, r, conds[i], all_routes[0]) for i, r in enumerate(all_routes)],
        "conditions": conds[choice],
        "depart": req.depart.isoformat(timespec="minutes"),
        "arrival_direct": (req.depart + timedelta(minutes=base_min + jam["delay_min"])).isoformat(timespec="minutes"),
        "arrival_planned": (req.depart + timedelta(minutes=base_min + jam["delay_min"] + extra)).isoformat(timespec="minutes"),
        "traffic": jam,
        "weather_source": "open-meteo" if any(forecast) else "none",
        "corridor_count": len(in_corridor),
        "candidates": [candidate_json(c) for c in sorted(cands, key=lambda c: c.score, reverse=True)],
        "stops": [c.id for c in stops],
        "extra_min": round(extra),
        "links": links(req.origin, req.destination, stops),
        "food": food,
        "lodging": lodging,
    }
