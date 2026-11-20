"""Време за отбивка: от точката на маршрута до обекта и обратно (OSRM /table) + престой."""
from app.corridor import Candidate
from app.routing import Route, table


def compute_detours(cands: list[Candidate], route: Route, stay_override: int | None) -> None:
    if not cands:
        return
    exits = [route.coords[c.route_idx] for c in cands]
    pois = [(c.lon, c.lat) for c in cands]
    there = table(exits, pois)
    back = table(pois, exits)
    for i, c in enumerate(cands):
        t1, t2 = there[i][i], back[i][i]
        # OSRM връща null, ако няма път до точката
        c.detour_s = (t1 if t1 is not None else 3600) + (t2 if t2 is not None else 3600)
        c.stay_min = stay_override if stay_override is not None else c.poi.get("stay_min", 40)
