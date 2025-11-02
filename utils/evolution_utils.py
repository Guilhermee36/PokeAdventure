# utils/evolution_utils.py

import utils.pokeapi_service as pokeapi
from supabase import Client
from postgrest import APIResponse

# Cache simples para armazenar dados da cadeia de evolução (URL -> dados)
_evo_chain_cache = {}

async def _get_evo_chain_data(url: str) -> dict | None:
    """Busca dados da cadeia de evolução com cache."""
    if url in _evo_chain_cache:
        return _evo_chain_cache[url]
    
    data = await pokeapi.get_data_from_url(url)
    if data:
        _evo_chain_cache[url] = data
    return data

def _find_evolution_node(chain: dict, pokemon_name: str) -> dict | None:
    """Navega recursivamente na cadeia de evolução para encontrar o nó do Pokémon atual."""
    if chain["species"]["name"] == pokemon_name:
        return chain
    
    for evo in chain["evolves_to"]:
        found = _find_evolution_node(evo, pokemon_name)
        if found:
            return found
    return None

def _get_species_id_from_url(url: str) -> int | None:
    """Extrai o ID da URL da espécie."""
    import re
    match = re.search(r"/pokemon-species/(\d+)/", url)
    if match:
        return int(match.group(1))
    return None

def _check_level_up_conditions(details: dict, context: dict, pkmn_data: dict) -> bool:
    """
    Verifica condições para evoluções do tipo 'level-up'.
    Exemplos: Gligar (nível + item + noite), Togepi (nível + felicidade), Pancham (nível + tipo na party).
    """
    
    # Condição 1: Nível Mínimo
    min_level = details.get("min_level")
    if min_level and pkmn_data["current_level"] < min_level:
        return False # Não tem o nível mínimo

    # Condição 2: Felicidade Mínima (Ex: Togepi -> Togetic, Chansey -> Blissey)
    min_happiness = details.get("min_happiness")
    if min_happiness:
        # REQUER QUE A COLUNA 'happiness' (int) EXISTA NA TABELA 'player_pokemon'
        if pkmn_data.get("happiness", 70) < min_happiness:
            return False

    # Condição 3: Item Segurado (Ex: Gligar -> Gliscor)
    held_item = details.get("held_item", {}).get("name")
    if held_item:
        # REQUER QUE A COLUNA 'held_item' (text) EXISTA NA TABELA 'player_pokemon'
        if pkmn_data.get("held_item") != held_item:
            return False 

    # Condição 4: Hora do Dia (Ex: Eevee -> Umbreon/Espeon, Gligar -> Gliscor)
    time_of_day = details.get("time_of_day")
    # O 'context' deve fornecer a hora atual do jogo (ex: 'day' ou 'night')
    if time_of_day and time_of_day != context.get("time_of_day"):
        return False # Hora errada

    # Condição 5: Conhecer um Ataque (Ex: Aipom -> Ambipom)
    known_move = details.get("known_move", {}).get("name")
    if known_move:
        # 'moves' deve ser uma lista de nomes/IDs. Ex: ["tackle", "growl", ...]
        if known_move not in pkmn_data.get("moves", []):
            return False
    
    # Condição 6: Pokémon de um tipo específico na Equipe (Ex: Pancham -> Pangoro)
    party_type = details.get("party_type", {}).get("name")
    if party_type:
        # O 'context' DEVE fornecer uma lista de tipos da party.
        # Ex: context = {"party_types": ["normal", "flying", "dark"]}
        if party_type not in context.get("party_types", []):
            return False
    
    # Condição 7: Inkay (Virar o console)
    if details.get("turn_upside_down", False):
        # Tratado em 'item_use' com um item especial
        return False
        
    return True # Passou em todas as verificações de level_up

def _check_item_use_conditions(details: dict, context: dict, pkmn_data: dict) -> bool:
    """
    Verifica condições para evoluções do tipo 'item_use'.
    Exemplos: Eevee + Fire Stone, ou casos especiais como Inkay.
    """
    
    item_used = context.get("item_name")
    if not item_used:
        return False

    # Condição 1: Item usado bate com o item esperado? (Ex: 'fire-stone')
    item_needed = details.get("item", {}).get("name")
    if item_needed and item_used == item_needed:
        return True
        
    # Condição 2: Caso especial Inkay (turn_upside_down)
    # Mapeamos a flag 'turn_upside_down' para um item fictício 'topsy-turvy-scroll'
    # E o Pokémon deve ter o nível mínimo
    min_level = details.get("min_level")
    if details.get("turn_upside_down", False) and item_used == "topsy-turvy-scroll":
        if min_level and pkmn_data["current_level"] >= min_level:
            return True
        elif not min_level:
             return True

    # Condição 3: Caso especial 'link-cable' (simula 'trade')
    # Se o gatilho da API for 'trade', mas usamos o item 'link-cable'
    trigger_name = details.get("trigger", {}).get("name")
    if trigger_name == "trade" and item_used == "link-cable":
        # Verifica se há um item segurado necessário (ex: Onix + 'metal-coat')
        item_needed_to_hold = details.get("held_item", {}).get("name")
        if item_needed_to_hold:
            # REQUER 'held_item' no banco de dados
            if pkmn_data.get("held_item") == item_needed_to_hold:
                return True
        else:
            # Evolução por troca simples (ex: Kadabra)
            return True
            
    return False

# --- FUNÇÃO PRINCIPAL ---

async def check_evolution(
    supabase: Client, 
    *, 
    pokemon_db_id: str, 
    trigger_event: str, 
    context: dict = None
) -> dict | None:
    """
    Verifica se um Pokémon pode evoluir com base em um gatilho.
    Retorna um dicionário com os dados da evolução se ela ocorrer, senão None.

    Args:
        supabase: O cliente Supabase.
        pokemon_db_id: O ID ÚNICO (uuid) do Pokémon na tabela player_pokemon.
        trigger_event: "level_up", "item_use", ou "trade".
        context: Dados adicionais. 
                 Para "level_up": {'time_of_day': 'day'/'night', 'party_types': ['dark', 'grass'], ...}
                 Para "item_use": {'item_name': 'fire-stone'}
    """
    if context is None:
        context = {}
    
    # 1. Buscar dados do Pokémon no Supabase
    pkmn_response = supabase.table("player_pokemon").select("*").eq("id", pokemon_db_id).single().execute()
    if not pkmn_response.data:
        print(f"Evolução falhou: Pokémon com db_id {pokemon_db_id} não encontrado.")
        return None
    
    pkmn = pkmn_response.data
    current_name = pkmn["pokemon_api_name"]

    # 2. Buscar dados da Espécie e Cadeia de Evolução na PokeAPI
    species_data = await pokeapi.get_pokemon_species_data(current_name)
    if not species_data or "evolution_chain" not in species_data or not species_data["evolution_chain"]["url"]:
        return None # Pokémon não tem cadeia de evolução (ex: Lendário)
    
    evo_chain_data = await _get_evo_chain_data(species_data["evolution_chain"]["url"])
    if not evo_chain_data:
        return None

    # 3. Encontrar o "nó" atual na cadeia de evolução
    current_evo_node = _find_evolution_node(evo_chain_data["chain"], current_name)
    if not current_evo_node or not current_evo_node.get("evolves_to"):
        return None # Este Pokémon não evolui mais

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
                     pass # Deixa a função _check_item_use_conditions decidir
                else:
                    continue # Gatilhos não batem

            # 6. Chamar o handler de verificação correto
            evolution_allowed = False
            if trigger_event == "level_up":
                evolution_allowed = _check_level_up_conditions(details, context, pkmn)
            
            elif trigger_event == "item_use":
                evolution_allowed = _check_item_use_conditions(details, context, pkmn)
            
            elif trigger_event == "trade":
                # Lógica de troca (ex: Karrablast/Shelmet) - Simplificado
                evolution_allowed = True 

            # 7. Se a evolução for permitida, retorna os dados!
            if evolution_allowed:
                return {
                    "old_name": current_name,
                    "new_name": new_species_name,
                    "new_api_id": _get_species_id_from_url(potential_evo["species"]["url"])
                }
    
    return None # Nenhuma evolução válida encontrada