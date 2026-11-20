"""Храна и нощувка: обединява OSM (координати, кухня, работно време, сайт) с регистрите на
Министерството на туризма (категория — звезди/еделвайси, брой легла).

→ data/processed/amenities.geojson   заведения (category=food) и места за настаняване (category=lodging)
→ data/processed/places.json         градовете (за надписи „край Севлиево“)

Употреба: python -m pipeline.merge_amenities
"""
import re
from collections import Counter

from pipeline.common import PROCESSED, RAW, load_json, save_json
from pipeline.merge_pois import OsmIndex, Places, feature, km, names_match, osm_point

STARS = {
    "Една звезда": 1, "Две звезди": 2, "Три звезди": 3, "Четири звезди": 4, "Пет звезди": 5,
    "Един еделвайс": 1, "Два еделвайса": 2, "Три еделвайса": 3,
}
KIND_BG = {
    "restaurant": "ресторант", "fast_food": "бързо хранене", "hotel": "хотел", "motel": "мотел",
    "guest_house": "къща за гости", "hostel": "хостел", "chalet": "вила", "camp_site": "къмпинг",
    "apartment": "апартаменти",
}
# от регистъра на заведенията взимаме само местата за хранене (без барове)
FOOD_TYPES = re.compile(r"ресторант|бързо обслужване|столова", re.I)
REG_NAME, REG_MUNI, REG_CITY, REG_ADDR, REG_TYPE, REG_SUBTYPE, REG_CATEGORY = 1, 2, 3, 4, 6, 7, 10


def osm_feature(e: dict, category: str) -> dict | None:
    p = osm_point(e)
    if not p:
        return None
    t = p["tags"]
    kind = t.get("amenity") if category == "food" else t.get("tourism")
    kind_bg = KIND_BG.get(kind, kind)
    if category == "food" and re.search(r"механа|mehana|кръчма|таверна", t["name"], re.I):
        kind_bg = "механа"
    try:
        stars = int(str(t.get("stars", "")).strip()[:1] or 0) or None
    except ValueError:
        stars = None
    p["props"] = {
        "id": p["id"], "name": t["name"], "category": category, "kind": kind, "kind_bg": kind_bg,
        "stars": stars, "category_label": f"{stars} звезди" if stars else None,
        "cuisine": t.get("cuisine"), "opening_hours": t.get("opening_hours"),
        "website": t.get("website") or t.get("contact:website"), "phone": t.get("phone") or t.get("contact:phone"),
        "coord_quality": "exact", "sources": ["osm"],
    }
    return p


def merge(category: str, osm_file: str, registry_file: str, places: Places, stats: Counter) -> list[dict]:
    raw = load_json(RAW / osm_file) if (RAW / osm_file).exists() else []
    osm = [p for p in (osm_feature(e, category) for e in raw) if p]
    index = OsmIndex(osm)
    rows = load_json(RAW / registry_file)
    head, rows = rows[0], rows[1:]
    beds_col = head.index("Опр. брой легла") if "Опр. брой легла" in head else None
    extra = []
    for row in rows:
        name = (row[REG_NAME] or "").strip()
        rtype = row[REG_TYPE] or ""
        if not name or (category == "food" and not FOOD_TYPES.search(rtype)):
            stats[f"{category}: пропуснат"] += 1
            continue
        stars = STARS.get(row[REG_CATEGORY])
        label = (row[REG_CATEGORY] or "").lower() or None
        beds = row[beds_col] if beds_col is not None else None
        where = places.locate(row[REG_CITY], row[REG_MUNI])
        if not where:
            stats[f"{category}: без място"] += 1
            continue
        cands = [p for p in index.near(where[0], where[1], 15) if names_match(name, p["tags"]["name"])]
        if cands:
            m = min(cands, key=lambda p: km(where[0], where[1], p["lat"], p["lon"]))
            m["props"].update(stars=stars or m["props"]["stars"], category_label=label, beds=beds,
                              registry_type=rtype, sources=["osm", "registry"])
            stats[f"{category}: регистър + OSM"] += 1
        else:
            kind_bg = rtype.lower() or KIND_BG.get(category)
            extra.append(feature(where[1], where[0], {
                "id": f"{category}-reg/{row[0]}", "name": name.title() if name.isupper() else name,
                "category": category, "kind": "registry", "kind_bg": kind_bg, "stars": stars,
                "category_label": label, "beds": beds, "registry_type": rtype,
                "address": f"{row[REG_CITY]}, {row[REG_ADDR]}".strip(", "),
                "coord_quality": "settlement", "sources": ["registry"],
            }))
            stats[f"{category}: само регистър"] += 1
    stats[f"{category}: OSM"] += len(osm)
    return [feature(p["lon"], p["lat"], p["props"]) for p in osm] + extra


def main() -> None:
    raw_places = load_json(RAW / "osm_places.json")
    places = Places(raw_places)
    stats: Counter = Counter()
    features = merge("food", "osm_food.json", "food_registry.json", places, stats)
    features += merge("lodging", "osm_lodging.json", "lodging_registry.json", places, stats)
    save_json(PROCESSED / "amenities.geojson", {"type": "FeatureCollection", "features": features})
    towns = [[e["tags"]["name"], round(e["lat"], 5), round(e["lon"], 5)] for e in raw_places
             if e["tags"].get("place") in ("city", "town")]
    save_json(PROCESSED / "places.json", towns)
    print(f"Общо {len(features)}: {dict(stats)}; градове: {len(towns)}")


if __name__ == "__main__":
    main()
