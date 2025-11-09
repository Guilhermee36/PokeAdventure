# utils/event_utils.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

# ------------- Gates -------------

def gate_allows(player: Any, gate: Optional[Dict]) -> bool:
    if not gate:
        return True
    requires_badge = gate.get("requires_badge")
    if requires_badge is not None:
        badges = getattr(player, "badges", 0) or 0
        if isinstance(badges, (list, tuple, set)):
            badges = len(badges)
        if int(badges) < int(requires_badge):
            return False
    required_flag = gate.get("flag")
    if required_flag:
        flags = set(getattr(player, "flags", []) or [])
        if required_flag not in flags:
            return False
    return True

# ------------- Consultas (Supabase) -------------

async def get_adjacent_routes(
    supabase,
    region: str,
    location_from: str,
    *,
    mainline_only: bool = False,
) -> List[Dict]:
    q = (
        supabase
        .table("routes")
        .select("location_from,location_to,step,is_mainline,gate")
        .eq("region", region)
        .eq("location_from", location_from)
    )
    if mainline_only:
        q = q.eq("is_mainline", True)
    # Ordenações: step (NULLS LAST) e depois location_to
    q = q.order("step", nullsfirst=False).order("location_to", nullsfirst=True)
    res = q.execute()
    return list(res.data or [])

async def get_next_mainline_edge(supabase, region: str, location_from: str) -> Optional[Dict]:
    q = (
        supabase
        .table("routes")
        .select("location_from,location_to,step,gate")
        .eq("region", region)
        .eq("location_from", location_from)
        .eq("is_mainline", True)
        .order("step", nullsfirst=False)
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
    edges = await get_adjacent_routes(supabase, region, location_from, mainline_only=mainline_only)
    allowed: List[Tuple[str, Optional[int]]] = []
    for e in edges:
        gate = e.get("gate") or {}
        if gate_allows(player, gate):
            allowed.append((e["location_to"], e.get("step")))
    # ordena: com step primeiro, depois alfa
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
