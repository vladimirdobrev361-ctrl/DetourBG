"""Геометрия: разстояния и локална проекция в километри (достатъчно точна за България)."""
import math

EARTH_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p = math.pi / 180
    a = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


class LocalProjection:
    """Равнинна проекция около дадена ширина: (lon, lat) → (x, y) в км."""

    def __init__(self, lat0: float):
        self.kx = 111.32 * math.cos(math.radians(lat0))
        self.ky = 110.57

    def xy(self, lon: float, lat: float) -> tuple[float, float]:
        return lon * self.kx, lat * self.ky
