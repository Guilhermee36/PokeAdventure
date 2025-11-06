# utils/event_utils.py

from supabase import Client
import json

async def _check_team_fainted(supabase: Client, player_id: int) -> bool:
    """Verifica se todos os Pokémon na party do jogador estão desmaiados."""
    try:
        # Busca apenas os HPs da party (posições 1-6)
        res = supabase.table("player_pokemon") \
            .select("current_hp") \
            .eq("player_id", player_id) \
            .filter("party_position", "not.is", "null") \
            .execute()
        
        if not res.data:
            return True # Sem time? Considera "desmaiado"

        # Se todos os HPs forem 0 ou menos, retorne True
        return all(p['current_hp'] <= 0 for p in res.data)
        
    except Exception as e:
        print(f"Erro ao checar time desmaiado: {e}")
        return False # Assume que não está desmaiado se houver erro

async def get_possible_events(supabase: Client, player_data: dict) -> list[str]:
    """
    Verifica a localização atual e o estado do jogador para retornar
    uma lista de eventos (ações) possíveis.
    """
    
    try:
        player_id = player_data['discord_id']
        location_name = player_data['current_location_name']
        badges = player_data.get('badges', 0)
    except KeyError:
        return [] # player_data incompleto

    # Regra 3 (Contexto): Time desmaiado
    if await _check_team_fainted(supabase, player_id):
        # Se o time estiver desmaiado, a única opção é ir ao Centro Pokémon.
        # (A lógica do 'adventure_cog' deve forçar isso)
        return ['pokemon_center']

    # Busca os dados da localização atual
    try:
        loc_res = supabase.table("locations") \
            .select("*") \
            .eq("location_api_name", location_name) \
            .single() \
            .execute()
        
        if not loc_res.data:
            return [] # Localização não existe no DB
        
        loc = loc_res.data
    except Exception as e:
        print(f"Erro ao buscar localização: {e}")
        return []

    events = []

    # Regra 1 (Cidade)
    if loc['type'] == 'city':
        events.append('talk_npc') # Sempre pode tentar falar com NPCs
        events.append('pokemon_center') # Toda cidade tem um (implícito)

        if loc.get('has_shop', False):
            events.append('shop')

        if loc.get('has_gym', False):
            req_badges = loc.get('gym_badge_required', 0)
            if badges >= req_badges:
                events.append('challenge_gym')

        # Cidades sempre permitem viajar
        events.append('move_to_route')

    # Regra 2 (Rota)
    elif loc['type'] == 'route':
        events.append('wild_encounter')
        events.append('find_item')
        
        # TODO: Implementar Regra 3 (trainer_battle)
        # Isso exigirá consultar npcs(location_api_name) e player_defeated_npcs
        # events.append('trainer_battle') 
        
        # Rotas sempre permitem viajar
        events.append('move_to_location')

    return events