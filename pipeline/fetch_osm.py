"""Сваля от OpenStreetMap туристическите обекти и населените места в България.

Употреба: python -m pipeline.fetch_osm [--force]
"""
import sys

from pipeline.common import RAW, load_json, overpass, save_json

AREA = 'area["ISO3166-1"="BG"][admin_level=2]->.bg;'

POIS_QUERY = f"""
[out:json][timeout:300];
{AREA}
(
  nwr["tourism"~"^(attraction|museum|viewpoint|zoo|theme_park|gallery)$"]["name"](area.bg);
  nwr["historic"~"^(castle|monastery|archaeological_site|ruins|fort|memorial|monument)$"]["name"](area.bg);
  nwr["amenity"="monastery"]["name"](area.bg);
  nwr["natural"~"^(cave_entrance|waterfall)$"]["name"](area.bg);
  nwr["waterway"="waterfall"]["name"](area.bg);
);
out center tags;
"""

PLACES_QUERY = f"""
[out:json][timeout:300];
{AREA}
node["place"~"^(city|town|village)$"]["name"](area.bg);
out;
"""


# Спорт: фитнес, хайкинг (маршрути и хижи), колоездене (маршрути и под наем), други.
# Отделни по-малки заявки — общата често не минава през претоварените Overpass сървъри.
SPORT_QUERIES = {
    "fitness": 'nwr["leisure"="fitness_station"](area.bg); nwr["leisure"="fitness_centre"]["name"](area.bg);',
    "hiking": 'relation["route"="hiking"]["name"](area.bg); nwr["tourism"~"^(alpine_hut|wilderness_hut)$"]["name"](area.bg);',
    "cycling": 'relation["route"~"^(bicycle|mtb)$"]["name"](area.bg); nwr["amenity"="bicycle_rental"](area.bg);',
    "other": ('nwr["leisure"~"^(sports_centre|horse_riding|water_park)$"]["name"](area.bg); '
              'nwr["sport"~"^(climbing|karting|skiing)$"]["name"](area.bg); nwr["landuse"="winter_sports"]["name"](area.bg);'),
}


# Храна и нощувка
AMENITY_QUERIES = {
    "food": 'nwr["amenity"~"^(restaurant|fast_food)$"]["name"](area.bg);',
    "lodging": 'nwr["tourism"~"^(hotel|motel|guest_house|hostel|chalet|camp_site|apartment)$"]["name"](area.bg);',
}


def sport_query(body: str) -> str:
    return f"[out:json][timeout:240];\n{AREA}\n({body});\nout center tags;"


# Отбелязани опасности: свлачища, падащи камъни
HAZARDS_QUERY = f"""
[out:json][timeout:300];
{AREA}
nwr["hazard"~"landslide|rockfall|falling_rocks|rock_fall"](area.bg);
out center tags;
"""


def fetch(name: str, query: str) -> None:
    out = RAW / f"{name}.json"
    if out.exists() and "--force" not in sys.argv:
        print(f"{out.name} вече е свален (--force за ново сваляне)")
        return
    print(f"Overpass: {name}…")
    data = overpass(query)
    print(f"  {len(data['elements'])} обекта")
    save_json(out, data["elements"])


def main() -> None:
    fetch("osm_pois", POIS_QUERY)
    fetch("osm_places", PLACES_QUERY)
    fetch("osm_hazards", HAZARDS_QUERY)
    for name, body in SPORT_QUERIES.items():
        fetch(f"osm_sport_{name}", sport_query(body))
    # обединяваме в един файл за merge_pois
    parts = [RAW / f"osm_sport_{n}.json" for n in SPORT_QUERIES]
    if all(p.exists() for p in parts):
        save_json(RAW / "osm_sport.json", [e for p in parts for e in load_json(p)])
    for name, body in AMENITY_QUERIES.items():
        fetch(f"osm_{name}", sport_query(body))


if __name__ == "__main__":
    main()
