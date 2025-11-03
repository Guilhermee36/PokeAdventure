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
    """Encontra o nó do Pokémon atual na cadeia de evolução."""
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
    # ✅ CORREÇÃO: (details.get("chave") or {}) previne erro se 'held_item' for null
    held_item = (details.get("held_item") or {}).get("name")
    if held_item:
        # 'held_item' no DB deve ser o 'api_name' (ex: "metal-coat")
        if pkmn_data.get("held_item") != held_item:
            return False 
            
    # Condição 4: Hora do Dia
    time_of_day = details.get("time_of_day")
    if time_of_day and time_of_day != context.get("time_of_day"):
        return False 
        
    # Condição 5: Conhecer um Ataque
    # ✅ CORREÇÃO: (details.get("chave") or {}) previne erro se 'known_move' for null
    known_move = (details.get("known_move") or {}).get("name")
    if known_move:
        if known_move not in pkmn_data.get("moves", []):
            return False
            
    # Condição 6: Tipo na Equipe
    # ✅ CORREÇÃO: (details.get("chave") or {}) previne erro se 'party_type' for null
    party_type = (details.get("party_type") or {}).get("name")
    if party_type:
        if party_type not in context.get("party_types", []):
            return False
            
    # Condição 7: Gênero
    gender_id = details.get("gender")
    if gender_id:
        required_gender = API_GENDER_MAP.get(gender_id)
        if pkmn_data.get("gender") != required_gender:
            return False
            
    # Condição 8: Stats Relativos
    stat_comparison = details.get("relative_physical_stats")
    if stat_comparison is not None:
        atk = pkmn_data.get("attack", 0)
        defense = pkmn_data.get("defense", 0)
        if stat_comparison == 1 and not (atk > defense): return False
        if stat_comparison == -1 and not (atk < defense): return False
        if stat_comparison == 0 and not (atk == defense): return False
        
    # Condição 9: Localização
    # ✅ CORREÇÃO: (details.get("chave") or {}) previne erro se 'location' for null
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
    
    item_used = context.get("item_name") # Este deve ser o 'api_name' (ex: "water-stone")
    if not item_used:
        return False

    # --- Condição Principal: Item usado bate com o item esperado? ---
    # ✅ CORREÇÃO: (details.get("chave") or {}) previne erro se 'item' for null
    item_needed = (details.get("item") or {}).get("name") # Este é o 'api_name' da PokeAPI
    
    # ✅ CORREÇÃO: (details.get("chave") or {}) previne erro se 'trigger' for null
    trigger_name = (details.get("trigger") or {}).get("name")
    
    # --- Casos Especiais (Workarounds) ---
    is_link_cable_trade = (trigger_name == "trade" and item_used == "link-cable")
    is_inkay_scroll = (details.get("turn_upside_down", False) and item_used == "topsy-turvy-scroll")

    # --- Nossos Itens Customizados ---
    is_sylveon_ribbon = (new_species_name == "sylveon" and item_used == "fita-de-sylveon")
    is_runerigus_fragment = (new_species_name == "runerigus" and item_used == "fragmento-de-tumba")
    is_basculegion_soul = (new_species_name == "basculegion" and item_used == "alma-perdida")
    
    # Se não for o item correto (ex: item_used 'water-stone' == item_needed 'water-stone')
    # E não for nenhum dos nossos casos especiais, falha.
    if (item_needed and item_used != item_needed) and \
       not is_link_cable_trade and \
       not is_inkay_scroll and \
       not is_sylveon_ribbon and \
       not is_runerigus_fragment and \
       not is_basculegion_soul:
        return False

    # --- Se o item BATEU (ou é um caso especial), checa condições SECUNDÁRIAS ---
    
    # Condição 2: Gênero (Ex: Kirlia -> Gallade OU Basculin -> Basculegion)
    gender_id = details.get("gender")
    if gender_id:
        required_gender = API_GENDER_MAP.get(gender_id)
        if pkmn_data.get("gender") != required_gender:
            return False

    # Condição 3: Hora do Dia (Ex: Ursaring -> Ursaluna)
    time_of_day = details.get("time_of_day")
    if time_of_day and time_of_day != context.get("time_of_day"):
        return False 

    # Condição 4: Localização (Ex: Eevee -> Leafeon/Glaceon)
    # ✅ CORREÇÃO: (details.get("chave") or {}) previne erro se 'location' for null
    # (Embora seja raro em item_use, é uma boa prática)
    location = (details.get("location") or {}).get("name")
    if location:
        if context.get("current_location_name") != location:
            return False
            
    # Condição 5: Item Segurado (Exclusivo do Link Cable)
    if is_link_cable_trade:
        # ✅ CORREÇÃO: (details.get("chave") or {}) previne erro se 'held_item' for null
        item_needed_to_hold = (details.get("held_item") or {}).get("name") # ex: "metal-coat"
        if item_needed_to_hold:
            if pkmn_data.get("held_item") != item_needed_to_hold:
                return False
    
    # Condição 6: Nível Mínimo (Exclusivo do Inkay)
    if is_inkay_scroll:
         min_level = details.get("min_level")
         if min_level and pkmn_data["current_level"] < min_level:
            return False
            
    # Condição 7: Felicidade (Exclusivo da Fita de Sylveon)
    if is_sylveon_ribbon:
        min_happiness = details.get("min_happiness", 160)
        if pkmn_data.get("happiness", 70) < min_happiness:
            return False

    # Passou em todas as verificações!
    return True

# =================================================================
# <<< FUNÇÃO PRINCIPAL (COM A LÓGICA CORRIGIDA) >>>
# =================================================================
async def check_evolution(
    supabase: Client, 
    *, 
    pokemon_db_id: str, 
    trigger_event: str, 
    context: dict = None
) -> dict | None:
    """
    (Versão corrigida)
    Verifica se um Pokémon pode evoluir com base em um gatilho.
    """
    if context is None:
        context = {}
    
    # 1. Buscar dados do Pokémon
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
    if not current_evo_node or not current_evo_node.get("evolves_to"):
        return None # Não evolui mais

    # 4. Iterar sobre as evoluções POSSÍVEIS
    for potential_evo in current_evo_node["evolves_to"]:
        new_species_name = potential_evo["species"]["name"]
        details_list = potential_evo["evolution_details"]
        
        # 5. Iterar sobre os detalhes
        for details in details_list:
            
            # --- LÓGICA DE FILTRO CORRIGIDA ---
            # ✅ CORREÇÃO: (details.get("chave") or {}) previne erro se 'trigger' for null
            trigger_details = details.get("trigger") or {}
            trigger_type = trigger_details.get("name") # ex: "level-up", "use-item", "trade"
            
            is_turn_upside_down = details.get("turn_upside_down", False)

            evolution_allowed = False
            
            if trigger_event == "level_up":
                # Se o gatilho for level-up, SÓ checa evoluções de level-up
                if trigger_type == "level_up":
                    evolution_allowed = _check_level_up_conditions(details, context, pkmn)
            
            elif trigger_event == "item_use":
                # Se o gatilho for item, checa MÚLTIPLOS tipos de evolução
                
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
                elif trigger_type == "level_up":
                     evolution_allowed = _check_item_use_conditions(details, context, pkmn, new_species_name)
            # --- FIM DA LÓGICA CORRIGIDA ---

            # 7. Se a evolução for permitida, retorna os dados!
            if evolution_allowed:
                return {
                    "old_name": current_name,
                    "new_name": new_species_name,
                    "new_api_id": _get_species_id_from_url(potential_evo["species"]["url"])
                }
    
    return None # Nenhuma evolução encontrada