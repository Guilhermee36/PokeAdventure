# utils/evolution_utils.py

import re
from supabase import Client
import utils.pokeapi_service as pokeapi

# cache simples p/ chain
_EVO_CHAIN_CACHE: dict[str, dict] = {}
API_GENDER_MAP = {1: "female", 2: "male", 3: "genderless"}

async def _get_evo_chain_data(url: str) -> dict | None:
    if url in _EVO_CHAIN_CACHE:
        return _EVO_CHAIN_CACHE[url]
    data = await pokeapi.get_data_from_url(url)
    if data:
        _EVO_CHAIN_CACHE[url] = data
    return data

def _find_evolution_node(chain: dict, pokemon_name: str) -> dict | None:
    if chain["species"]["name"] == pokemon_name:
        return chain
    for evo in chain.get("evolves_to", []):
        found = _find_evolution_node(evo, pokemon_name)
        if found:
            return found
    return None

def _get_species_id_from_url(url: str) -> int | None:
    m = re.search(r"/pokemon-species/(\d+)/", url)
    return int(m.group(1)) if m else None

# ---------- condições: level-up ----------
def _check_level_up_conditions(details: dict, context: dict, pkmn: dict) -> bool:
    # 1) min_level
    min_level = details.get("min_level")
    if min_level and pkmn["current_level"] < min_level:
        return False

    # 2) min_happiness (coluna happiness)
    min_happiness = details.get("min_happiness")
    if min_happiness and pkmn.get("happiness", 70) < min_happiness:
        return False

    # 3) held_item
    held_item = (details.get("held_item") or {}).get("name")
    if held_item and pkmn.get("held_item") != held_item:
        return False

    # 4) known_move / known_move_type
    known_move = (details.get("known_move") or {}).get("name")
    if known_move and known_move not in (pkmn.get("moves") or []):
        return False

    known_move_type = (details.get("known_move_type") or {}).get("name")
    if known_move_type and known_move_type not in (pkmn.get("move_types") or []):
        return False

    # 5) hora do dia (context['time_of_day'] -> players.game_time_of_day)
    time_of_day = details.get("time_of_day")
    if time_of_day and context.get("time_of_day") != time_of_day:
        return False

    # 6) gênero (coluna gender)
    gender_id = details.get("gender")
    if gender_id and pkmn.get("gender") != API_GENDER_MAP.get(gender_id):
        return False

    # 7) atk vs def (usa attack/defense)
    rel = details.get("relative_physical_stats")
    if rel is not None:
        atk = pkmn.get("attack", 0)
        df = pkmn.get("defense", 0)
        if rel == 1 and not (atk > df): return False
        if rel == -1 and not (atk < df): return False
        if rel == 0 and not (atk == df): return False

    # 8) localização
    location = (details.get("location") or {}).get("name")
    if location and context.get("current_location_name") != location:
        return False

    # 9) upside_down (Inkay) não via level-up no seu jogo
    if details.get("turn_upside_down", False):
        return False

    return True

# ---------- condições: uso de item ----------
def _check_item_use_conditions(details: dict, context: dict, pkmn: dict, new_species: str) -> bool:
    item_used = context.get("item_name")  # api_name do item usado
    if not item_used:
        return False

    item_needed = (details.get("item") or {}).get("name")
    trigger_name = (details.get("trigger") or {}).get("name")

    is_link_cable_trade = (trigger_name == "trade" and item_used == "link-cable")
    is_inkay_scroll = (details.get("turn_upside_down", False) and item_used == "topsy-turvy-scroll")

    # se pede item específico (pedras), exige match, exceto se for um dos casos especiais
    if (item_needed and item_used != item_needed) and not (is_link_cable_trade or is_inkay_scroll):
        return False

    # filtros extra
    gender_id = details.get("gender")
    if gender_id and pkmn.get("gender") != API_GENDER_MAP.get(gender_id):
        return False

    time_of_day = details.get("time_of_day")
    if time_of_day and context.get("time_of_day") != time_of_day:
        return False

    location = (details.get("location") or {}).get("name")
    if location and context.get("current_location_name") != location:
        return False

    if is_link_cable_trade:
        need_held = (details.get("held_item") or {}).get("name")
        if need_held and pkmn.get("held_item") != need_held:
            return False

    if is_inkay_scroll:
        min_level = details.get("min_level")
        if min_level and pkmn["current_level"] < min_level:
            return False

    return True

# ---------- função principal ----------
async def check_evolution(
    *,
    supabase: Client,
    pokemon_db_id: str,
    trigger_event: str,          # "level_up" | "item_use"
    context: dict | None = None, # precisa conter: time_of_day, current_location_name, (opcional item_name)
) -> dict | None:
    context = context or {}

    # lê mon do DB *(snake_case)*
    res = supabase.table("player_pokemon").select("*").eq("id", pokemon_db_id).single().execute()
    if not res.data:
        return None
    pkmn = res.data
    current_name = pkmn["pokemon_api_name"]

    # espécie + chain
    species = await pokeapi.get_pokemon_species_data(current_name)
    if not species or not species.get("evolution_chain", {}).get("url"):
        return None
    chain_data = await _get_evo_chain_data(species["evolution_chain"]["url"])
    if not chain_data:
        return None

    node = _find_evolution_node(chain_data["chain"], current_name)
    if not node:
        return None

    for evo in node.get("evolves_to", []):
        new_name = evo["species"]["name"]
        for details in evo.get("evolution_details", []):
            trigger_data = details.get("trigger")
            trigger_type = trigger_data.get("name") if isinstance(trigger_data, dict) else trigger_data

            allowed = False
            if trigger_event == "level_up":
                if trigger_type == "level-up":  # hífen
                    allowed = _check_level_up_conditions(details, context, pkmn)

            elif trigger_event == "item_use":
                if trigger_type in ("use-item", "trade", "level-up") or details.get("turn_upside_down", False):
                    allowed = _check_item_use_conditions(details, context, pkmn, new_name)

            if allowed:
                return {
                    "old_name": current_name,
                    "new_name": new_name,
                    "new_api_id": _get_species_id_from_url(evo["species"]["url"]),
                }

    return None
