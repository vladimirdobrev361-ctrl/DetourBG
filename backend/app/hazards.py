"""Условия по маршрута:
- ПТП, задръствания, затворени пътища, ремонти — TomTom Traffic Incidents (нужен TOMTOM_API_KEY);
- силен дъжд, силен снеговалеж, поледица, буря, силен вятър, мъгла — Open-Meteo към часа, в който минаваме;
- риск от свлачища и паднали камъни — обилни валежи за 48 ч в планински участък (≥ 400 м)
  + отбелязаните в OpenStreetMap свлачища (hazard=landslide/rockfall);
- официални предупреждения (жълт/оранжев/червен код) — Meteoalarm по области.
"""
import json
import math
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from shapely import LineString, Point

from app import config, regions
from app.corridor import PROJ
from app.routing import Route

SAMPLE_KM = 15
TZ = ZoneInfo(config.TIMEZONE)
DANGER, WARNING, INFO = "danger", "warning", "info"
RANK = {DANGER: 3, WARNING: 2, INFO: 1}
# Опасности, които зависят от конкретния път — само те водят до предложение за обход
ROUTE_SPECIFIC = {"accident", "closure", "flooding", "landslide", "landslide_risk", "heavy_snow", "freezing", "jam"}

_meteo_cache: dict[tuple[float, float], tuple[float, dict]] = {}
_alarm_cache: tuple[float, list[dict]] = (0.0, [])
_osm_hazards: list[dict] | None = None


# ---------- помощни ----------

def samples(route: Route) -> list[dict]:
    """Точки по маршрута през ~15 км: {lat, lon, t_s}."""
    out, acc, last = [], 0.0, None
    for (lon, lat), t in zip(route.coords, route.cum_s):
        if last is not None:
            acc += math.hypot((lon - last[0]) * PROJ.kx, (lat - last[1]) * PROJ.ky)
        if last is None or acc >= SAMPLE_KM:
            out.append({"lat": lat, "lon": lon, "t_s": t})
            acc = 0.0
        last = (lon, lat)
    lon, lat = route.coords[-1]
    out.append({"lat": lat, "lon": lon, "t_s": route.cum_s[-1]})
    return out


def _hazard(kind, severity, title, detail, s: dict, source: str) -> dict:
    return {"type": kind, "severity": severity, "title": title, "detail": detail,
            "lat": s["lat"], "lon": s["lon"], "at_min": round(s["t_s"] / 60), "source": source}


def _merge_segments(items: list[dict]) -> list[dict]:
    """Съседни точки със същата опасност → един участък „от … до …“."""
    out: list[dict] = []
    for h in items:
        prev = out[-1] if out else None
        if prev and prev["type"] == h["type"] and h["at_min"] - prev.get("to_min", prev["at_min"]) <= 30:
            prev["to_min"] = h["at_min"]
            if RANK[h["severity"]] > RANK[prev["severity"]]:
                prev.update(severity=h["severity"], title=h["title"], detail=h["detail"])
        else:
            out.append(dict(h))
    return out


# ---------- времето по пътя ----------

def _meteo(cells: list[tuple[float, float]]) -> None:
    missing = [c for c in cells if c not in _meteo_cache or time.time() - _meteo_cache[c][0] > 900]
    if not missing or config.OFFLINE:
        return
    for i in range(0, len(missing), 50):
        chunk = missing[i : i + 50]
        try:
            r = httpx.get(config.OPEN_METEO_URL, params={
                "latitude": ",".join(str(c[0]) for c in chunk),
                "longitude": ",".join(str(c[1]) for c in chunk),
                "hourly": "precipitation,snowfall,weather_code,wind_gusts_10m,temperature_2m",
                "past_days": 2, "forecast_days": 3, "timezone": config.TIMEZONE,
            }, timeout=20)
            data = r.json()
            for cell, d in zip(chunk, data if isinstance(data, list) else [data]):
                if "hourly" in d:
                    _meteo_cache[cell] = (time.time(), {**d["hourly"], "elevation": d.get("elevation", 0)})
        except (httpx.HTTPError, ValueError):
            return


def _cell(s: dict) -> tuple[float, float]:
    return round(s["lat"] / 0.1) * 0.1, round(s["lon"] / 0.1) * 0.1


def weather_hazards(pts: list[dict], depart: datetime) -> list[dict]:
    out = []
    for s in pts:
        h = _meteo_cache.get(_cell(s), (0, None))[1]
        if not h:
            continue
        key = (depart + timedelta(seconds=s["t_s"])).strftime("%Y-%m-%dT%H:00")
        if key not in h["time"]:
            continue
        k = h["time"].index(key)
        rain, snow = h["precipitation"][k] or 0, h["snowfall"][k] or 0
        code, gust = h["weather_code"][k] or 0, h["wind_gusts_10m"][k] or 0
        rain48 = sum(x or 0 for x in h["precipitation"][max(0, k - 47) : k + 1])
        hour = key[11:16]
        src = "Open-Meteo"
        if snow >= 1.0 or code in (75, 86):
            out.append(_hazard("heavy_snow", DANGER, "Силен снеговалеж", f"{snow:.1f} см/ч около {hour}", s, src))
        elif snow >= 0.3 or code in (71, 73, 85):
            out.append(_hazard("snow", WARNING, "Снеговалеж", f"{snow:.1f} см/ч около {hour}", s, src))
        if code in (56, 57, 66, 67):
            out.append(_hazard("freezing", DANGER, "Поледица", f"замръзващ дъжд около {hour}", s, src))
        if rain >= 7.6 or code in (65, 82):
            out.append(_hazard("heavy_rain", DANGER, "Силен дъжд", f"{rain:.1f} мм/ч около {hour}", s, src))
        elif rain >= 4 or code in (63, 81):
            out.append(_hazard("rain", WARNING, "Дъжд", f"{rain:.1f} мм/ч около {hour}", s, src))
        if code in (95, 96, 99):
            out.append(_hazard("storm", DANGER, "Гръмотевична буря", f"около {hour}", s, src))
        if gust >= 75:
            out.append(_hazard("wind", DANGER, "Много силен вятър", f"пориви до {round(gust)} км/ч около {hour}", s, src))
        elif gust >= 55:
            out.append(_hazard("wind", WARNING, "Силен вятър", f"пориви до {round(gust)} км/ч около {hour}", s, src))
        if code in (45, 48):
            out.append(_hazard("fog", INFO, "Мъгла", f"намалена видимост около {hour}", s, src))
        if h["elevation"] >= 400 and rain48 >= 40:
            sev = DANGER if rain48 >= 70 else WARNING
            out.append(_hazard("landslide_risk", sev, "Риск от свлачища и паднали камъни",
                               f"{round(rain48)} мм валеж за 48 ч, планински участък ({round(h['elevation'])} м)", s, src))
    out.sort(key=lambda x: (x["type"], x["at_min"]))
    return _merge_segments(out)


# ---------- отбелязани свлачища (OSM) ----------

def _load_osm_hazards() -> list[dict]:
    global _osm_hazards
    if _osm_hazards is None:
        path = config.ROOT / "data" / "processed" / "hazards.geojson"
        _osm_hazards = json.loads(path.read_text(encoding="utf-8"))["features"] if path.exists() else []
    return _osm_hazards


def osm_hazards(route: Route, line: LineString) -> list[dict]:
    out = []
    for f in _load_osm_hazards():
        lon, lat = f["geometry"]["coordinates"]
        pt = Point(PROJ.xy(lon, lat))
        if line.distance(pt) <= 0.3:
            idx = min(range(len(route.coords)), key=lambda i: (route.coords[i][0] - lon) ** 2 + (route.coords[i][1] - lat) ** 2)
            s = {"lat": lat, "lon": lon, "t_s": route.cum_s[idx]}
            out.append(_hazard("landslide", WARNING, "Отбелязано свлачище / падащи камъни",
                               f["properties"].get("name") or "участък с риск по OpenStreetMap", s, "OpenStreetMap"))
    return out


# ---------- ПТП и задръствания (TomTom) ----------

TOMTOM_CATEGORY = {
    1: ("accident", DANGER, "ПТП"), 2: ("fog", INFO, "Мъгла"), 3: ("dangerous", WARNING, "Опасни условия"),
    4: ("rain", INFO, "Дъжд"), 5: ("ice", WARNING, "Заледяване"), 6: ("jam", WARNING, "Задръстване"),
    7: ("lane_closed", WARNING, "Затворена лента"), 8: ("closure", DANGER, "Затворен път"),
    9: ("roadworks", WARNING, "Ремонт на пътя"), 10: ("wind", INFO, "Вятър"), 11: ("flooding", DANGER, "Наводнение"),
    14: ("breakdown", WARNING, "Аварирал автомобил"),
}
TOMTOM_FIELDS = ("{incidents{type,geometry{type,coordinates},properties{iconCategory,magnitudeOfDelay,"
                 "events{description},from,to,delay,roadNumbers}}}")


def traffic_incidents(route: Route, line: LineString, pts: list[dict]) -> tuple[list[dict], str]:
    """(инциденти по пътя, откъде са) — без ключ или при грешка списъкът е празен, а статусът казва защо."""
    if not config.TOMTOM_API_KEY or config.OFFLINE:
        return [], "няма ключ за TomTom"
    seen, out = set(), []
    step = max(1, 40 // SAMPLE_KM)  # bbox на ~40 км (TomTom приема до 10 000 км²)
    try:
        for i in range(0, len(pts) - 1, step):
            a, b = pts[i], pts[min(i + step, len(pts) - 1)]
            bbox = (min(a["lon"], b["lon"]) - 0.05, min(a["lat"], b["lat"]) - 0.05,
                    max(a["lon"], b["lon"]) + 0.05, max(a["lat"], b["lat"]) + 0.05)
            r = httpx.get("https://api.tomtom.com/traffic/services/5/incidentDetails", params={
                "key": config.TOMTOM_API_KEY, "bbox": ",".join(f"{v:.5f}" for v in bbox),
                "fields": TOMTOM_FIELDS, "language": "en-GB", "timeValidityFilter": "present",
            }, timeout=15)
            r.raise_for_status()
            for inc in r.json().get("incidents", []):
                geom = inc["geometry"]
                coords = [geom["coordinates"]] if geom["type"] == "Point" else geom["coordinates"]
                lon, lat = coords[0]
                key = (round(lon, 4), round(lat, 4))
                if key in seen:
                    continue
                seen.add(key)
                shape = Point(PROJ.xy(lon, lat)) if len(coords) == 1 else LineString([PROJ.xy(*c) for c in coords])
                if line.distance(shape) > 0.3:
                    continue
                p = inc["properties"]
                kind, sev, title = TOMTOM_CATEGORY.get(p.get("iconCategory"), ("incident", WARNING, "Инцидент"))
                if kind == "jam" and (p.get("magnitudeOfDelay") or 0) >= 3:
                    sev = DANGER
                along = line.project(Point(PROJ.xy(lon, lat))) / max(line.length, 1e-6)
                s = {"lat": lat, "lon": lon, "t_s": along * route.duration_s}
                desc = "; ".join(e.get("description", "") for e in p.get("events") or [])
                where = " – ".join(x for x in (p.get("from"), p.get("to")) if x)
                delay = f", +{round(p['delay'] / 60)} мин" if p.get("delay") else ""
                out.append(_hazard(kind, sev, title, f"{desc}{delay}" + (f" ({where})" if where else ""), s, "TomTom"))
    except (httpx.HTTPError, ValueError, KeyError) as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        return [], f"грешка от TomTom ({status or type(e).__name__}) — проверете ключа"
    return out, "TomTom"


# ---------- официални предупреждения (Meteoalarm) ----------

CAP = "{urn:oasis:names:tc:emergency:cap:1.2}"
ATOM = "{http://www.w3.org/2005/Atom}"
LEVEL_BG = {"Yellow": ("Жълт код", WARNING), "Orange": ("Оранжев код", DANGER), "Red": ("Червен код", DANGER)}
TYPE_BG = {
    "Wind": "силен вятър", "Rain": "интензивни валежи", "Snow-ice": "сняг и поледица", "Snow/Ice": "сняг и поледица",
    "Thunderstorm": "гръмотевични бури", "Fog": "мъгла", "High-temperature": "високи температури",
    "Low-temperature": "ниски температури", "Coastalevent": "явления по крайбрежието", "Forest-fire": "горски пожари",
    "Avalanches": "лавини", "Rain-flood": "наводнения", "Flooding": "наводнения",
}


def _alarms() -> list[dict]:
    global _alarm_cache
    if time.time() - _alarm_cache[0] < 600 or config.OFFLINE:
        return _alarm_cache[1]
    items = []
    try:
        r = httpx.get("https://feeds.meteoalarm.org/feeds/meteoalarm-legacy-atom-bulgaria", timeout=15)
        root = ET.fromstring(r.content)
        for e in root.iter(f"{ATOM}entry"):
            title = e.findtext(f"{ATOM}title") or ""
            parts = title.split(" ")
            level = parts[0] if parts else ""
            kind = parts[1] if len(parts) > 1 else ""
            items.append({
                "nuts": e.findtext(f"{CAP}geocode/{ATOM}value") or e.findtext(f"{CAP}geocode/value"),
                "level": level, "kind": kind,
                "onset": datetime.fromisoformat(e.findtext(f"{CAP}onset")),
                "expires": datetime.fromisoformat(e.findtext(f"{CAP}expires")),
            })
        _alarm_cache = (time.time(), items)
    except (httpx.HTTPError, ET.ParseError, TypeError, ValueError):
        pass
    return _alarm_cache[1]


def official_warnings(pts: list[dict], depart: datetime) -> list[dict]:
    # кога влизаме и кога излизаме от всяка област
    first_seen: dict[str, dict] = {}
    last_seen: dict[str, dict] = {}
    for s in pts:
        code = regions.region_of(s["lat"], s["lon"])
        first_seen.setdefault(code, s)
        last_seen[code] = s
    start = depart.replace(tzinfo=TZ)
    out = []
    for a in _alarms():
        s = first_seen.get(a["nuts"])
        if not s or a["level"] not in LEVEL_BG:
            continue
        enter = start + timedelta(seconds=s["t_s"])
        leave = start + timedelta(seconds=last_seen[a["nuts"]]["t_s"])
        if a["expires"] < enter or a["onset"] > leave:  # няма да сме там, докато важи
            continue
        label, sev = LEVEL_BG[a["level"]]
        until = a["expires"].astimezone(TZ).strftime("%H:%M")
        out.append(_hazard(f"alert_{a['kind'].lower()}", sev, f"{label}: {TYPE_BG.get(a['kind'], a['kind'])}",
                           f"обл. {regions.name(a['nuts'])}, до {until} ч.", s, "Meteoalarm / НИМХ"))
    # една област може да има няколко записа за един и същ код
    uniq = {(h["title"], h["detail"]): h for h in out}
    return sorted(uniq.values(), key=lambda h: h["at_min"])


# ---------- всичко заедно ----------

def check(routes: list[Route], depart: datetime) -> list[dict]:
    """Условията за всеки от маршрутите (основен + обходни)."""
    all_pts = [samples(r) for r in routes]
    _meteo(sorted({_cell(s) for pts in all_pts for s in pts}))
    results = []
    for route, pts in zip(routes, all_pts):
        line = LineString([PROJ.xy(lon, lat) for lon, lat in route.coords])
        incidents, traffic_source = traffic_incidents(route, line, pts)
        hazards = incidents + weather_hazards(pts, depart) + osm_hazards(route, line) + official_warnings(pts, depart)
        hazards.sort(key=lambda h: (-RANK[h["severity"]], h["at_min"]))
        level = max((h["severity"] for h in hazards), key=lambda s: RANK[s], default="ok")
        results.append({
            "level": level,
            "hazards": hazards,
            "checked_at": datetime.now(TZ).strftime("%H:%M"),
            "sources": {
                "traffic": traffic_source,
                "weather": "Open-Meteo" if _meteo_cache else "няма данни",
                "warnings": "Meteoalarm / НИМХ",
                "landslides": f"OpenStreetMap ({len(_load_osm_hazards())} отбелязани) + валежи и височина",
            },
        })
    return results


def route_specific_danger(cond: dict) -> int:
    return sum(1 for h in cond["hazards"] if h["severity"] == DANGER and h["type"] in ROUTE_SPECIFIC)


def recommend(conds: list[dict], routes: list[Route], current: int = 0) -> int | None:
    """Индекс на по-безопасен маршрут, ако текущият има опасност точно по пътя."""
    if len(routes) < 2 or route_specific_danger(conds[current]) == 0:
        return None
    def badness(i):
        c = conds[i]
        return (route_specific_danger(c), sum(1 for h in c["hazards"] if h["severity"] == WARNING), routes[i].duration_s)
    best = min(range(len(routes)), key=badness)
    return best if best != current and badness(best)[0] < badness(current)[0] else None
