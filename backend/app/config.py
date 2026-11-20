"""Настройки от променливи на средата (виж .env.example)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POIS_PATH = ROOT / "data" / "processed" / "pois.geojson"
FRONTEND_DIR = ROOT / "frontend"


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

OSRM_URL = os.getenv("OSRM_URL", "https://router.project-osrm.org")
TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY", "")
OPEN_METEO_URL = os.getenv("OPEN_METEO_URL", "https://api.open-meteo.com/v1/forecast")
# offline=1 → без външни заявки (маршрут по права линия, без прогноза); за демо без интернет
OFFLINE = os.getenv("OFFLINE", "0") == "1"
USER_AGENT = "fmi-hackathon-trip-detour/0.1 (https://ml-hackathon.pages.dev; student project)"
TIMEZONE = "Europe/Sofia"
