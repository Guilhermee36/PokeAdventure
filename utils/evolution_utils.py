# utils/evolution_utils.py

import utils.pokeapi_service as pokeapi
from supabase import Client
from postgrest import APIResponse
import re 

_evo_chain_cache = {}
API_GENDER_MAP = { 1: 'female', 2: 'male', 3: 'genderless' }

async def _get_evo_chain_data(url: str) -> dict | None:
    # ... (código sem alterações) ...
    if url in _evo_chain_cache:
        return _evo_chain_cache[url]
    data = await pokeapi.get_data_from_url(url)
    if data:
        _evo_chain_cache[url] = data
    return data

def _find_evolution_node(chain: dict, pokemon_name: str) -> dict | None:
    # ... (código sem alterações) ...
    if chain["species"]["name"] == pokemon_name:
        return chain
    for evo in chain["evolves_to"]:
        found = _find_evolution_node(evo, pokemon_name)
        if found:
            return found
    return None

def _get_species_id_from_url(url: str) -> int | None:
    # ... (código sem alterações) ...
    match = re.search(r"/pokemon-species/(\d+)/", url)
    if match:
        return int(match.group(1))
    return None

def _check_level_up_conditions(details: dict, context: dict, pkmn_data: dict) -> bool:
    """Verifica condições para evoluções do tipo 'level-up'."""
    # ... (esta função permanece exatamente a mesma, já estava completa) ...
    
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
    held_item = details.get("held_item", {}).get("name")
    if held_item:
        if pkmn_data.get("held_item") != held_item:
            return False 
    # Condição 4: Hora do Dia
    time_of_day = details.get("time_of_day")
    if time_of_day and time_of_day != context.get("time_of_day"):
        return False 
    # Condição 5: Conhecer um Ataque
    known_move = details.get("known_move", {}).get("name")
    if known_move:
        if known_move not in pkmn_data.get("moves", []):
            return False
    # Condição 6: Tipo na Equipe
    party_type = details.get("party_type", {}).get("name")
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
    location = details.get("location", {}).get("name")
    if location:
        if context.get("current_location_name") != location:
            return False
    # Condição 10: Inkay
    if details.get("turn_upside_down", False):
        return False
        
    return True 

# =================================================================
# <<< FUNÇÃO ATUALIZADA >>>
# =================================================================
def _check_item_use_conditions(details: dict, context: dict, pkmn_data: dict) -> bool:
    """
    Verifica condições para evoluções do tipo 'item_use'.
    AGORA SUPORTA CONDIÇÕES MÚLTIPLAS (ex: item + hora do dia).
    """
    
    item_used = context.get("item_name")
    if not item_used:
        return False

    # --- Condição Principal: Item usado bate com o item esperado? ---
    item_needed = details.get("item", {}).get("name")
    
    # --- Casos Especiais (Link Cable, Inkay) ---
    trigger_name = details.get("trigger", {}).get("name")
    
    is_link_cable_trade = (trigger_name == "trade" and item_used == "link-cable")
    is_inkay_scroll = (details.get("turn_upside_down", False) and item_used == "topsy-turvy-scroll")
    
    # Se não for o item correto E não for um caso especial, falha
    if (item_needed and item_used != item_needed) and not is_link_cable_trade and not is_inkay_scroll:
        return False

    # --- Se o item BATEU (ou é um caso especial), checa condições SECUNDÁRIAS ---
    
    # Condição 2: Gênero (Ex: Kirlia -> Gallade)
    gender_id = details.get("gender")
    if gender_id:
        required_gender = API_GENDER_MAP.get(gender_id)
        if pkmn_data.get("gender") != required_gender:
            return False

    # Condição 3: Hora do Dia (Ex: Ursaring -> Ursaluna, Sneasel-H -> Sneasler)
    time_of_day = details.get("time_of_day")
    if time_of_day and time_of_day != context.get("time_of_day"):
        return False # Hora errada

    # Condição 4: Localização (Ex: Eevee -> Leafeon/Glaceon com Leaf Stone)
    # (Nota: A API às vezes tem 'location' em evoluções de item, ex: Eevee)
    location = details.get("location", {}).get("name")
    if location:
        if context.get("current_location_name") != location:
            return False
            
    # Condição 5: Item Segurado (Exclusivo do Link Cable)
    if is_link_cable_trade:
        item_needed_to_hold = details.get("held_item", {}).get("name")
        if item_needed_to_hold:
            if pkmn_data.get("held_item") != item_needed_to_hold:
                return False
    
    # Condição 6: Nível Mínimo (Exclusivo do Inkay)
    if is_inkay_scroll:
         min_level = details.get("min_level")
         if min_level and pkmn_data["current_level"] < min_level:
            return False

    # Passou em todas as verificações!
    return True

# --- FUNÇÃO PRINCIPAL (check_evolution) ---
async def check_evolution(
    supabase: Client, 
    *, 
    pokemon_db_id: str, 
    trigger_event: str, 
    context: dict = None
) -> dict | None:
    """
    Verifica se um Pokémon pode evoluir com base em um gatilho.
    (Esta função permanece a mesma, ela apenas chama os checkers acima)
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
        
        # 5. Verificar se os detalhes batem com o gatilho
        for details in details_list:
            trigger_type = details.get("trigger", {}).get("name")

            if trigger_event != trigger_type:
                # Exceção: 'item_use' pode acionar 'trade' ou 'turn_upside_down'
                if trigger_event == "item_use" and (trigger_type == "trade" or details.get("turn_upside_down", False)):
                     pass # Deixa o _check_item_use_conditions decidir
                else:
                    continue 

            # 6. Chamar o handler de verificação correto
            evolution_allowed = False
            if trigger_event == "level_up":
                evolution_allowed = _check_level_up_conditions(details, context, pkmn)
            
            elif trigger_event == "item_use":
                evolution_allowed = _check_item_use_conditions(details, context, pkmn)

            # 7. Se a evolução for permitida, retorna os dados!
            if evolution_allowed:
                return {
                    "old_name": current_name,
                    "new_name": new_species_name,
                    "new_api_id": _get_species_id_from_url(potential_evo["species"]["url"])
                }
    
    return None