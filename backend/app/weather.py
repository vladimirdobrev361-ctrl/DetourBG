"""Прогноза от Open-Meteo за часа, в който стигаме до всеки обект."""
import time
from datetime import datetime

import httpx

from app import config

HOURLY = "temperature_2m,precipitation_probability,precipitation,weather_code,wind_speed_10m,is_day"
GRID = 0.2          # обектите в една клетка (~20 км) делят една прогноза
CACHE_TTL_S = 900
_cache: dict[tuple[float, float], tuple[float, dict]] = {}


def _cell(lat: float, lon: float) -> tuple[float, float]:
    return round(round(lat / GRID) * GRID, 2), round(round(lon / GRID) * GRID, 2)


def _fetch(cells: list[tuple[float, float]]) -> None:
    missing = [c for c in cells if c not in _cache or time.time() - _cache[c][0] > CACHE_TTL_S]
    if not missing or config.OFFLINE:
        return
    for i in range(0, len(missing), 50):
        chunk = missing[i : i + 50]
        try:
            r = httpx.get(config.OPEN_METEO_URL, params={
                "latitude": ",".join(str(c[0]) for c in chunk),
                "longitude": ",".join(str(c[1]) for c in chunk),
                "hourly": HOURLY, "forecast_days": 3, "timezone": config.TIMEZONE,
            }, timeout=20)
            data = r.json()
            data = data if isinstance(data, list) else [data]
            for cell, d in zip(chunk, data):
                if "hourly" in d:
                    _cache[cell] = (time.time(), d["hourly"])
        except (httpx.HTTPError, ValueError):
            return


def at(points: list[tuple[float, float, datetime]]) -> list[dict | None]:
    """points: [(lat, lon, кога сме там)] → [{temp, rain_prob, precip, code, wind, is_day, time} | None]."""
    cells = [_cell(lat, lon) for lat, lon, _ in points]
    _fetch(sorted(set(cells)))
    out = []
    for cell, (_, _, when) in zip(cells, points):
        hourly = _cache.get(cell, (0, None))[1]
        w = None
        if hourly:
            key = when.strftime("%Y-%m-%dT%H:00")
            if key in hourly["time"]:
                k = hourly["time"].index(key)
                w = {
                    "time": key,
                    "temp": hourly["temperature_2m"][k],
                    "precipitation_probability": hourly["precipitation_probability"][k] or 0,
                    "precipitation": hourly["precipitation"][k] or 0,
                    "weather_code": hourly["weather_code"][k],
                    "wind": hourly["wind_speed_10m"][k],
                    "is_day": bool(hourly["is_day"][k]),
                }
        out.append(w)
    return out


def is_rainy(w: dict | None) -> bool:
    return bool(w) and (w["precipitation_probability"] >= 60 or w["precipitation"] >= 1.0)
