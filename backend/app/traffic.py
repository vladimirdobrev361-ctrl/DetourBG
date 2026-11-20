"""Забавяне от трафика по целия маршрут: TomTom Routing API, ако има TOMTOM_API_KEY, иначе 0."""
import httpx

from app import config


def delay(origin: tuple[float, float], destination: tuple[float, float]) -> dict:
    """origin/destination: (lat, lon) → {source, delay_min, travel_min?}"""
    if not config.TOMTOM_API_KEY or config.OFFLINE:
        return {"source": "none", "delay_min": 0}
    path = f"{origin[0]},{origin[1]}:{destination[0]},{destination[1]}"
    try:
        r = httpx.get(
            f"https://api.tomtom.com/routing/1/calculateRoute/{path}/json",
            params={"key": config.TOMTOM_API_KEY, "traffic": "true", "travelMode": "car", "routeType": "fastest"},
            timeout=15,
        )
        summary = r.json()["routes"][0]["summary"]
        return {"source": "tomtom", "delay_min": round(summary.get("trafficDelayInSeconds", 0) / 60),
                "travel_min": round(summary["travelTimeInSeconds"] / 60)}
    except (httpx.HTTPError, ValueError, KeyError, IndexError):
        return {"source": "error", "delay_min": 0}
