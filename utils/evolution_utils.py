
# utils/evolution_utils.py

import utils.pokeapi_service as pokeapi
from supabase import Client
from postgrest import APIResponse
import re 

# Cache para a cadeia de evolução
_evo_chain_cache = {}
API_GENDER_MAP = { 1: 'female', 2: 'male', 3: 'genderless' }

async def _get_evo_chain_data(url: str) -> dict | None:
    """Busca dados da cadeia de evolução da API, com cache."""
    if url in _evo_chain_cache:
        return _evo_chain_cache[url]
    data = await pokeapi.get_data_from_url(url)
    if data:
        _evo_chain_cache[url] = data
    return data

def _find_evolution_node(chain: dict, pokemon_name: str) -> dict | None:
    """Encontra o nó da cadeia de evolução correspondente ao Pokémon atual."""
    if chain["species"]["name"] == pokemon_name:
        return chain
    for evo in chain["evolves_to"]:
        found = _find_evolution_node(evo, pokemon_name)
        if found:
            return found
    return None

def _get_species_id_from_url(url: str) -> int | None:
    """Extrai o ID da espécie da URL da API."""
    match = re.search(r"/pokemon-species/(\d+)/", url)
    if match:
        return int(match.group(1))
    return None

def _check_level_up_conditions(details: dict, context: dict, pkmn_data: dict) -> bool:
    """Verifica condições para evoluções do tipo 'level-up'."""
    # Condição 1: Nível Mínimo
    min_level = details.get("min_level")
    if min_level and pkmn_data["current_level"] < min_level:
        return False 

    # Condição 2: Felicidade Mínima
    min_happiness = details.get("min_happiness")
    if min_happiness:
        if pkmn_data.get("happiness", 70) < min_happiness:
            return False
            
    # Condição 3: Item Segurado
    held_item = (details.get("held_item") or {}).get("name")
    if held_item:
        if pkmn_data.get("held_item") != held_item:
            return False

    # Condição 4: Movimento conhecido (known_move) e/ou known_move_type
    known_move = (details.get("known_move") or {}).get("name")
    if known_move:
        moves_list = pkmn_data.get("moves", []) or []
        if known_move not in moves_list:
            return False

    known_move_type = (details.get("known_move_type") or {}).get("name")
    if known_move_type:
        move_types_list = pkmn_data.get("move_types", []) or []
        if known_move_type not in move_types_list:
            return False

    # Condição 5: Tempo do dia
    time_of_day = details.get("time_of_day")
    if time_of_day:
        if context.get("game_time_of_day") != time_of_day:
            return False

    # Condição 6: Afiliar partido (Beauty, Affection) — ignoradas por simplicidade
    # Condição 7: Troca com parceiro específico — ignorada no level-up

    # Condição 8: Attack vs Defense (ex: Tyrogue)
    relative_physical_stats = details.get("relative_physical_stats")
    if relative_physical_stats is not None:
        atk = pkmn_data.get("attack", 0)
        defense = pkmn_data.get("defense", 0)
        if relative_physical_stats == 1 and not (atk > defense): return False
        if relative_physical_stats == -1 and not (atk < defense): return False
        if relative_physical_stats == 0 and not (atk == defense): return False
        
    # Condição 9: Localização
    location = (details.get("location") or {}).get("name")
    if location:
        if context.get("current_location_name") != location:
            return False
            
    # Condição 10: Inkay (ignorado no level-up, tratado com item)
    if details.get("turn_upside_down", False):
        return False
        
    return True 

def _check_item_use_conditions(details: dict, context: dict, pkmn_data: dict, new_species_name: str) -> bool:
    """
    Verifica condições para evoluções do tipo 'item_use'.
    Suporta condições múltiplas e itens customizados.
    """
    item_used = context.get("item_name")  # 'api_name' (ex: "water-stone")
    if not item_used:
        return False

    item_needed = (details.get("item") or {}).get("name")  # 'api_name' da PokeAPI
    trigger_name = (details.get("trigger") or {}).get("name")
    
    # --- Casos Especiais (Workarounds) ---
    is_link_cable_trade = (trigger_name == "trade" and item_used == "link-cable")
    is_inkay_scroll = (details.get("turn_upside_down", False) and item_used == "topsy-turvy-scroll")

    # 1) Evoluções padrão: usar pedra
    if trigger_name == "use-item" and item_needed:
        return item_used == item_needed

    # 2) Evolução por "trade" substituída por Link Cable
    if is_link_cable_trade:
        return True

    # 3) Inkay "virar de ponta-cabeça" substituído por item custom
    if is_inkay_scroll:
        return True

    # 4) Workarounds de level-up acionados via item (Sylveon etc.)
    if trigger_name == "level-up":
        # Reaproveita as mesmas checagens do level-up
        return _check_level_up_conditions(details, context, pkmn_data)

    return False

async def check_evolution(
    *, 
    supabase: Client, 
    pokemon_db_id: str, 
    trigger_event: str, 
    context: dict = None
) -> dict | None:
    """
    Verifica se um Pokémon pode evoluir com base em um gatilho.
    """
    if context is None:
        context = {}
    
    # 1. Buscar dados do Pokémon (Lê os dados frescos do DB)
    pkmn_response = supabase.table("player_pokemon").select("*").eq("id", pokemon_db_id).single().execute()
    if not pkmn_response.data:
        print(f"Evolução falhou: Pokémon com db_id {pokemon_db_id} não encontrado.")
        return None
    pkmn = pkmn_response.data
    current_name = pkmn["pokemon_api_name"]

    # 2. Buscar dados da Espécie e Cadeia de Evolução
    species_data = await pokeapi.get_pokemon_species_data(current_name)
    if not species_data or "evolution_chain" not in species_data or not species_data["evolution_chain"]["url"]:
        return None 
    evo_chain_data = await _get_evo_chain_data(species_data["evolution_chain"]["url"])
    if not evo_chain_data:
        return None

    # 3. Encontrar o "nó" atual
    current_evo_node = _find_evolution_node(evo_chain_data["chain"], current_name)
    if not current_evo_node:
        return None

    # 4. Iterar possíveis evoluções
    for potential_evo in current_evo_node.get("evolves_to", []):
        new_species_name = potential_evo["species"]["name"]
        for details in potential_evo.get("evolution_details", []):
            trigger_data = details.get("trigger")

            # trigger_data pode vir como dict {"name": "..."} ou como string "level-up"
            trigger_type = None
            if isinstance(trigger_data, dict):
                trigger_type = trigger_data.get("name")
            elif isinstance(trigger_data, str):
                # Formato visto em alguns dumps: "level-up"
                trigger_type = trigger_data

            is_turn_upside_down = details.get("turn_upside_down", False)
            evolution_allowed = False
            
            if trigger_event == "level_up":
                # Se o gatilho for level-up, SÓ checa evoluções de level-up
                if trigger_type == "level-up":
                    # Checa min_level, min_happiness, known_move, time_of_day etc.
                    evolution_allowed = _check_level_up_conditions(details, context, pkmn)
            
            elif trigger_event == "item_use":
                # Se o gatilho for item, checa tipos de evolução acionados por item
                # 1. É uma evolução 'use-item' (Pedras)?
                if trigger_type == "use-item":
                    evolution_allowed = _check_item_use_conditions(details, context, pkmn, new_species_name)
                # 2. É uma evolução 'trade' (Link Cable)?
                elif trigger_type == "trade":
                    evolution_allowed = _check_item_use_conditions(details, context, pkmn, new_species_name)
                # 3. É a evolução 'turn_upside_down' (Inkay)?
                elif is_turn_upside_down:
                    evolution_allowed = _check_item_use_conditions(details, context, pkmn, new_species_name)
                # 4. É uma das nossas 'level-up' customizadas (Sylveon, etc)?
                elif trigger_type == "level-up":
                    evolution_allowed = _check_item_use_conditions(details, context, pkmn, new_species_name)

            # 7. Se a evolução for permitida, retorna os dados!
            if evolution_allowed:
                return {
                    "old_name": current_name,
                    "new_name": new_species_name,
                    "new_api_id": _get_species_id_from_url(potential_evo["species"]["url"])
                }
    
    return None  # Nenhuma evolução encontrada
