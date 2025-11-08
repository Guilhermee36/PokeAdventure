# event_utils.py
# Utilitários para eventos e navegação no mundo (locations/routes).
# Mantém a filosofia do seu projeto: adjacências por região e gates declarativos.
# Compatível com o Adventure/Travel atual.  :contentReference[oaicite:1]{index=1}

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


# ========== Helpers de formatação ==========

def safe_title(slug: str) -> str:
    """Converte 'viridian-city' -> 'Viridian City'."""
    return slug.replace("-", " ").title()


# ========== Gates (requisitos) ==========

def gate_allows(player: Any, gate: Optional[Dict]) -> bool:
    """
    Valida um gate de rota contra o estado do jogador.
    gate (jsonb): {"requires_badge": 2, "flag": "snorlax_cleared"} (campos opcionais)
    player: objeto com badges (int ou lista) e flags (lista de strings), se existirem.
    """
    if not gate or gate == {}:
        return True

    # Badges
    requires_badge = gate.get("requires_badge")
    if requires_badge is not None:
        player_badges = getattr(player, "badges", 0) or 0
        if isinstance(player_badges, (list, tuple, set)):
            player_badges = len(player_badges)
        if int(player_badges) < int(requires_badge):
            return False

    # Flags
    required_flag = gate.get("flag")
    if required_flag:
        flags = set(getattr(player, "flags", []) or [])
        if required_flag not in flags:
            return False

    return True


# ========== Consultas de rotas/adjacências ==========

async def get_adjacent_routes(
    db,
    region: str,
    location_from: str,
    *,
    mainline_only: bool = False,
) -> List[Dict]:
    """
    Lê as arestas saindo de `location_from` na `region`.
    Retorna dicionários com: location_from, location_to, step, is_mainline, gate.
    Ordena por step ASC (NULLS LAST) e por nome (estável para embed).
    """
    sql = """
        SELECT location_from, location_to, step, is_mainline, gate
        FROM public.routes
        WHERE region = %s
          AND location_from = %s
          AND (%s = FALSE OR is_mainline = TRUE)
        ORDER BY step NULLS LAST, location_to
    """
    rows = await db.fetch(sql, region, location_from, mainline_only)
    return [dict(r) for r in rows]


async def get_next_mainline_edge(db, region: str, location_from: str) -> Optional[Dict]:
    """
    Recupera a PRÓXIMA aresta da linha principal a partir do nó atual (se existir).
    Útil para destacar o próximo passo de história.
    """
    sql = """
        SELECT location_from, location_to, step, gate
        FROM public.routes
        WHERE region = %s
          AND is_mainline = TRUE
          AND location_from = %s
        ORDER BY step ASC
        LIMIT 1
    """
    row = await db.fetchrow(sql, region, location_from)
    return dict(row) if row else None


async def get_permitted_destinations(
    db,
    player: Any,
    region: str,
    location_from: str,
    *,
    mainline_only: bool = False,
) -> List[Tuple[str, Optional[int]]]:
    """
    Lista de destinos permitidos (filtrada por gates), como (location_to, step).
    Ordena com passos de história primeiro (step ASC), depois restantes por nome.
    """
    edges = await get_adjacent_routes(db, region, location_from, mainline_only=mainline_only)
    allowed: List[Tuple[str, Optional[int]]] = []
    for e in edges:
        gate = e.get("gate") or {}
        if gate_allows(player, gate):
            allowed.append((e["location_to"], e.get("step")))
    allowed.sort(key=lambda t: (t[1] is None, t[1] or 10**9, t[0]))
    return allowed


# ========== (Opcional) possíveis eventos por tipo de local ==========

async def get_location_info(db, location_api_name: str) -> Optional[Dict]:
    """
    Busca info básica da location (para decidir eventos, flavor, etc).
    """
    sql = """
        SELECT location_api_name, name, type, region, has_gym, has_shop, default_area
        FROM public.locations
        WHERE location_api_name = %s
    """
    row = await db.fetchrow(sql, location_api_name)
    return dict(row) if row else None


def get_possible_events(location_type: str, has_gym: bool) -> List[str]:
    """
    Placeholder compatível com sua lógica de eventos:
    - em 'city': shop/centro/gym (se tiver)
    - em 'route'/'dungeon': encontros selvagens, trainers, coleta
    (Ajuste conforme seu design atual; mantido simples aqui.)  :contentReference[oaicite:2]{index=2}
    """
    if location_type == "city":
        events = ["heal", "shop"]
        if has_gym:
            events.append("gym")
        return events
    return ["wild", "trainer", "loot"]
