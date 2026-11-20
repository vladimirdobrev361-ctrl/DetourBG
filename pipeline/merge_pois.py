"""Обединява регистъра, OSM и Wikidata в един файл: data/processed/pois.geojson.

Ред на координатите за всеки обект от регистъра:
  1. GPS от текста в „Местоположение“            → coord_quality = "exact"
  2. OSM обект със същото име наблизо             → coord_quality = "osm"
  3. центърът на населеното място (с./гр. …)      → coord_quality = "settlement"
OSM обектите без съответствие в регистъра също влизат (source = ["osm"]).

Употреба: python -m pipeline.merge_pois
"""
import math
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from pipeline.common import PROCESSED, RAW, load_json, save_json
from pipeline.parse_coords import parse_coords

# Колони в регистъра
C_MUNI, C_NAME, C_TYPE, C_OWNER, C_STATUS, C_ACCESS, C_LOC, C_ROAD, C_VIS, C_ENV, C_INFRA = range(11)

# Общини, чийто център се казва различно
MUNICIPALITY_SEATS = {
    "Столична": "София",
    "Родопи": "Пловдив",
    "Марица": "Пловдив",
    "Тунджа": "Ямбол",
    "Добричка": "Добрич",
    "Добрич-селска": "Добрич",
    "Добрич - селска": "Добрич",
}

CATEGORY_RULES = [
    ("religion", ["църкв", "манастир", "параклис", "храм", "джамия", "синагог", "катедрал", "обител", "метох", "черкв"]),
    ("museum", ["музе", "галери", "експозиц", "изложб", "планетариум", "обсерватор", "читалищ", "театър"]),
    ("sport_other", ["спортн", "конна", "конен", "катерен", "картинг", "мотописта", "ски център", "ски писта", "ски зона",
                     "басейн", "аквапарк", "голф", "стрелбищ", "пейнтбол", "рафтинг", "парапланер"]),
    ("hiking", ["екопът", "еко пътека", "туристическа пътека", "пешеходен маршрут", "хижа"]),
    ("cycling", ["велоалея", "велосипед", "веломаршрут"]),
    ("nature", ["природ", "пещер", "водопад", "скал", "езер", "резерват", "местност", "връх", "екопътек", "пътек",
                "гледк", "каньон", "ждрел", "дюн", "плаж", "вековн", "дърв", "извор", "минерал", "защитен", "парк",
                "язовир", "зоопарк"]),
    ("history", ["крепост", "антич", "римск", "тракийск", "могил", "археолог", "руин", "паметник", "мемориал",
                 "истор", "кул", "мост", "гробниц", "светилищ", "архитектур", "етнограф", "възрожд", "култур"]),
]

# Престой по подразбиране (минути)
DEFAULT_STAY = {"museum": 60, "religion": 30, "history": 40, "nature": 60, "other": 40,
                "fitness": 30, "hiking": 120, "cycling": 120, "sport_other": 60}
INDOOR = {"museum", "religion"}

GENERIC_WORDS = {
    "св", "свети", "света", "светите", "църква", "храм", "манастир", "музей", "паметник", "крепост", "пещера",
    "водопад", "местност", "м", "природна", "забележителност", "и", "на", "в", "гр", "с", "град", "село", "антична",
    "късноантична", "историческа", "исторически", "архитектурен", "резерват", "комплекс", "къща", "музейна", "сбирка",
    "център", "градски", "общински", "етнографски", "етнографска", "регионален", "национален", "художествена",
    "галерия", "читалище", "училище", "средновековна", "средновековен", "парк", "паметна", "плоча",
}

# Събития и места за нощувка/хранене не са спирки по пътя
NOT_A_STOP = re.compile(r"фестивал|празни|събор|конкурс|биенале|панаир|карнавал|кукер|хотел|къща за гости|ресторант|механа|кафе", re.I)


def norm(name: str) -> str:
    name = name.lower().replace("ѝ", "й")
    name = re.sub(r"[„“”\"'«»`’()\[\]]", " ", name)
    name = re.sub(r"[^\w\s]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def key_tokens(name: str) -> set[str]:
    return {t for t in norm(name).split() if len(t) >= 3 and t not in GENERIC_WORDS}


def names_match(a: str, b: str) -> bool:
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if SequenceMatcher(None, na, nb).ratio() >= 0.85:
        return True
    ka, kb = key_tokens(a), key_tokens(b)
    return bool(ka) and bool(kb) and (ka <= kb or kb <= ka) and len("".join(ka & kb)) >= 5


def km(lat1, lon1, lat2, lon2) -> float:
    p = math.pi / 180
    a = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2
    return 12742 * math.asin(math.sqrt(a))


def category_from_text(*texts: str) -> str:
    text = " ".join(t for t in texts if t).lower()
    for cat, stems in CATEGORY_RULES:
        if any(s in text for s in stems):
            return cat
    return "other"


def category_from_osm(tags: dict) -> str:
    if tags.get("tourism") in ("museum", "gallery"):
        return "museum"
    if category_from_text(tags.get("name", "")) == "religion":
        return "religion"
    if tags.get("amenity") == "monastery" or tags.get("historic") == "monastery" or tags.get("amenity") == "place_of_worship":
        return "religion"
    if tags.get("natural") in ("cave_entrance", "waterfall") or tags.get("waterway") == "waterfall" or tags.get("tourism") == "viewpoint":
        return "nature"
    if "historic" in tags:
        return "history"
    return category_from_text(tags.get("name", ""))


def is_outdoor(category: str, kind: str) -> bool:
    if category in INDOOR or kind in ("fitness_centre", "sports_centre"):
        return False
    return "пещер" not in kind.lower() and kind != "cave_entrance"


def road_type(text: str) -> str | None:
    t = (text or "").lower()
    if re.search(r"черен|черни|горск|пешеход|пътек|макадам|offroad|джип|без път", t):
        return "unpaved"
    if re.search(r"асфалт|автобус|обществен|градск|шосе", t):
        return "paved"
    return None


def access_info(text: str) -> tuple[bool | None, bool | None]:
    """(безплатно?, сезонно?) от колоната „Достъпност за посещение“."""
    t = (text or "").lower()
    free = True if "безплат" in t else False if re.search(r"платен|такса|лв|билет|вход", t) else None
    seasonal = True if re.search(r"сезон|летен|лято|май|юни|юли|август|септ", t) and "целогод" not in t else (
        False if "целогод" in t else None)
    return free, seasonal


def pretty_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip(" ,.*")
    if name.isupper():
        name = name[:1] + name[1:].lower()
    return name


class Places:
    """Индекс на населените места от OSM по име."""

    def __init__(self, elements: list[dict]):
        self.by_name: dict[str, list[tuple[float, float, str]]] = defaultdict(list)
        for e in elements:
            self.by_name[norm(e["tags"]["name"])].append((e["lat"], e["lon"], e["tags"]["place"]))

    def seat(self, municipality: str) -> tuple[float, float] | None:
        name = MUNICIPALITY_SEATS.get(municipality, municipality)
        cands = self.by_name.get(norm(name), [])
        if not cands:
            return None
        rank = {"city": 0, "town": 1, "village": 2}
        lat, lon, _ = min(cands, key=lambda c: rank.get(c[2], 3))
        return lat, lon

    def locate(self, location_text: str, municipality: str) -> tuple[float, float] | None:
        seat = self.seat(municipality)
        for raw in re.findall(r"(?:^|[\s,(.])(?:гр|с|село|град)\.?\s*([А-Я][^,\d(;:„\"“]+)", location_text or ""):
            words = raw.strip(" .").split()
            # Най-дългото начало, което е име на населено място: „Долна баня“, „Велико Търново“
            for n in range(min(len(words), 4), 0, -1):
                cands = self.by_name.get(norm(" ".join(words[:n])), [])
                if not cands:
                    continue
                if seat:
                    best = min(cands, key=lambda c: km(c[0], c[1], *seat))
                    if km(best[0], best[1], *seat) <= 60:
                        return best[0], best[1]
                elif len(cands) == 1:
                    return cands[0][0], cands[0][1]
        return seat


class OsmIndex:
    """Груба решетка (~11 км) за бързо търсене на OSM обекти наблизо."""

    def __init__(self, pois: list[dict]):
        self.grid: dict[tuple[int, int], list[dict]] = defaultdict(list)
        for p in pois:
            self.grid[(int(p["lat"] * 10), int(p["lon"] * 10))].append(p)

    def near(self, lat: float, lon: float, radius_km: float) -> list[dict]:
        r = math.ceil(radius_km / 8)
        ci, cj = int(lat * 10), int(lon * 10)
        out = []
        for i in range(ci - r, ci + r + 1):
            for j in range(cj - r, cj + r + 1):
                out.extend(p for p in self.grid.get((i, j), []) if km(lat, lon, p["lat"], p["lon"]) <= radius_km)
        return out


def osm_point(e: dict) -> dict | None:
    lat = e.get("lat") or e.get("center", {}).get("lat")
    lon = e.get("lon") or e.get("center", {}).get("lon")
    if lat is None:
        return None
    return {"id": f"osm/{e['type']}/{e['id']}", "lat": lat, "lon": lon, "tags": e.get("tags", {}), "used": False}


def popularity(wd: dict | None, national: bool, sources: list[str], tags: dict) -> float:
    p = 1.0
    if wd:
        p += min(wd.get("sitelinks", 0), 40) / 10
        if wd.get("unesco"):
            p += 2
    if national:
        p += 1
    if tags.get("tourism") in ("attraction", "museum"):
        p += 0.5
    if len(sources) > 1:
        p += 0.3
    return round(p, 2)


def wikidata_props(wd: dict | None) -> dict:
    if not wd:
        return {}
    out = {"sitelinks": wd.get("sitelinks", 0), "unesco": bool(wd.get("unesco"))}
    if wd.get("image"):
        out["image"] = wd["image"].replace("http://", "https://") + "?width=320"
    if wd.get("descBg") or wd.get("descEn"):
        out["description"] = wd.get("descBg") or wd.get("descEn")
    if wd.get("articleBg"):
        out["wikipedia"] = wd["articleBg"]
    return out


def feature(lon: float, lat: float, props: dict) -> dict:
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]}, "properties": props}


def sport_feature(e: dict) -> dict | None:
    """Фитнес, хайкинг, колоездене и други спортове от OSM."""
    p = osm_point(e)
    if not p:
        return None
    t = p["tags"]
    name = t.get("name")
    try:
        length_km = float(str(t.get("distance", "")).replace("km", "").replace(",", ".").strip() or 0)
    except ValueError:
        length_km = 0
    if t.get("leisure") == "fitness_station":
        cat, kind, stay, name = "fitness", "fitness_station", 20, name or "Фитнес на открито"
    elif t.get("leisure") == "fitness_centre":
        cat, kind, stay = "fitness", "fitness_centre", 60
    elif t.get("route") == "hiking":
        cat, kind = "hiking", "hiking_route"
        stay = int(min(240, max(45, length_km / 3.5 * 60))) if length_km else 120
    elif t.get("tourism") in ("alpine_hut", "wilderness_hut"):
        cat, kind, stay = "hiking", t["tourism"], 60
    elif t.get("route") in ("bicycle", "mtb"):
        cat, kind = "cycling", f"{t['route']}_route"
        stay = int(min(180, max(30, length_km / 12 * 60))) if length_km else 120
    elif t.get("amenity") == "bicycle_rental":
        cat, kind, stay, name = "cycling", "bicycle_rental", 90, name or "Колела под наем"
    else:
        cat = "sport_other"
        kind = t.get("leisure") or t.get("sport") or t.get("landuse") or "sport"
        stay = 60
    if not name:
        return None
    return feature(p["lon"], p["lat"], {
        "id": p["id"], "name": name, "category": cat, "kind": kind,
        "outdoor": is_outdoor(cat, kind), "free": (t["fee"] == "no") if t.get("fee") in ("yes", "no") else None,
        "seasonal": None, "road": None, "national": False, "opening_hours": t.get("opening_hours"),
        "stay_min": stay, "length_km": length_km or None, "coord_quality": "exact", "sources": ["osm"],
        "popularity": 1.5 if t.get("wikidata") or t.get("website") else 1.0,
    })


def write_hazards() -> None:
    """Отбелязаните в OSM свлачища и падащи камъни → data/processed/hazards.geojson."""
    path = RAW / "osm_hazards.json"
    feats = []
    for e in load_json(path) if path.exists() else []:
        p = osm_point(e)
        if p:
            feats.append(feature(p["lon"], p["lat"], {"id": p["id"], "hazard": p["tags"].get("hazard"),
                                                       "name": p["tags"].get("name")}))
    save_json(PROCESSED / "hazards.geojson", {"type": "FeatureCollection", "features": feats})
    print(f"  отбелязани опасности (свлачища/камъни): {len(feats)}")


def dedupe(features: list[dict], stats: Counter) -> list[dict]:
    """Едно и също място може да дойде два пъти (регистър + OSM, точка + сграда). Пазим по-богатия запис."""
    def richness(f):
        p = f["properties"]
        return (len(p["sources"]), p["coord_quality"] != "settlement", p["popularity"])
    kept, grid = [], defaultdict(list)
    for f in sorted(features, key=richness, reverse=True):
        lon, lat = f["geometry"]["coordinates"]
        name = f["properties"]["name"]
        cell = (int(lat * 50), int(lon * 50))  # ~2 км
        near = [g for i in (-1, 0, 1) for j in (-1, 0, 1) for g in grid[(cell[0] + i, cell[1] + j)]]
        if any(names_match(name, g["properties"]["name"]) and km(lat, lon, g["geometry"]["coordinates"][1], g["geometry"]["coordinates"][0]) < 1.0 for g in near):
            stats["дубликат"] += 1
            continue
        grid[cell].append(f)
        kept.append(f)
    return kept


def main() -> None:
    registry = load_json(RAW / "registry.json")[1:]
    places = Places(load_json(RAW / "osm_places.json"))
    wikidata = load_json(RAW / "wikidata.json") if (RAW / "wikidata.json").exists() else {}

    osm = [p for p in (osm_point(e) for e in load_json(RAW / "osm_pois.json")) if p]
    # Малките паметни плочи са хиляди; оставяме само известните.
    # Голото tourism=attraction често е животно в зоопарк или атракцион — без Wikidata го пропускаме.
    def notable(t: dict) -> bool:
        if "wikidata" in t:
            return True
        if t.get("historic") in ("memorial", "monument"):
            return "tourism" in t
        if t.get("tourism") == "attraction" and not any(k in t for k in ("historic", "natural", "waterway", "amenity")):
            return any(k in t for k in ("website", "wikipedia", "image", "description"))
        return True
    osm = [p for p in osm if notable(p["tags"])]
    index = OsmIndex(osm)

    features, stats = [], Counter()
    for i, row in enumerate(registry):
        row = (row + [""] * 14)[:14]
        name = pretty_name(row[C_NAME] or "")
        if not name or name == "-":
            stats["без име"] += 1
            continue
        kind = (row[C_TYPE] or "").strip()
        if NOT_A_STOP.search(kind) or NOT_A_STOP.search(name):
            stats["събитие/нощувка/храна"] += 1
            continue
        coords, quality = parse_coords(row[C_LOC]), "exact"
        approx = coords or places.locate(row[C_LOC], row[C_MUNI])
        if not approx:
            stats["без местоположение"] += 1
            continue

        match = None
        radius = 2 if coords else 15
        cands = [p for p in index.near(approx[0], approx[1], radius) if names_match(name, p["tags"].get("name", ""))]
        if cands:
            match = min(cands, key=lambda p: km(approx[0], approx[1], p["lat"], p["lon"]))
            match["used"] = True
        if not coords:
            coords, quality = ((match["lat"], match["lon"]), "osm") if match else (approx, "settlement")
        stats[quality] += 1

        tags = match["tags"] if match else {}
        wd = wikidata.get(tags.get("wikidata", ""))
        category = category_from_text(kind, name)
        if category == "other" and match:
            category = category_from_osm(tags)
        free, seasonal = access_info(row[C_ACCESS])
        if free is None and tags.get("fee") in ("yes", "no"):
            free = tags["fee"] == "no"
        national = "национ" in (row[C_STATUS] or "").lower()
        sources = ["registry"] + (["osm"] if match else []) + (["wikidata"] if wd else [])
        features.append(feature(coords[1], coords[0], {
            "id": f"reg/{i}",
            "name": tags.get("name") or name,
            "category": category,
            "kind": kind,
            "outdoor": is_outdoor(category, kind),
            "free": free,
            "seasonal": seasonal,
            "road": road_type(row[C_ROAD]),
            "municipality": row[C_MUNI],
            "location": (row[C_LOC] or "")[:160],
            "national": national,
            "opening_hours": tags.get("opening_hours"),
            "stay_min": DEFAULT_STAY[category],
            "coord_quality": quality,
            "sources": sources,
            "popularity": popularity(wd, national, sources, tags),
            **wikidata_props(wd),
        }))

    for p in osm:
        if p["used"]:
            continue
        tags = p["tags"]
        wd = wikidata.get(tags.get("wikidata", ""))
        category = category_from_osm(tags)
        kind = tags.get("tourism") or tags.get("historic") or tags.get("natural") or tags.get("amenity") or tags.get("waterway", "")
        sources = ["osm"] + (["wikidata"] if wd else [])
        free = (tags["fee"] == "no") if tags.get("fee") in ("yes", "no") else None
        features.append(feature(p["lon"], p["lat"], {
            "id": p["id"],
            "name": tags["name"],
            "category": category,
            "kind": kind,
            "outdoor": is_outdoor(category, kind),
            "free": free,
            "seasonal": None,
            "road": None,
            "national": False,
            "opening_hours": tags.get("opening_hours"),
            "stay_min": 15 if tags.get("tourism") == "viewpoint" else DEFAULT_STAY[category],
            "coord_quality": "exact",
            "sources": sources,
            "popularity": popularity(wd, False, sources, tags),
            **wikidata_props(wd),
        }))
        stats["само OSM"] += 1

    sport_path = RAW / "osm_sport.json"
    for e in load_json(sport_path) if sport_path.exists() else []:
        f = sport_feature(e)
        if f:
            features.append(f)
            stats["спорт (OSM)"] += 1

    features = dedupe(features, stats)
    write_hazards()
    save_json(PROCESSED / "pois.geojson", {"type": "FeatureCollection", "features": features})
    cats = Counter(f["properties"]["category"] for f in features)
    print(f"Общо {len(features)} обекта")
    print("  координати:", dict(stats))
    print("  категории:", dict(cats))
    print("  с Wikidata:", sum("wikidata" in f["properties"]["sources"] for f in features))


if __name__ == "__main__":
    main()
