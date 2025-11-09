# utils/event_utils.py
# -*- coding: utf-8 -*-

from __future__ import annotations
from typing import Any, Dict, List, Optional

"""
Utilitários de eventos/rotas apoiados em Supabase.

Assume as tabelas:

- routes(region, location_from, location_to, step, is_mainline, gate)
- locations(region, location_api_name, type, has_gym, has_shop)

Ajustes importantes:
- Removemos o uso de `nullsfirst=` nas chamadas .order(...) por compatibilidade.
- Funções protegem contra erros e retornam listas vazias quando apropriado.
"""

# ------------- helpers -------------

def _table(client: Any, name: str):
    # `client` aqui é o supabase.create_client(...)
    return client.table(name)

# ------------- consultas -------------

async def get_adjacent_routes(
    client: Any,
    *,
    region: str,
    location_from: str,
    mainline_only: bool = False,
) -> List[Dict]:
    """
    Rotas que saem de `location_from`.
    """
    q = (
        _table(client, "routes")
        .select("region,location_from,location_to,step,is_mainline,gate")
        .eq("region", region)
        .eq("location_from", location_from)
    )
    if mainline_only:
        q = q.eq("is_mainline", True)

    # Compat: não usamos nullsfirst / nullslast aqui.
    q = q.order("step").order("location_to")

    data = await q.execute()
    rows = getattr(data, "data", data)
    return rows or []

async def get_location_info(
    client: Any,
    *,
    region: str,
    location_api_name: str,
) -> Optional[Dict]:
    q = (
        _table(client, "locations")
        .select("region,location_api_name,type,has_gym,has_shop")
        .eq("region", region)
        .eq("location_api_name", location_api_name)
        .limit(1)
    )
    data = await q.execute()
    rows = getattr(data, "data", data) or []
    return rows[0] if rows else None

async def get_permitted_destinations(
    client: Any,
    *,
    region: str,
    location_from: str,
    player: Any,
    mainline_only: bool = False,
) -> List[Dict]:
    """
    Retorna as rotas adjacentes permitidas a partir de `location_from`.
    Aqui você pode aplicar gates/badges com base no `player`.
    Por enquanto, apenas retorna as adjacentes; ajuste as regras conforme seu jogo.
    """
    routes = await get_adjacent_routes(
        client,
        region=region,
        location_from=location_from,
        mainline_only=mainline_only,
    )

    # Exemplo de filtro por gate (se gate existe, e o jogador não tem, bloqueia)
    def _allowed(route: Dict) -> bool:
        gate = route.get("gate")
        if not gate:
            return True
        # adapte conforme seu modelo de player (badges, flags, etc.)
        player_gates = set(getattr(player, "gates", []) or [])
        return gate in player_gates

    permitted = [r for r in routes if _allowed(r)]
    return permitted
