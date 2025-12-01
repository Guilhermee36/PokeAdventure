# sync_pokeapi_locations_dump.py
import requests
import json
from pathlib import Path

BASE = "https://pokeapi.co/api/v2"

REGIONS = [
    "kanto",
    "johto",
    "hoenn",
    "sinnoh",
    "unova",
    "kalos",
    "alola",
    "galar",
    "hisui",
    "paldea",
]


def fetch_json(url: str):
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json()


def get_region_locations(region_name: str):
    """
    Retorna uma lista de dicts:
    [
      {"name": "pallet-town", "areas": ["pallet-town-area", ...]},
      ...
    ]
    """
    region_data = fetch_json(f"{BASE}/region/{region_name}")
    locations = region_data["locations"]  # lista com {"name", "url"}

    out = []

    for loc in locations:
        loc_name = loc["name"]
        loc_data = fetch_json(loc["url"])
        areas = [a["name"] for a in loc_data.get("areas", [])]

        out.append(
            {
                "name": loc_name,
                "areas": areas,
            }
        )

    return out


def dump_regions(path: str = "pokeapi_locations_dump.json"):
    out = {}

    for region in REGIONS:
        print(f"[POKEAPI] Sincronizando região: {region}")
        locs = get_region_locations(region)
        out[region] = locs

    Path(path).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Salvo em {path}")


if __name__ == "__main__":
    dump_regions()
