# utils/pokeapi_service.py

import aiohttp
import math

# Cache manual para armazenar os RESULTADOS (JSON), não as corrotinas.
# A chave será a URL completa para garantir que cada endpoint seja único.
api_cache = {}
BASE_URL = "https://pokeapi.co/api/v2"

async def get_data_from_url(url: str):
    """
    Função genérica para buscar dados de qualquer URL da PokeAPI, usando nosso cache manual.
    """
    if url in api_cache:
        return api_cache[url]

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                api_cache[url] = data
                return data
            return None

async def get_pokemon_data(pokemon_name_or_id: str):
    """
    Busca dados de BATALHA de um Pokémon (stats, types, moves, etc.).
    Endpoint: /pokemon/{id}
    """
    url = f"{BASE_URL}/pokemon/{str(pokemon_name_or_id).lower()}"
    return await get_data_from_url(url)

async def get_pokemon_species_data(pokemon_name_or_id: str):
    """
    Busca dados de ESPÉCIE de um Pokémon (growth_rate, evolution_chain).
    Endpoint: /pokemon-species/{id}
    """
    url = f"{BASE_URL}/pokemon-species/{str(pokemon_name_or_id).lower()}"
    return await get_data_from_url(url)

async def get_total_xp_for_level(growth_rate_url: str, level: int) -> int:
    """Busca a tabela de XP e retorna o total necessário para um nível específico."""
    growth_data = await get_data_from_url(growth_rate_url)
    if not growth_data:
        return float('inf')

    for level_info in growth_data.get('levels', []):
        if level_info.get('level') == level:
            return level_info['experience']
            
    return float('inf')

def find_evolution_details(chain: dict, current_pokemon_name: str) -> list | None:
    """
    Função recursiva para encontrar os detalhes da próxima evolução possível
    a partir do nome do Pokémon atual na cadeia de evolução.
    """
    if chain.get('species', {}).get('name') == current_pokemon_name:
        return chain.get('evolves_to', [])

    for evolution in chain.get('evolves_to', []):
        result = find_evolution_details(evolution, current_pokemon_name)
        if result is not None:
            return result
            
    return None

# --- NOVA FUNÇÃO DE LÓGICA DE JOGO PARA CÁLCULO DE STATS ---
def calculate_stats_for_level(base_stats: list, level: int) -> dict:
    """
    Calcula os stats de um Pokémon para um nível específico usando uma fórmula simplificada.
    base_stats: A lista de 'stats' vinda diretamente da PokeAPI.
    level: O nível atual do Pokémon.
    """
    stats = {}
    
    stat_name_map = {
        "hp": "max_hp",
        "attack": "attack",
        "defense": "defense",
        "special-attack": "special_attack",
        "special-defense": "special_defense",
        "speed": "speed"
    }

    for stat_info in base_stats:
        base_value = stat_info['base_stat']
        stat_name_api = stat_info['stat']['name']
        
        db_col_name = stat_name_map.get(stat_name_api)
        if not db_col_name:
            continue

        if stat_name_api == 'hp':
            # Fórmula do HP: floor( ( (2 * Base * Level) / 100 ) + Level + 10 )
            calculated_value = math.floor(((2 * base_value * level) / 100) + level + 10)
        else:
            # Fórmula para outros stats: floor( ( (2 * Base * Level) / 100 ) + 5 )
            calculated_value = math.floor(((2 * base_value * level) / 100) + 5)
        
        stats[db_col_name] = calculated_value
        
    return stats

def get_initial_moves(pokemon_api_data: dict, starting_level: int) -> list:
    """
    Busca e retorna os 4 ataques mais recentes que um Pokémon aprendeu até um certo nível.
    """
    potential_moves = set() # Usamos um set para evitar ataques duplicados

    for move_info in pokemon_api_data.get('moves', []):
        for version_details in move_info.get('version_group_details', []):
            if version_details.get('move_learn_method', {}).get('name') == 'level-up' and version_details.get('level_learned_at', 0) <= starting_level and version_details.get('level_learned_at', 0) > 0:
                potential_moves.add(move_info['move']['name'])

    # Ordena os ataques e pega os 4 últimos (os mais recentes)
    sorted_moves = sorted(list(potential_moves))
    initial_moves = sorted_moves[-4:]

    # Preenche a lista com 'None' (que vira 'null' no JSONB) até ter 4 elementos
    while len(initial_moves) < 4:
        initial_moves.append(None)
    
    return initial_moves