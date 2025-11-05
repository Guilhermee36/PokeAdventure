# utils/pokeapi_service.py

import aiohttp
import math
import re

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
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    api_cache[url] = data
                    return data
    except Exception as e:
        print(f"Erro ao buscar dados da API: {e}")
    return None

async def get_pokemon_data(pokemon_name: str):
    """Busca dados do endpoint `pokemon/`."""
    url = f"{BASE_URL}/pokemon/{pokemon_name}"
    return await get_data_from_url(url)

async def get_pokemon_species_data(pokemon_name: str):
    """Busca dados do endpoint `pokemon-species/`."""
    url = f"{BASE_URL}/pokemon-species/{pokemon_name}"
    return await get_data_from_url(url)

async def get_evolution_chain_data(chain_url: str):
    """Busca dados do endpoint `evolution-chain/` a partir de uma URL completa."""
    return await get_data_from_url(chain_url)

async def get_total_xp_for_level(growth_rate_url: str, level: int) -> int | float:
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
    - HP: floor(((2 * base * level) / 100) + level + 10)
    - Outros: floor(((2 * base * level) / 100) + 5)
    """
    stats = {}
    for stat in base_stats:
        name = stat['stat']['name']
        base_value = stat['base_stat']
        if name == 'hp':
            db_col_name = 'max_hp'
            calculated_value = math.floor(((2 * base_value * level) / 100) + level + 10)
        else:
            db_col_name = name
            calculated_value = math.floor(((2 * base_value * level) / 100) + 5)
        stats[db_col_name] = calculated_value
    return stats

def get_initial_moves(pokemon_api_data: dict, starting_level: int) -> list:
    """
    Busca e retorna os 4 ataques mais recentes (por nível aprendido) que um Pokémon
    já poderia conhecer até `starting_level` via level-up.
    """
    candidates = []
    for move_info in pokemon_api_data.get('moves', []):
        move_name = move_info.get('move', {}).get('name')
        if not move_name:
            continue
        for vd in move_info.get('version_group_details', []):
            method = vd.get('move_learn_method', {}) or {}
            if method.get('name') == 'level-up':
                lvl = vd.get('level_learned_at', 0) or 0
                if 0 < lvl <= starting_level:
                    candidates.append((lvl, move_name))
                    break  # Considera a primeira entrada válida deste move

    # Ordena por nível aprendido (mais antigos primeiro, depois por nome p/ estabilidade)
    candidates.sort(key=lambda x: (x[0], x[1]))
    # Toma os 4 mais recentes por nível
    initial_moves = [name for _, name in candidates[-4:]]

    # Preenche com None até 4 elementos
    while len(initial_moves) < 4:
        initial_moves.append(None)
    return initial_moves

# ==========================================================
# ADICIONE TODAS ESTAS NOVAS FUNÇÕES ABAIXO NO SEU ARQUIVO
# ==========================================================
def _clean_flavor_text(text: str) -> str:
    """Limpa quebras de linha e caracteres especiais do flavor_text."""
    text = text.replace('\n', ' ').replace('\f', ' ').strip()
    text = re.sub(r'\s+', ' ', text)
    return text

async def get_pokemon_sprite_urls(pokemon_name: str) -> dict:
    """Retorna possíveis URLs de sprite para o Pokémon."""
    data = await get_pokemon_data(pokemon_name)
    if not data:
        return {}
    sprites = data.get('sprites', {}) or {}
    return {
        "front_default": sprites.get("front_default"),
        "official_artwork": sprites.get("other", {}).get("official-artwork", {}).get("front_default"),
    }

async def get_species_flavor_text_en(pokemon_name: str) -> str:
    """Retorna um flavor text em inglês (se disponível) da espécie."""
    data = await get_pokemon_species_data(pokemon_name)
    if not data:
        return "Description unavailable."
    for entry in data.get('flavor_text_entries', []):
        if entry['language']['name'] == 'en':
            return _clean_flavor_text(entry['flavor_text'])
    return "Descrição não disponível."

async def download_image_bytes(url: str) -> bytes | None:
    """Baixa uma imagem de uma URL e retorna os bytes."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.read()
    except Exception as e:
        print(f"Erro ao baixar imagem: {e}")
        return None
