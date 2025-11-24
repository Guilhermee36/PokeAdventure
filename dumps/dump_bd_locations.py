# dump_bd_locations.py
import json
from pathlib import Path
import os
import asyncio
import sys

# garante que a pasta raiz (onde está utils) esteja no path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from supabase import create_client, Client
from utils import pokeapi_service as pokeapi


SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]  # mesma key que você usa no backend


def get_supabase_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


async def build_bd_locations_dump(region: str | None = None):
    """
    Lê a tabela locations do Supabase e monta uma lista de dicts no formato:

    {
      "location_api_name": "pallet-town",
      "default_area": "pallet-town-area",
      "region": "Kanto",
      "type": "city",
      "wild_status": "empty" | "non_empty",
    }
    """
    supabase = get_supabase_client()

    # NÃO usa mais id
    q = supabase.table("locations").select(
        "location_api_name,default_area,region,type"
    )

    if region:
        # ilike pra permitir "Kanto", "kanto", etc
        q = q.ilike("region", region)

    q = q.order("region").order("location_api_name")
    res = q.execute()
    rows = list(res.data or [])

    print(f"[BD] Total de locations lidas: {len(rows)}")

    out = []

    for row in rows:
        loc_name = row["location_api_name"]
        area = row.get("default_area")
        loc_region = row.get("region")
        loc_type = row.get("type")

        # default: se não tem área, consideramos wilds vazios
        wild_status = "empty"

        if area:
            try:
                encounters = await pokeapi.get_location_area_encounters(
                    area, version=None
                )
                if encounters:
                    wild_status = "non_empty"
                else:
                    wild_status = "empty"
            except Exception as e:
                # Loga erro, mas mantém "empty" pra não quebrar o pipeline
                print(
                    f"[ERRO] {loc_region} / {loc_name} area={area} → {e}"
                )
                wild_status = "empty"

        out.append(
            {
                "location_api_name": loc_name,
                "default_area": area,
                "region": loc_region,
                "type": loc_type,
                "wild_status": wild_status,
            }
        )

    return out


def dump_bd_locations(path: str = "bd_locations_dump.json", region: str | None = None):
    """
    Gera o arquivo JSON que o reconcile_locations_to_excel.py usa.
    """
    locations = asyncio.run(build_bd_locations_dump(region=region))
    Path(path).write_text(json.dumps(locations, indent=2), encoding="utf-8")
    print(f"[DONE] Dump salvo em {path}")


if __name__ == "__main__":
    # Se quiser filtrar por região específica, troca region="Kalos" por outra ou None
    dump_bd_locations(path="bd_locations_dump.json", region=None)
