# utils/pokeapi_service.py

import aiohttp
import math
import re

# Cache manual p/ resultados JSON
api_cache = {}
BASE_URL = "https://pokeapi.co/api/v2"

# Headers para PokeAPI:
# - Accept-Encoding: identity → pede resposta SEM compressão (sem gzip/br/zstd)
API_HEADERS = {
    "Accept": "application/json",
    "Accept-Encoding": "identity",
    "User-Agent": "PokeAdventure/1.0",
}


async def get_data_from_url(url: str):
    if url in api_cache:
        return api_cache[url]
    try:
        # Session com headers fixos (sem zstd)
        async with aiohttp.ClientSession(headers=API_HEADERS) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    api_cache[url] = data
                    return data
                else:
                    print(f"Erro ao buscar dados da API: {resp.status}, url={url}")
    except Exception as e:
        print(f"Erro ao buscar dados da API: {e}")
    return None


async def get_pokemon_data(pokemon_name_or_id: str):
    url = f"{BASE_URL}/pokemon/{str(pokemon_name_or_id).lower()}"
    return await get_data_from_url(url)


async def get_pokemon_species_data(pokemon_name_or_id: str):
    url = f"{BASE_URL}/pokemon-species/{str(pokemon_name_or_id).lower()}"
    return await get_data_from_url(url)


async def get_evolution_chain_data(chain_url: str):
    return await get_data_from_url(chain_url)


async def get_total_xp_for_level(growth_rate_url: str, level: int) -> int | float:
    growth_data = await get_data_from_url(growth_rate_url)
    if not growth_data:
        return float("inf")
    for level_info in growth_data.get("levels", []):
        if level_info.get("level") == level:
            return level_info["experience"]
    return float("inf")


def find_evolution_details(chain: dict, current_pokemon_name: str) -> list | None:
    if chain.get("species", {}).get("name") == current_pokemon_name:
        return chain.get("evolves_to", [])
    for evolution in chain.get("evolves_to", []):
        result = find_evolution_details(evolution, current_pokemon_name)
        if result is not None:
            return result
    return None


# ---------- cálculo de stats (alinhado ao schema snake_case) ----------
def calculate_stats_for_level(base_stats: list, level: int) -> dict:
    """
    hp -> max_hp
    attack -> attack
    defense -> defense
    special-attack -> special_attack
    special-defense -> special_defense
    speed -> speed
    """
    stat_name_map = {
        "hp": "max_hp",
        "attack": "attack",
        "defense": "defense",
        "special-attack": "special_attack",
        "special-defense": "special_defense",
        "speed": "speed",
    }

    stats = {}
    for stat in base_stats:
        api_name = stat["stat"]["name"]
        base_val = stat["base_stat"]
        db_col = stat_name_map.get(api_name)
        if not db_col:
            continue
        if api_name == "hp":
            val = math.floor(((2 * base_val * level) / 100) + level + 10)
        else:
            val = math.floor(((2 * base_val * level) / 100) + 5)
        stats[db_col] = val
    return stats


def get_initial_moves(pokemon_api_data: dict, starting_level: int) -> list:
    """
    4 moves mais recentes por nível aprendido (level-up) até starting_level.
    """
    candidates = []
    for move_info in pokemon_api_data.get("moves", []):
        move_name = move_info.get("move", {}).get("name")
        if not move_name:
            continue
        for vd in move_info.get("version_group_details", []):
            method = (vd.get("move_learn_method") or {}).get("name")
            if method == "level-up":
                lvl = vd.get("level_learned_at", 0) or 0
                if 0 < lvl <= starting_level:
                    candidates.append((lvl, move_name))
                    break
    candidates.sort(key=lambda x: (x[0], x[1]))  # por nível, depois nome
    initial_moves = [name for _, name in candidates[-4:]]
    while len(initial_moves) < 4:
        initial_moves.append(None)
    return initial_moves


# ---------- helpers de flavor text / sprites ----------
def _clean_flavor_text(text: str) -> str:
    """Limpa o texto da Pokédex removendo quebras de linha e caracteres de controle."""
    if not text:
        return "Nenhuma descrição encontrada."
    text = text.replace("\n", " ").replace("\f", " ")
    text = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def get_portuguese_flavor_text(species_data: dict) -> str:
    """
    ***Função esperada pelo TeamCog***:
    recebe o dict de `pokemon-species` e devolve um flavor text em pt-BR (fallback: en).
    """
    if not species_data or "flavor_text_entries" not in species_data:
        return "Descrição não disponível."
    for entry in species_data["flavor_text_entries"]:
        if entry.get("language", {}).get("name") == "pt":
            return _clean_flavor_text(entry.get("flavor_text", ""))
    for entry in species_data["flavor_text_entries"]:  # fallback inglês
        if entry.get("language", {}).get("name") == "en":
            return _clean_flavor_text(entry.get("flavor_text", ""))
    return "Descrição não disponível."


async def get_species_flavor_text_pt(pokemon_name_or_id: str) -> str:
    """
    Wrapper opcional: aceita um nome/id, busca `pokemon-species` e retorna o texto em pt/en.
    """
    data = await get_pokemon_species_data(pokemon_name_or_id)
    return get_portuguese_flavor_text(data)


# ---------- encontros por location-area (PokeAPI) ----------


async def get_location_area_encounters(
    location_area_name: str, version: str | None = None
) -> list[dict]:
    """
    Retorna uma lista simplificada de encontros de Pokémon para uma location-area da PokeAPI.

    Cada item:
      {
        'pokemon_name': str,
        'chance': int,       # chance máxima encontrada para essa versão
        'min_level': int,
        'max_level': int
      }

    Se `version` for None, considera qualquer versão disponível.
    """
    if not location_area_name:
        return []

    url = f"{BASE_URL}/location-area/{str(location_area_name).lower()}"
    data = await get_data_from_url(url)
    if not data:
        return []

    version = version.lower() if version else None
    results: list[dict] = []

    for enc in data.get("pokemon_encounters", []):
        poke = enc.get("pokemon") or {}
        name = (poke.get("name") or "").lower()
        if not name:
            continue

        best_chance = 0
        min_level = 1
        max_level = 1

        for vd in enc.get("version_details", []):
            vname = ((vd.get("version") or {}).get("name") or "").lower()
            if version and vname != version:
                continue

            for det in vd.get("encounter_details", []):
                chance = int(det.get("chance") or 0)
                if chance > best_chance:
                    best_chance = chance
                    min_level = int(det.get("min_level") or 1)
                    max_level = int(det.get("max_level") or min_level)

        if best_chance <= 0:
            continue

        results.append(
            {
                "pokemon_name": name,
                "chance": best_chance,
                "min_level": min_level,
                "max_level": max_level,
            }
        )

    return results


async def get_pokemon_sprite_urls(pokemon_name: str) -> dict:
    data = await get_pokemon_data(pokemon_name)
    if not data:
        return {}
    sprites = data.get("sprites", {}) or {}
    return {
        "front_default": sprites.get("front_default"),
        "official_artwork": sprites.get("other", {})
        .get("official-artwork", {})
        .get("front_default"),
    }


async def get_species_flavor_text_en(pokemon_name_or_id: str) -> str:
    data = await get_pokemon_species_data(pokemon_name_or_id)
    if not data:
        return "Description unavailable."
    for entry in data.get("flavor_text_entries", []):
        if entry.get("language", {}).get("name") == "en":
            return _clean_flavor_text(entry.get("flavor_text", ""))
    return "Descrição não disponível."
