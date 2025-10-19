# utils/pokeapi_service.py

import aiohttp

# Cache manual para armazenar os RESULTADOS (JSON), não as corrotinas.
# A chave será a URL completa para garantir que cada endpoint seja único.
api_cache = {}
BASE_URL = "https://pokeapi.co/api/v2"

async def get_data_from_url(url: str):
    """
    Função genérica para buscar dados de qualquer URL da PokeAPI, usando nosso cache manual.
    """
    # 1. Verifica se o resultado para esta URL já está no cache.
    if url in api_cache:
        # Se estiver, retorna o dado salvo imediatamente.
        return api_cache[url]

    # 2. Se não estiver no cache, faz a requisição HTTP.
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                # 3. Armazena o resultado (o dicionário JSON) no cache.
                api_cache[url] = data
                return data
            # Retorna None se a API der erro (ex: Pokémon não encontrado).
            return None

async def get_pokemon_data(pokemon_name_or_id: str):
    """Busca dados principais de um Pokémon (endpoint /pokemon/)."""
    url = f"{BASE_URL}/pokemon/{str(pokemon_name_or_id).lower()}"
    return await get_data_from_url(url)

async def get_pokemon_species_data(pokemon_name_or_id: str):
    """
    Busca dados da espécie de um Pokémon (endpoint /pokemon-species/).
    Essencial para obter a URL da cadeia de evolução.
    """
    # Precisamos desta função para a lógica de evolução funcionar corretamente.
    pokemon_data = await get_pokemon_data(pokemon_name_or_id)
    if pokemon_data and 'species' in pokemon_data:
        species_url = pokemon_data['species']['url']
        return await get_data_from_url(species_url)
    return None

async def get_total_xp_for_level(growth_rate_url: str, level: int) -> int:
    """Busca a tabela de XP e retorna o total necessário para um nível específico."""
    growth_data = await get_data_from_url(growth_rate_url)
    if not growth_data:
        return float('inf') # Retorna um número enorme se a busca falhar

    # Procura o nível exato na lista de "levels" da API.
    for level_info in growth_data.get('levels', []):
        if level_info.get('level') == level:
            return level_info['experience']
            
    return float('inf') # Retorna se o nível não for encontrado

def find_evolution_details(chain: dict, current_pokemon_name: str) -> list | None:
    """
    Função recursiva para encontrar os detalhes da próxima evolução possível
    a partir do nome do Pokémon atual na cadeia de evolução.
    """
    if chain.get('species', {}).get('name') == current_pokemon_name:
        # Encontramos o Pokémon, retornamos a lista de suas próximas evoluções.
        return chain.get('evolves_to', [])

    # Se não for o atual, busca recursivamente nas próximas evoluções.
    for evolution in chain.get('evolves_to', []):
        result = find_evolution_details(evolution, current_pokemon_name)
        # O 'is not None' é importante para não parar em ramos sem evolução.
        if result is not None:
            return result
            
    return None