# utils/wild_utils.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Any, Dict, Optional, List
import random
import traceback
from supabase import Client

import utils.pokeapi_service as pokeapi
from utils import event_utils


# ----------------------------------------------------------------------
#  players.current_location_name -> locations.default_area
#  Usa a location atual do jogador para descobrir a location-area
# ----------------------------------------------------------------------
async def _get_player_location_area(
    supabase: Client,
    discord_id: int,
) -> Optional[str]:
    """
    Retorna o slug de `location_area` a partir da localização atual do jogador.

    players.current_location_name (ex.: 'viridian-city')
      -> event_utils.get_location_info(...)
         -> locations.default_area (ex.: 'viridian-city-area')
    """
    try:
        # Lê player do banco
        res = (
            supabase.table("players")
            .select("current_location_name,current_region")
            .eq("discord_id", discord_id)
            .limit(1)
            .execute()
        )
        rows: List[Dict[str, Any]] = res.data or []
        if not rows:
            print(f"[wild_utils:_get_player_location_area] no player row for {discord_id}", flush=True)
            return None

        player_row = rows[0]
        location_name = (player_row.get("current_location_name") or "").strip()
        region = (player_row.get("current_region") or "").strip()

        print(
            f"[wild_utils:_get_player_location_area] discord_id={discord_id} "
            f"location_name={location_name!r} region={region!r}",
            flush=True,
        )

        if not location_name:
            # Se não tiver spawn setado, força o spawn padrão da região
            spawn = event_utils.ensure_player_spawn(supabase, discord_id, region)
            print(f"[wild_utils:_get_player_location_area] ensured spawn={spawn!r}", flush=True)
            location_name = (spawn or "").strip()

        if not location_name:
            return None

        # Busca info da location na tabela "locations"
        info = event_utils.get_location_info(supabase, location_name)
        if not info:
            print(f"[wild_utils:_get_player_location_area] no location info for {location_name!r}", flush=True)
            return None

        default_area = (info.get("default_area") or "").strip()
        print(
            f"[wild_utils:_get_player_location_area] location={location_name!r} "
            f"default_area={default_area!r}",
            flush=True,
        )
        return default_area or None

    except Exception as e:
        print(f"[wild_utils:pick_wild_for_player][ERROR] {e}", flush=True)
        traceback.print_exc()
        raise  # <--- não volta Pidgey em silêncio, explode com stack trace



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
        "location_area": str | None,
        "source": "location-area" | "fallback",
        "raw_encounter": dict | None,
      }

    Regras de nível:
      - Usa min_level / max_level da área quando disponível
      - Caso contrário, varia em torno de ref_level (ref-5 .. ref+5)
    """
    rng = rng or random.Random()

    # Fallback absoluto (usado se der qualquer erro)
    fallback_level = max(1, min(ref_level, 100))
    fallback = {
        "pokemon_api_name": default_species.lower(),
        "level": fallback_level,
        "location_area": None,
        "source": "fallback",
        "raw_encounter": None,
    }

    try:
        location_area = await _get_player_location_area(supabase, discord_id)
        if not location_area:
            print("[wild_utils:pick_wild_for_player] no location_area → fallback", flush=True)
            return fallback

        # Consulta os encontros da location-area na PokeAPI
        print(
            f"[wild_utils:pick_wild_for_player] location_area={location_area!r} "
            f"version={version!r}",
            flush=True,
        )
        encounters = await pokeapi.get_location_area_encounters(location_area, version=version)
        if not encounters:
            print("[wild_utils:pick_wild_for_player] no encounters → fallback", flush=True)
            return fallback

        # ---------------------------------------
        # Sorteio ponderado pela chance
        # ---------------------------------------
        total_chance = sum(int(e.get("chance") or 0) for e in encounters)
        if total_chance <= 0:
            print("[wild_utils:pick_wild_for_player] total_chance<=0 → fallback", flush=True)
            return fallback

        roll = rng.randint(1, total_chance)
        acc = 0
        chosen: Optional[Dict[str, Any]] = None

        for e in encounters:
            c = int(e.get("chance") or 0)
            if c <= 0:
                continue
            acc += c
            if roll <= acc:
                chosen = e
                break

        if not chosen:
            chosen = rng.choice(encounters)

        # ---------------------------------------
        # Nível (respeita min/max da área)
        # ---------------------------------------
        min_lvl = int(chosen.get("min_level") or max(1, ref_level - 5))
        max_lvl = int(chosen.get("max_level") or max(min_lvl, ref_level + 5))

        # Clamp seguro
        min_lvl = max(1, min(min_lvl, 100))
        max_lvl = max(min_lvl, min(max_lvl, 100))

        level = rng.randint(min_lvl, max_lvl)
        name = (chosen.get("pokemon_name") or default_species).lower()

        print(
            f"[wild_utils:pick_wild_for_player] chosen={name!r} "
            f"lvl={level} (min={min_lvl}, max={max_lvl})",
            flush=True,
        )

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
