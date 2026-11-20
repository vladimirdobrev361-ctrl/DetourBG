"""Сваля регистрите на Министерството на туризма от data.egov.bg:

- туристически забележителности: https://data.egov.bg/data/view/428bd51a-f1bf-487b-89db-6cab9e2a8cc4 (към 07.05.2024)
- категоризирани места за настаняване: https://data.egov.bg/data/view/8e3acd9a-0da2-4b21-940d-92b1fd9200bb (към 31.12.2025)
- категоризирани заведения за хранене: https://data.egov.bg/data/view/95381bd0-28c9-41a8-98d1-4c1e6fef7083 (към 31.12.2025)

Сървърът отговаря бавно (около минута на регистър), затова файловете се кешират.
Употреба: python -m pipeline.fetch_registry [--force]
"""
import sys

from pipeline.common import RAW, client, save_json

API_URL = "https://data.egov.bg/api/getResourceData"
RESOURCES = {
    "registry": "b3165822-0821-4fdf-a80e-0f416e85a35e",
    "lodging_registry": "211a298d-bae0-4594-945f-0ee99b1e879d",
    "food_registry": "48f94fea-f0da-4612-af8f-e3bb5f4d39cf",
}


def fetch(name: str, resource_uri: str) -> None:
    out = RAW / f"{name}.json"
    if out.exists() and "--force" not in sys.argv:
        print(f"{out.name} вече е свален (--force за ново сваляне)")
        return
    print(f"Свалям {name} от data.egov.bg (около минута)…")
    with client(timeout=600) as http:
        r = http.post(API_URL, json={"resource_uri": resource_uri})
        r.raise_for_status()
        payload = r.json()
    if not payload.get("success") or not payload.get("data"):
        raise RuntimeError(f"data.egov.bg върна грешка за {name}: {str(payload)[:200]}")
    rows = payload["data"]
    print(f"  {len(rows) - 1} записа, колони: {rows[0]}")
    save_json(out, rows)


def main() -> None:
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or list(RESOURCES)
    for name in names:
        fetch(name, RESOURCES[name])


if __name__ == "__main__":
    main()
