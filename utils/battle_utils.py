# utils/battle_utils.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Tuple, Optional, Dict
import math
import random

# Tipagem simplificada (chart fixo) — multiplicadores de efetividade
# Ex.: TYPE_CHART[atk_type][def_type] -> mult
TYPE_CHART: Dict[str, Dict[str, float]] = {
    "normal":  {"rock": 0.5, "ghost": 0.0, "steel": 0.5},
    "fire":    {"fire": 0.5, "water": 0.5, "grass": 2.0, "ice": 2.0, "bug": 2.0, "rock": 0.5, "dragon": 0.5, "steel": 2.0},
    "water":   {"fire": 2.0, "water": 0.5, "grass": 0.5, "ground": 2.0, "rock": 2.0, "dragon": 0.5},
    "electric":{"water": 2.0, "electric": 0.5, "grass": 0.5, "ground": 0.0, "flying": 2.0, "dragon": 0.5},
    "grass":   {"fire": 0.5, "water": 2.0, "grass": 0.5, "poison": 0.5, "ground": 2.0, "flying": 0.5, "bug": 0.5, "rock": 2.0, "dragon": 0.5, "steel": 0.5},
    "ice":     {"fire": 0.5, "water": 0.5, "grass": 2.0, "ice": 0.5, "ground": 2.0, "flying": 2.0, "dragon": 2.0, "steel": 0.5},
    "fighting":{"normal": 2.0, "ice": 2.0, "poison": 0.5, "flying": 0.5, "psychic": 0.5, "bug": 0.5, "rock": 2.0, "ghost": 0.0, "dark": 2.0, "steel": 2.0, "fairy": 0.5},
    "poison":  {"grass": 2.0, "poison": 0.5, "ground": 0.5, "rock": 0.5, "ghost": 0.5, "steel": 0.0, "fairy": 2.0},
    "ground":  {"fire": 2.0, "electric": 2.0, "grass": 0.5, "poison": 2.0, "flying": 0.0, "bug": 0.5, "rock": 2.0, "steel": 2.0},
    "flying":  {"electric": 0.5, "grass": 2.0, "fighting": 2.0, "bug": 2.0, "rock": 0.5, "steel": 0.5},
    "psychic": {"fighting": 2.0, "poison": 2.0, "psychic": 0.5, "dark": 0.0, "steel": 0.5},
    "bug":     {"fire": 0.5, "grass": 2.0, "fighting": 0.5, "poison": 0.5, "flying": 0.5, "psychic": 2.0, "ghost": 0.5, "dark": 2.0, "steel": 0.5, "fairy": 0.5},
    "rock":    {"fire": 2.0, "ice": 2.0, "fighting": 0.5, "ground": 0.5, "flying": 2.0, "bug": 2.0, "steel": 0.5},
    "ghost":   {"normal": 0.0, "psychic": 2.0, "dark": 0.5},
    "dragon":  {"dragon": 2.0, "steel": 0.5, "fairy": 0.0},
    "dark":    {"fighting": 0.5, "psychic": 2.0, "ghost": 2.0, "dark": 0.5, "fairy": 0.5},
    "steel":   {"fire": 0.5, "water": 0.5, "electric": 0.5, "ice": 2.0, "rock": 2.0, "fairy": 2.0, "steel": 0.5},
    "fairy":   {"fire": 0.5, "fighting": 2.0, "poison": 0.5, "dragon": 2.0, "dark": 2.0, "steel": 0.5},
}

def get_type_multiplier(move_type: str, defender_types: List[str]) -> float:
    move_type = (move_type or "").lower()
    mult = 1.0
    for t in defender_types or []:
        t = (t or "").lower()
        mult *= TYPE_CHART.get(move_type, {}).get(t, 1.0)
    return mult

def get_stab_multiplier(attacker_types: List[str], move_type: str) -> float:
    if not attacker_types or not move_type:
        return 1.0
    return 1.5 if move_type.lower() in [t.lower() for t in attacker_types] else 1.0

def describe_effectiveness(mult: float) -> Optional[str]:
    if mult == 0:
        return "Não afeta o oponente!"
    if mult >= 2.0:
        return "É super efetivo!"
    if 0 < mult < 1.0:
        return "Não é muito efetivo…"
    return None

def calc_damage(
    level: int,
    power: int,
    atk: int,
    deff: int,
    move_type: str,
    attacker_types: List[str],
    defender_types: List[str],
    rng: random.Random,
) -> Tuple[int, float, bool]:
    """Retorna (dano, efetividade, stab_aplicado)"""
    if power <= 0:
        return 0, 1.0, False
    base = math.floor((((2 * level) / 5) + 2) * power * (atk / max(1, deff)) / 50) + 2
    eff = get_type_multiplier(move_type, defender_types)
    if eff == 0:
        return 0, 0.0, False
    stab = get_stab_multiplier(attacker_types, move_type)
    rand_factor = rng.uniform(0.85, 1.0)
    dmg = max(1, math.floor(base * eff * stab * rand_factor))
    return dmg, eff, (stab > 1.0)

# --------- Captura ---------

def capture_chance(
    base_capture_rate: int,
    wild_max_hp: int,
    wild_current_hp: int,
    ball_mult: float = 1.0,
    status_mult: float = 1.0,
) -> float:
    """Aproximação simples e divertida (0..1)."""
    if wild_max_hp <= 0:
        return 1.0
    hp_factor = ((3 * wild_max_hp) - (2 * max(0, wild_current_hp))) / (3 * wild_max_hp)
    hp_factor = max(0.01, min(1.0, hp_factor))
    base = base_capture_rate / 255.0
    chance = base * ball_mult * status_mult * hp_factor
    return max(0.01, min(0.95, chance))

def attempt_capture(rng: random.Random, chance: float) -> bool:
    return rng.random() < max(0.0, min(1.0, chance))

# --------- HP bar textual ---------

def hp_bar(current: int, maximum: int, width_blocks: int = 10) -> Tuple[str, str]:
    if maximum <= 0:
        return "HP: [??????????] 0/0", "🟥"
    ratio = max(0.0, min(1.0, current / maximum))
    filled = int(round(ratio * width_blocks))
    bar = "█" * filled + "░" * (width_blocks - filled)
    color = "🟩" if ratio > 0.5 else ("🟨" if ratio > 0.2 else "🟥")
    return f"HP: {color} [{bar}] {current}/{maximum}", color
