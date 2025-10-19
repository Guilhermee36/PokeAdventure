# pokeapi_service.py

import httpx
import aiohttp
from functools import lru_cache

BASE_URL = "https://pokeapi.co/api/v2"

@lru_cache(maxsize=128)
async def get_pokemon_data(pokemon_name: str) -> dict | None:
    """Busca os dados principais de um Pokémon (incluindo stats) da PokeAPI.
    Args:
        pokemon_name (str): O nome do Pokémon.
    Returns:
        dict | None: Um dicionário com os dados do Pokémon se encontrado, senão None.
    """
    url = f"https://pokeapi.co/api/v2/pokemon/{pokemon_name.lower()}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.json()
            else:
                return None

@lru_cache(maxsize=32)
async def get_data_from_url(url: str) -> dict:
    """Função genérica e cacheada para buscar dados de uma URL específica da API."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError:
            return None

async def get_total_xp_for_level(growth_rate_url: str, level: int) -> int:
    """Busca a quantidade TOTAL de XP necessária para um Pokémon atingir um determinado nível."""
    growth_data = await get_data_from_url(growth_rate_url)
    if not growth_data:
        return float('inf')

    if 1 < level <= len(growth_data['levels']):
        return growth_data['levels'][level - 1]['experience']
    
    return float('inf')

def find_evolution_details(chain: dict, pokemon_name: str) -> list:
    """Função recursiva para encontrar os detalhes da próxima evolução de um Pokémon."""
    if chain['species']['name'] == pokemon_name:
        return chain['evolves_to']

    for evolution in chain['evolves_to']:
        result = find_evolution_details(evolution, pokemon_name)
        if result:
            return result
            
    return []