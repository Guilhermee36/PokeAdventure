# utils/event_utils.py

from supabase import Client

# ============================================================
# Helpers de estado do time / eventos possíveis por localização
# ============================================================

async def _check_team_fainted(supabase: Client, player_id: int) -> bool:
    """Verifica se todos os Pokémon na party do jogador estão desmaiados."""
    try:
        res = (
            supabase.table("player_pokemon")
            .select("current_hp")
            .eq("player_id", player_id)
            .filter("party_position", "not.is", "null")
            .execute()
        )

        if not res.data:
            # Sem time? Trate como 'sem condições de batalha'
            return True

        return all(p["current_hp"] <= 0 for p in res.data)

    except Exception as e:
        print(f"[event_utils] Erro ao checar time desmaiado: {e}")
        # Em caso de erro, seja permissivo
        return False


async def get_possible_events(supabase: Client, player_data: dict) -> list[str]:
    """
    Devolve a lista de eventos possíveis no local atual, considerando o estado do jogador.
    """
    try:
        player_id = player_data["discord_id"]
        location_name = player_data["current_location_name"]
        badges = player_data.get("badges", 0)
    except KeyError:
        return []

    # Regra: se o time estiver desmaiado, só Centro Pokémon
    if await _check_team_fainted(supabase, player_id):
        return ["pokemon_center"]

    # Carrega dados do local atual
    try:
        loc_res = (
            supabase.table("locations")
            .select("*")
            .eq("location_api_name", location_name)
            .single()
            .execute()
        )
        if not loc_res.data:
            return []
        loc = loc_res.data
    except Exception as e:
        print(f"[event_utils] Erro ao buscar localização: {e}")
        return []

    events: list[str] = []

    if loc["type"] == "city":
        events += ["talk_npc", "pokemon_center"]
        if loc.get("has_shop", False):
            events.append("shop")
        if loc.get("has_gym", False):
            req_badges = loc.get("gym_badge_required", 0)
            if badges >= req_badges:
                events.append("challenge_gym")
        # cidades permitem viagem
        events.append("move_to_route")

    elif loc["type"] == "route":
        events += ["wild_encounter", "find_item"]
        # rotas permitem viagem
        events.append("move_to_location")

    return events


# ============================================================
# NOVO: Vizinhança/viagem restrita à MESMA região do jogador
# ============================================================

async def get_adjacent_locations_in_region(
    supabase: Client, from_location_api_name: str, region: str
) -> list[dict]:
    """
    Retorna as locations alcançáveis a partir de `from_location_api_name`,
    **restritas** à mesma `region`. Evita teleporte cross-region quando
    há nomes repetidos (ex.: 'route-1' em várias regiões).
    """
    try:
        # 1) rotas que partem do local atual
        routes_res = (
            supabase.table("routes")
            .select("location_to")
            .eq("location_from", from_location_api_name)
            .execute()
        )
        to_names = [r["location_to"] for r in (routes_res.data or [])]
        if not to_names:
            return []

        # 2) filtra destino por 'locations.region'
        locs_res = (
            supabase.table("locations")
            .select("location_api_name, name_pt, name, type, region, has_gym, has_shop")
            .in_("location_api_name", to_names)
            .eq("region", region)
            .execute()
        )
        return locs_res.data or []

    except Exception as e:
        print(f"[event_utils] erro ao montar adjacências por região: {e}")
        return []
