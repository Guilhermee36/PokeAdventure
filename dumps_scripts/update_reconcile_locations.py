import pandas as pd
from pathlib import Path

excel_path = Path("reconciliation_report.xlsx")  # ajuste o caminho se precisar

xls = pd.ExcelFile(excel_path)
df_all         = pd.read_excel(xls, "all")
df_loc_invalid = pd.read_excel(xls, "location_invalid")
df_area_invalid = pd.read_excel(xls, "area_invalid")
df_wild_suspect = pd.read_excel(xls, "wild_suspect")

# 1) Mapa de infos por poke_location_name (wilds + áreas de exemplo)
loc_stats = {}
for _, row in df_all.iterrows():
    name = row["poke_location_name"]
    if pd.isna(name):
        continue
    has_wilds = not pd.isna(row["poke_areas"])
    if name not in loc_stats:
        loc_stats[name] = {"has_wilds": False, "areas": set()}
    if has_wilds:
        loc_stats[name]["has_wilds"] = True
        for area in str(row["poke_areas"]).split(","):
            loc_stats[name]["areas"].add(area.strip())

def choose_candidate(row):
    # pega candidates e scores
    cand_names = str(row["candidate_names"])
    if cand_names == "nan":
        return None, None, False

    cand_names = [c.strip() for c in cand_names.split(",") if c.strip()]

    scores_raw = str(row["candidate_scores"])
    if scores_raw == "nan":
        scores = [1.0] * len(cand_names)
    else:
        scores = [float(x.strip()) for x in scores_raw.split(",") if x.strip()]
        if len(scores) < len(cand_names):
            scores += [scores[-1]] * (len(cand_names) - len(scores))

    candidates = []
    for name, score in zip(cand_names, scores):
        stats = loc_stats.get(name, {"has_wilds": False, "areas": set()})
        has_wilds = stats["has_wilds"]
        example_area = next(iter(stats["areas"]), None)
        candidates.append((name, score, has_wilds, example_area))

    if not candidates:
        return None, None, False

    # ordena: 1º tem wilds, depois maior score
    candidates.sort(key=lambda c: (not c[2], -c[1]))
    best_name, best_score, best_has_wilds, best_area = candidates[0]
    return best_name, best_area, best_has_wilds

sql_lines = []

# 2) LOCATION_INVALID: corrigir location_api_name e default_area
for _, row in df_loc_invalid.iterrows():
    old_loc = row["bd_location_api_name"]
    best_name, best_area, has_wilds = choose_candidate(row)

    if not best_name:
        continue  # não achou nada útil

    # fallback pra default_area se não tiver área conhecida
    if not best_area or best_area == "nan":
        # você pode trocar essa linha pra outra lógica se quiser
        best_area = row["bd_default_area"] or f"{best_name}-area"

    sql_lines.append(
        f"-- {old_loc} -> {best_name} (has_wilds={has_wilds})\n"
        f"UPDATE public.locations\n"
        f"SET location_api_name = '{best_name}',\n"
        f"    default_area      = '{best_area}'\n"
        f"WHERE location_api_name = '{old_loc}';\n"
    )

# 3) AREA_INVALID + WILD_SUSPECT: só corrigir default_area usando poke_areas
def area_updates(df, comment_prefix):
    lines = []
    for _, row in df.iterrows():
        bd_loc = row["bd_location_api_name"]
        poke_areas = row["poke_areas"]
        if pd.isna(poke_areas):
            continue
        first_area = str(poke_areas).split(",")[0].strip()
        lines.append(
            f"-- {comment_prefix} {bd_loc}: set default_area = {first_area}\n"
            f"UPDATE public.locations\n"
            f"SET default_area = '{first_area}'\n"
            f"WHERE location_api_name = '{bd_loc}';\n"
        )
    return lines

sql_lines += area_updates(df_area_invalid,  "area_invalid")
sql_lines += area_updates(df_wild_suspect, "wild_suspect")

# 4) salvar tudo num arquivo
out_path = Path("generated_updates.sql")
out_path.write_text("\n".join(sql_lines), encoding="utf-8")

print(f"Arquivo gerado: {out_path.resolve()}")
