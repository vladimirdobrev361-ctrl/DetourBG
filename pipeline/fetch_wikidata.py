"""Обогатява OSM обектите с данни от Wikidata: снимка, описание, статия в Уикипедия,
брой езикови версии (мярка за популярност) и дали е обект на ЮНЕСКО.

Връзката е по тага `wikidata=Q…` в OSM.
Употреба: python -m pipeline.fetch_wikidata [--force]
"""
import sys
import time

from pipeline.common import RAW, client, load_json, save_json

SPARQL_URL = "https://query.wikidata.org/sparql"
OUT = RAW / "wikidata.json"
BATCH = 150

QUERY = """
SELECT ?item ?sitelinks ?image ?descBg ?descEn ?articleBg ?whs WHERE {
  VALUES ?item { %s }
  ?item wikibase:sitelinks ?sitelinks .
  OPTIONAL { ?item wdt:P18 ?image }
  OPTIONAL { ?item schema:description ?descBg FILTER(LANG(?descBg) = "bg") }
  OPTIONAL { ?item schema:description ?descEn FILTER(LANG(?descEn) = "en") }
  OPTIONAL { ?articleBg schema:about ?item ; schema:isPartOf <https://bg.wikipedia.org/> }
  OPTIONAL { ?item wdt:P1435 wd:Q9259 . BIND(true AS ?whs) }
}
"""


def main() -> None:
    if OUT.exists() and "--force" not in sys.argv:
        print(f"{OUT.name} вече е свален (--force за ново сваляне)")
        return
    pois = load_json(RAW / "osm_pois.json")
    ids = sorted({p["tags"]["wikidata"] for p in pois if p.get("tags", {}).get("wikidata", "").startswith("Q")})
    print(f"Wikidata: {len(ids)} обекта")
    result: dict[str, dict] = {}
    with client(timeout=120) as http:
        for i in range(0, len(ids), BATCH):
            values = " ".join(f"wd:{q}" for q in ids[i : i + BATCH])
            r = http.post(SPARQL_URL, data={"query": QUERY % values, "format": "json"})
            r.raise_for_status()
            for b in r.json()["results"]["bindings"]:
                qid = b["item"]["value"].rsplit("/", 1)[1]
                item = result.setdefault(qid, {"sitelinks": int(b["sitelinks"]["value"])})
                for key in ("image", "descBg", "descEn", "articleBg"):
                    if key in b and key not in item:
                        item[key] = b[key]["value"]
                if "whs" in b:
                    item["unesco"] = True
            print(f"  {min(i + BATCH, len(ids))}/{len(ids)}")
            time.sleep(1)
    save_json(OUT, result)


if __name__ == "__main__":
    main()
