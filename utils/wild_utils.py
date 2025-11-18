# utils/wild_utils.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Any, Dict, Optional, List
import random

from supabase import Client

import utils.pokeapi_service as pokeapi
from utils import event_utils


async def _get_player_location_area(
    supabase: Client,
    discord_id: int,
) -> Optional[str]:
    """
    Descobre a location-area da PokeAPI com base na localização atual do jogador.

    players.current_location_name -> locations.default_area
    """
    try:
        res = (
            supabase.table("players")
            .select("current_location_name")
            .eq("discord_id", discord_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return None

        loc_slug = (rows[0].get("current_location_name") or "").strip()
        if not loc_slug:
            return None

        loc_info = event_utils.get_location_info(supabase, loc_slug)
        if not loc_info:
            return None

        default_area = (loc_info.get("default_area") or "").strip()
        return default_area or None
    except Exception as e:
        print(f"[wild_utils:_get_player_location_area][ERROR] {e}", flush=True)
        return None


async def pick_wild_for_player(
    supabase: Client,
    *,
    discord_id: int,
    ref_level: int,
    rng: Optional[random.Random] = None,
    default_species: str = "pidgey",
    version: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Decide qual Pokémon selvagem aparece para o jogador.

    Retorna um dict:
      {
        "pokemon_api_name": str,
        "level": int,
        "location_area": Optional[str],
        "source": str,              # "location-area" | "default"
        "raw_encounter": Optional[dict],
      }

    - Usa players.current_location_name -> locations.default_area.
    - Busca encontros na PokeAPI para essa location-area.
    - Faz sorteio ponderado por `chance`.
    - Level é sorteado entre min/max da área, com clamp +/- da ref_level.
    """
    rng = rng or random.Random()
    ref_level = max(1, int(ref_level or 1))

    # Fallback padrão
    fallback = {
        "pokemon_api_name": default_species.lower(),
        "level": ref_level,
        "location_area": None,
        "source": "default",
        "raw_encounter": None,
    }

    try:
        location_area = await _get_player_location_area(supabase, discord_id)
        if not location_area:
            return fallback

        encounters = await pokeapi.get_location_area_encounters(location_area, version=version)
        if not encounters:
            return {**fallback, "location_area": location_area}

        # Sorteio ponderado por chance
        weights = [max(1, int(e.get("chance") or 1)) for e in encounters]
        chosen = rng.choices(encounters, weights=weights, k=1)[0]

        min_lvl = int(chosen.get("min_level") or 1)
        max_lvl = int(chosen.get("max_level") or min_lvl)

        # Clamp de nível para não aparecer algo MUITO fora da curva
        # Ex: min: 2, max: 40, seu mon é 10 → clamp em até ref_level + 5
        max_lvl = max(min_lvl, min(max_lvl, ref_level + 5))

        level = rng.randint(min_lvl, max_lvl)
        name = (chosen.get("pokemon_name") or default_species).lower()

        return {
            "pokemon_api_name": name,
            "level": level,
            "location_area": location_area,
            "source": "location-area",
            "raw_encounter": chosen,
        }
    except Exception as e:
        print(f"[wild_utils:pick_wild_for_player][ERROR] {e}", flush=True)
        return fallback
