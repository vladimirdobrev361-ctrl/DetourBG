"""Общи пътища и HTTP помощници за pipeline скриптовете."""
import json
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

USER_AGENT = "fmi-hackathon-trip-detour/0.1 (https://ml-hackathon.pages.dev; student project, FMI VTU)"

# Основният сървър често е претоварен, затова пробваме и огледални.
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Приблизителни граници на България (за проверка на координати).
BG_BBOX = (41.2, 22.3, 44.3, 28.7)  # min_lat, min_lon, max_lat, max_lon


def in_bulgaria(lat: float, lon: float) -> bool:
    return BG_BBOX[0] <= lat <= BG_BBOX[2] and BG_BBOX[1] <= lon <= BG_BBOX[3]


def client(timeout: float = 300) -> httpx.Client:
    return httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True)


def overpass(query: str, attempts: int = 3) -> dict:
    """Изпълнява Overpass заявка, като сменя сървъра при грешка."""
    last_error = None
    with client() as http:
        for attempt in range(attempts):
            for url in OVERPASS_ENDPOINTS:
                try:
                    r = http.post(url, data={"data": query})
                    if r.status_code == 200 and r.text.lstrip().startswith("{"):
                        return r.json()
                    last_error = f"{url}: HTTP {r.status_code} {r.text[:80]!r}"
                except httpx.HTTPError as e:
                    last_error = f"{url}: {e}"
                print(f"  ✗ {last_error}")
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"Overpass не отговаря: {last_error}")


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"  → {path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB)")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
