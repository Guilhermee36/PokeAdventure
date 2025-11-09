# utils/event_utils.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
import json

# ------------- Gates -------------

def _coerce_gate(gate_val: Any) -> Dict:
    """
    Converte o valor de 'gate' para dict:
    - {} -> {}
    - '{"requires_badge": 3}' -> {"requires_badge": 3}
    - None / "" -> {}
    - Qualquer outra coisa inválida -> {}
    """
    if not gate_val:
        return {}
    if isinstance(gate_val, dict):
        return gate_val
    if isinstance(gate_val, str):
        s = gate_val.strip()
        if not s or s == "{}":
            return {}
        try:
            parsed = json.loads(s)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    # tipos inesperados
    return {}

def gate_allows(player: Any, gate: Optional[Dict]) -> bool:
    gate = _coerce_gate(gate)
    if not gate:
        return True

    requires_badge = gate.get("requires_badge")
    if requires_badge is not None:
        badges = getattr(player, "badges", 0) or 0
        if isinstance(badges, (list, tuple, set)):
            badges = len(badges)
        if int(badges) < int(requires_badge):
            return False

    required_flags = gate.get("requires_flags")
    if required_flags:
        have = set(getattr(player, "flags", []) or [])
        need = set(required_flags or [])
        if not need.issubset(have):
            return False

    # adicione outras regras de gate aqui (itens, story_flags, etc.)
    return True

# ------------- Consultas -------------

async def get_adjacent_routes(
    supabase,
    region: str,
    location_from: str,
    *,
    mainline_only: bool = False,
) -> List[Dict]:
    """
    Busca as arestas a partir de `location_from` na região dada.
    """
    q = (
        supabase
        .table("routes")
        .select("location_from,location_to,step,is_mainline,gate")
        .eq("region", region)
        .eq("location_from", location_from)
    )
    if mainline_only:
        q = q.eq("is_mainline", True)

    # Compat: sem 'nullsfirst', que pode não ser aceito por alguns clients.
    q = q.order("step").order("location_to")

    res = q.execute()
    return list(res.data or [])

async def get_next_mainline_edge(
    supabase,
    region: str,
    location_from: str
) -> Optional[Dict]:
    """
    Próxima aresta da linha principal a partir de `location_from`.
    """
    q = (
        supabase
        .table("routes")
        .select("location_from,location_to,step,gate")
        .eq("region", region)
        .eq("location_from", location_from)
        .eq("is_mainline", True)
        .order("step")     # sem nullsfirst
        .limit(1)
    )
    res = q.execute()
    rows = res.data or []
    return dict(rows[0]) if rows else None

async def get_permitted_destinations(
    supabase,
    player: Any,
    region: str,
    location_from: str,
    *,
    mainline_only: bool = False,
) -> List[Tuple[str, Optional[int]]]:
    """
    Filtra as arestas adjacentes por 'gate' e devolve (location_to, step).
    """
    edges = await get_adjacent_routes(
        supabase, region, location_from, mainline_only=mainline_only
    )

    allowed: List[Tuple[str, Optional[int]]] = []
    for e in edges:
        gate = _coerce_gate(e.get("gate"))
        if gate_allows(player, gate):
            allowed.append((e["location_to"], e.get("step")))

    # Ordena: com passo definido primeiro (crescente), depois alfabético.
    allowed.sort(key=lambda t: (t[1] is None, t[1] or 10**9, t[0]))
    return allowed

async def get_location_info(supabase, location_api_name: str) -> Optional[Dict]:
    res = (
        supabase
        .table("locations")
        .select("location_api_name,name,type,region,has_gym,has_shop,default_area")
        .eq("location_api_name", location_api_name)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return dict(rows[0]) if rows else None
