# reconcile_locations_to_excel.py
import json
from pathlib import Path
from typing import Dict, List, Any, Tuple
import difflib

import pandas as pd


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

# ------------- Helpers de normalização / core_name ------------- #

REGION_TOKENS = set(REGIONS)


def normalize_name(name: str) -> str:
    if not name:
        return ""
    return name.strip().lower().replace(" ", "-")


def core_name(name: str) -> str:
    """
    Remove prefixos de região e tenta manter o "miolo" útil.
    ex:
      'kanto-route-1' -> 'route-1'
      'route-1-kalos' -> 'route-1-kalos' (aqui região vem como sufixo)
    Simples mas suficiente pra boa parte dos casos.
    """
    if not name:
        return ""

    n = normalize_name(name)
    tokens = [t for t in n.split("-") if t]

    # se o primeiro token é uma região, remove
    if tokens and tokens[0] in REGION_TOKENS:
        tokens = tokens[1:]

    # tentativa simples: juntar de volta
    return "-".join(tokens)


# ------------- Carregamento do dump da PokeAPI ------------- #

def load_pokeapi_dump(path: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Estrutura esperada (gerada pelo sync_pokeapi_locations_dump.py):
    {
      "kanto": [
        {"name": "pallet-town", "areas": ["pallet-town-area", ...]},
        ...
      ],
      ...
    }
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data


def build_pokeapi_indexes(poke_dump: Dict[str, List[Dict[str, Any]]]):
    locations_by_name = {}  # name -> {name, areas, region}
    areas_by_name = {}      # area_name -> {area_name, location_name, region}

    for region, locs in poke_dump.items():
        for loc in locs:
            name = loc["name"]
            areas = loc.get("areas", [])
            locations_by_name[name] = {
                "name": name,
                "areas": areas,
                "region": region,
            }

            for a in areas:
                areas_by_name[a] = {
                    "area_name": a,
                    "location_name": name,
                    "region": region,
                }

    return locations_by_name, areas_by_name


# ------------- Carregamento do dump do BD ------------- #

def load_bd_locations(path: str) -> List[Dict[str, Any]]:
    """
    Espera uma lista de dicts, por ex:
    [
      {
        "id": 1,
        "location_api_name": "pallet-town",
        "default_area": "pallet-town-area",
        "region": "Kanto",
        "type": "city",
        "wild_status": "empty",
      },
      ...
    ]
    """
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ------------- Lógica de matching ------------- #

def find_best_location_candidates(
    bd_loc_name: str,
    bd_region: str,
    locations_by_name: Dict[str, Dict[str, Any]],
) -> List[Tuple[str, float]]:
    """
    Tenta achar candidatos na PokeAPI para um location do BD
    usando:
      - core_name
      - similaridade textual (difflib)
      - foco primeiro na mesma região
    Retorna lista [(nome_poke, score), ...] ordenada por score desc.
    """
    bd_norm = normalize_name(bd_loc_name)
    bd_core = core_name(bd_loc_name)
    bd_region_norm = normalize_name(bd_region)

    same_region_candidates = []
    other_region_candidates = []

    for name, meta in locations_by_name.items():
        region = meta["region"]
        name_norm = normalize_name(name)
        name_core = core_name(name)

        score_name = difflib.SequenceMatcher(None, bd_norm, name_norm).ratio()
        score_core = difflib.SequenceMatcher(None, bd_core, name_core).ratio()
        score = max(score_name, score_core)

        if score < 0.5:
            continue

        if region == bd_region_norm:
            same_region_candidates.append((name, score))
        else:
            other_region_candidates.append((name, score))

    same_region_candidates.sort(key=lambda x: x[1], reverse=True)
    other_region_candidates.sort(key=lambda x: x[1], reverse=True)

    return same_region_candidates + other_region_candidates


def reconcile(
    bd_locations: List[Dict[str, Any]],
    locations_by_name: Dict[str, Dict[str, Any]],
    areas_by_name: Dict[str, Dict[str, Any]],
):
    rows_ok = []
    rows_loc_invalid = []
    rows_area_invalid = []
    rows_wild_suspect = []

    for row in bd_locations:
        bd_id = row.get("id")
        bd_loc_name = row.get("location_api_name") or ""
        bd_area = row.get("default_area") or ""
        bd_region = (row.get("region") or "").lower()
        bd_type = (row.get("type") or "").lower()
        wild_status = row.get("wild_status")  # "empty" ou "non_empty"

        norm_loc = normalize_name(bd_loc_name)
        norm_area = normalize_name(bd_area)

        poke_loc = locations_by_name.get(norm_loc)
        poke_area = areas_by_name.get(norm_area)

        loc_exists = poke_loc is not None
        area_exists = poke_area is not None

        base_info = {
            "bd_id": bd_id,
            "bd_location_api_name": bd_loc_name,
            "bd_default_area": bd_area,
            "bd_region": bd_region,
            "bd_type": bd_type,
            "bd_wild_status": wild_status,
        }

        if loc_exists and area_exists:
            rows_ok.append(
                {
                    **base_info,
                    "status": "ok",
                    "poke_location_name": poke_loc["name"],
                    "poke_location_region": poke_loc["region"],
                    "poke_areas": ",".join(poke_loc["areas"]),
                    "poke_area_region": poke_area["region"],
                }
            )
        else:
            candidates = find_best_location_candidates(
                bd_loc_name, bd_region, locations_by_name
            )

            top_candidates = candidates[:3]
            cand_names = [c[0] for c in top_candidates]
            cand_scores = [round(c[1], 3) for c in top_candidates]

            common_fields = {
                **base_info,
                "loc_exists": loc_exists,
                "area_exists": area_exists,
                "candidate_names": ", ".join(cand_names),
                "candidate_scores": ", ".join(map(str, cand_scores)),
            }

            if not loc_exists:
                rows_loc_invalid.append(
                    {
                        **common_fields,
                        "status": "location_invalid",
                    }
                )

            if loc_exists and not area_exists:
                rows_area_invalid.append(
                    {
                        **common_fields,
                        "status": "area_invalid",
                        "poke_location_name": poke_loc["name"],
                        "poke_location_region": poke_loc["region"],
                        "poke_areas": ",".join(poke_loc["areas"]),
                    }
                )

        if bd_type in {"route", "dungeon", "cave", "outside"} and wild_status == "empty":
            rows_wild_suspect.append(
                {
                    **base_info,
                    "loc_exists": loc_exists,
                    "area_exists": area_exists,
                }
            )

    return rows_ok, rows_loc_invalid, rows_area_invalid, rows_wild_suspect


def main(
    poke_dump_path="pokeapi_locations_dump.json",
    bd_dump_path="bd_locations_dump.json",
    out_excel_path="reconciliation_report.xlsx",
):
    print("[LOAD] Lendo dump da PokeAPI...")
    poke_dump = load_pokeapi_dump(poke_dump_path)
    locations_by_name, areas_by_name = build_pokeapi_indexes(poke_dump)

    locations_by_name = {
        normalize_name(k): v for k, v in locations_by_name.items()
    }
    areas_by_name = {
        normalize_name(k): v for k, v in areas_by_name.items()
    }

    print("[LOAD] Lendo dump do BD...")
    bd_locations = load_bd_locations(bd_dump_path)

    print("[RECONCILE] Reconciliando locations...")
    rows_ok, rows_loc_invalid, rows_area_invalid, rows_wild_suspect = reconcile(
        bd_locations, locations_by_name, areas_by_name
    )

    print("[EXCEL] Gerando planilha...")
    with pd.ExcelWriter(out_excel_path, engine="openpyxl") as writer:
        pd.DataFrame(rows_ok).to_excel(writer, sheet_name="ok", index=False)
        pd.DataFrame(rows_loc_invalid).to_excel(
            writer, sheet_name="location_invalid", index=False
        )
        pd.DataFrame(rows_area_invalid).to_excel(
            writer, sheet_name="area_invalid", index=False
        )
        pd.DataFrame(rows_wild_suspect).to_excel(
            writer, sheet_name="wild_suspect", index=False
        )

    print(f"[DONE] Salvo em {out_excel_path}")


if __name__ == "__main__":
    main()
