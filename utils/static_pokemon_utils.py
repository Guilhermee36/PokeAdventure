# utils/static_pokemon_utils.py
# -*- coding: utf-8 -*-

"""
Módulo de dados estáticos de Pokémon.

Aqui ficam:
  - Pools para o Black Shop (cassino & compra aleatória)
  - Pools para eventos futuros (Halloween, Natal, etc.)

Tudo aqui é "hardcoded" / estático, para não depender de API externa
e ser fácil de editar.
"""

from enum import Enum
from typing import Dict, List, TypedDict, Optional


class Rarity(str, Enum):
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    MYTHICAL = "mythical"


class StaticPokemon(TypedDict):
    id: int           # pokedex id oficial
    name: str         # nome em inglês (ou como você preferir)
    region: Optional[int]  # identificador numérico da região (ex: 1 = Kanto)


# -------------------------------------------------------------------
# Helpers genéricos
# -------------------------------------------------------------------

def get_sprite_url(pokedex_id: int) -> str:
    """
    Retorna uma URL de sprite estática (PokeAPI sprites 2D front).
    Pode ser trocado depois por outro repositório se você quiser.
    """
    return (
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
        f"sprites/pokemon/{pokedex_id}.png"
    )


# -------------------------------------------------------------------
# BLACK SHOP – caça-níquel (slots)
# -------------------------------------------------------------------

#: Pools por raridade para o caça-níquel clandestino
#: region = 1 por enquanto (Kanto, por exemplo) — você ajusta depois.
BLACK_SLOTS_POOLS: Dict[Rarity, List[StaticPokemon]] = {
    Rarity.COMMON: [
        {"id": 10, "name": "Caterpie", "region": 1},
        {"id": 13, "name": "Weedle", "region": 1},
        {"id": 16, "name": "Pidgey", "region": 1},
        {"id": 19, "name": "Rattata", "region": 1},
        {"id": 21, "name": "Spearow", "region": 1},
        {"id": 23, "name": "Ekans", "region": 1},
    ],
    Rarity.UNCOMMON: [
        {"id": 25, "name": "Pikachu", "region": 1},
        {"id": 27, "name": "Sandshrew", "region": 1},
        {"id": 29, "name": "Nidoran♀", "region": 1},
        {"id": 32, "name": "Nidoran♂", "region": 1},
        {"id": 37, "name": "Vulpix", "region": 1},
        {"id": 41, "name": "Zubat", "region": 1},
    ],
    Rarity.RARE: [
        {"id": 58, "name": "Growlithe", "region": 1},
        {"id": 63, "name": "Abra", "region": 1},
        {"id": 66, "name": "Machop", "region": 1},
        {"id": 74, "name": "Geodude", "region": 1},
        {"id": 86, "name": "Seel", "region": 1},
        {"id": 90, "name": "Shellder", "region": 1},
    ],
    Rarity.MYTHICAL: [
        {"id": 151, "name": "Mew", "region": 1},
        {"id": 251, "name": "Celebi", "region": 1},
        {"id": 385, "name": "Jirachi", "region": 1},
        {"id": 490, "name": "Manaphy", "region": 1},
        {"id": 492, "name": "Shaymin", "region": 1},
        {"id": 649, "name": "Genesect", "region": 1},
    ],
}


def get_black_slots_pool(rarity: str | Rarity) -> List[StaticPokemon]:
    """Retorna a lista de pokémons para a raridade do caça-níquel."""
    if isinstance(rarity, str):
        try:
            rarity_enum = Rarity(rarity)
        except ValueError:
            return []
    else:
        rarity_enum = rarity

    return BLACK_SLOTS_POOLS.get(rarity_enum, [])


# -------------------------------------------------------------------
# BLACK SHOP – compra de pokémons aleatórios
# -------------------------------------------------------------------

#: Pool de primeiros estágios NÃO lendários / NÃO míticos
#: usado pelo comando de compra clandestina (blackbuy)
#: region = 1 por enquanto.
BLACK_SHOP_BASIC_POOL: List[StaticPokemon] = [
    {"id": 1, "name": "Bulbasaur", "region": 1},
    {"id": 4, "name": "Charmander", "region": 1},
    {"id": 7, "name": "Squirtle", "region": 1},
    {"id": 10, "name": "Caterpie", "region": 1},
    {"id": 13, "name": "Weedle", "region": 1},
    {"id": 16, "name": "Pidgey", "region": 1},
    {"id": 19, "name": "Rattata", "region": 1},
    {"id": 25, "name": "Pikachu", "region": 1},
    {"id": 27, "name": "Sandshrew", "region": 1},
    {"id": 35, "name": "Clefairy", "region": 1},
    {"id": 39, "name": "Jigglypuff", "region": 1},
    {"id": 52, "name": "Meowth", "region": 1},
    {"id": 54, "name": "Psyduck", "region": 1},
    {"id": 60, "name": "Poliwag", "region": 1},
    {"id": 63, "name": "Abra", "region": 1},
    {"id": 66, "name": "Machop", "region": 1},
    {"id": 69, "name": "Bellsprout", "region": 1},
    {"id": 72, "name": "Tentacool", "region": 1},
    {"id": 74, "name": "Geodude", "region": 1},
    {"id": 79, "name": "Slowpoke", "region": 1},
]


def get_black_shop_basic_pool() -> List[StaticPokemon]:
    """Retorna a lista de pokémons básicos usados na compra clandestina."""
    return BLACK_SHOP_BASIC_POOL


# -------------------------------------------------------------------
# EVENTOS FUTUROS (exemplos/esqueleto)
# -------------------------------------------------------------------

HALLOWEEN_EVENT_POKEMON: List[StaticPokemon] = [
    {"id": 92, "name": "Gastly", "region": 1},
    {"id": 200, "name": "Misdreavus", "region": 1},
    {"id": 355, "name": "Duskull", "region": 1},
]

CHRISTMAS_EVENT_POKEMON: List[StaticPokemon] = [
    {"id": 225, "name": "Delibird", "region": 1},
    {"id": 361, "name": "Snorunt", "region": 1},
]

EVENT_POOLS: Dict[str, List[StaticPokemon]] = {
    "halloween": HALLOWEEN_EVENT_POKEMON,
    "christmas": CHRISTMAS_EVENT_POKEMON,
}


def get_event_pool(event_key: str) -> List[StaticPokemon]:
    """Retorna a lista estática associada à chave de evento, se existir."""
    return EVENT_POOLS.get(event_key, [])
