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
    Espera uma lista de dicts, por ex (id agora é opcional):
    [
      {
        "location_api_name": "pallet-town",
        "default_area": "pallet-town-area",
        "region": "Kanto",
        "type": "city",
        "wild_status": "empty" | "non_empty",
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
    """
    Agora retorna UMA linha por location do BD (lista rows_all),
    com colunas:
      - bd_*
      - loc_exists / area_exists
      - candidate_names / candidate_scores
      - poke_* infos (se disponíveis)
      - status: ok | location_invalid | area_invalid | wild_suspect
    """
    rows_all = []

    for row in bd_locations:
        bd_id = row.get("id")  # pode ser None
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

        # candidatos só fazem sentido se não estiver tudo ok
        candidates = []
        if not (loc_exists and area_exists):
            candidates = find_best_location_candidates(
                bd_loc_name, bd_region, locations_by_name
            )

        top_candidates = candidates[:3]
        cand_names = [c[0] for c in top_candidates]
        cand_scores = [round(c[1], 3) for c in top_candidates]

        # definição de status (uma label principal por linha)
        if not loc_exists:
            status = "location_invalid"
        elif loc_exists and not area_exists:
            status = "area_invalid"
        elif bd_type in {"route", "dungeon", "cave", "outside"} and wild_status == "empty":
            status = "wild_suspect"
        else:
            status = "ok"

        base_info = {
            "bd_id": bd_id,
            "bd_location_api_name": bd_loc_name,
            "bd_default_area": bd_area,
            "bd_region": bd_region,
            "bd_type": bd_type,
            "bd_wild_status": wild_status,
            "loc_exists": loc_exists,
            "area_exists": area_exists,
            "candidate_names": ", ".join(cand_names),
            "candidate_scores": ", ".join(map(str, cand_scores)),
            "status": status,
        }

        poke_fields = {
            "poke_location_name": None,
            "poke_location_region": None,
            "poke_areas": None,
            "poke_area_region": None,
        }

        if poke_loc:
            poke_fields["poke_location_name"] = poke_loc["name"]
            poke_fields["poke_location_region"] = poke_loc["region"]
            poke_fields["poke_areas"] = ",".join(poke_loc["areas"])

        if poke_area:
            poke_fields["poke_area_region"] = poke_area["region"]

        rows_all.append({**base_info, **poke_fields})

    return rows_all


def main(
    poke_dump_path="pokeapi_locations_dump.json",
    bd_dump_path="bd_locations_dump.json",
    out_excel_path="reconciliation_report.xlsx",
):
    print("[LOAD] Lendo dump da PokeAPI...")
    poke_dump = load_pokeapi_dump(poke_dump_path)
    locations_by_name, areas_by_name = build_pokeapi_indexes(poke_dump)

    # normaliza chaves pra comparação
    locations_by_name = {normalize_name(k): v for k, v in locations_by_name.items()}
    areas_by_name = {normalize_name(k): v for k, v in areas_by_name.items()}

    print("[LOAD] Lendo dump do BD...")
    bd_locations = load_bd_locations(bd_dump_path)
    print(f"[INFO] Total de locations no BD: {len(bd_locations)}")

    print("[RECONCILE] Reconciliando locations...")
    rows_all = reconcile(bd_locations, locations_by_name, areas_by_name)

    df_all = pd.DataFrame(rows_all)

    # visões derivadas (só filtros em cima de all)
    df_ok = df_all[df_all["status"] == "ok"]
    df_location_invalid = df_all[df_all["status"] == "location_invalid"]
    df_area_invalid = df_all[df_all["status"] == "area_invalid"]
    df_wild_suspect = df_all[
        (df_all["bd_type"].isin(["route", "dungeon", "cave", "outside"]))
        & (df_all["bd_wild_status"] == "empty")
    ]

    print("[STATS] Status counts (all):")
    print(df_all["status"].value_counts(dropna=False))

    print("[EXCEL] Gerando planilha...")
    with pd.ExcelWriter(out_excel_path, engine="openpyxl") as writer:
        df_all.to_excel(writer, sheet_name="all", index=False)
        df_ok.to_excel(writer, sheet_name="ok", index=False)
        df_location_invalid.to_excel(
            writer, sheet_name="location_invalid", index=False
        )
        df_area_invalid.to_excel(writer, sheet_name="area_invalid", index=False)
        df_wild_suspect.to_excel(writer, sheet_name="wild_suspect", index=False)

    print(f"[DONE] Salvo em {out_excel_path}")


if __name__ == "__main__":
    main()
