# utils/event_utils.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
import json

# ==============================================================
#  🔒 GATES (regras para travas de acesso)
# ==============================================================

def _coerce_gate(gate_val: Any) -> Dict:
    """
    Converte o valor de 'gate' em dict.
    Aceita {}, string JSON, None, etc.
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
    return {}

def gate_allows(player: Any, gate: Optional[Dict]) -> bool:
    """
    Retorna True se o jogador atende às condições do gate.
    Suporta:
      - requires_badge
      - requires_flags
    """
    gate = _coerce_gate(gate)
    if not gate:
        return True

    # Requer um número mínimo de insígnias
    requires_badge = gate.get("requires_badge")
    if requires_badge is not None:
        badges = getattr(player, "badges", 0) or 0
        if isinstance(badges, (list, tuple, set)):
            badges = len(badges)
        if int(badges) < int(requires_badge):
            return False

    # Requer certas flags de história
    required_flags = gate.get("requires_flags")
    if required_flags:
        have = set(getattr(player, "flags", []) or [])
        need = set(required_flags or [])
        if not need.issubset(have):
            return False

    return True


# ==============================================================
#  🗺️ Consultas de local e rotas
# ==============================================================

def get_adjacent_routes(
    supabase,
    region: str,
    location_from: str,
    *,
    mainline_only: bool = False,
) -> List[Dict]:
    """
    Retorna todas as rotas conectadas a `location_from` na região dada.
    Compatível com Supabase Python síncrono.
    """
    try:
        q = (
            supabase.table("routes")
            .select("location_from,location_to,step,is_mainline,gate")
            .ilike("region", region)
            .ilike("location_from", location_from)
        )
        if mainline_only:
            q = q.eq("is_mainline", True)

        q = q.order("step").order("location_to")
        res = q.execute()
        return list(res.data or [])
    except Exception as e:
        print(f"[event_utils] Erro em get_adjacent_routes: {e}")
        return []


def get_next_mainline_edge(
    supabase,
    region: str,
    location_from: str
) -> Optional[Dict]:
    """
    Retorna a próxima rota principal a partir de `location_from`.
    """
    try:
        q = (
            supabase
            .table("routes")
            .select("location_from,location_to,step,gate")
            .eq("region", region)
            .eq("location_from", location_from)
            .eq("is_mainline", True)
            .order("step")
            .limit(1)
        )
        res = q.execute()
        rows = res.data or []
        return dict(rows[0]) if rows else None
    except Exception as e:
        print(f"[event_utils] Erro em get_next_mainline_edge: {e}")
        return None


def get_permitted_destinations(
    supabase,
    player: Any,
    region: str,
    location_from: str,
    *,
    mainline_only: bool = False,
) -> List[Dict]:
    """
    Filtra as rotas adjacentes por 'gate' e retorna destinos liberados.
    Retorna lista de dicts no formato:
        { "location_to": str, "step": int | None, "is_mainline": bool, "gate": dict }
    """
    edges = get_adjacent_routes(supabase, region, location_from, mainline_only=mainline_only)

    allowed: List[Dict] = []
    for e in edges:
        gate = _coerce_gate(e.get("gate"))
        if gate_allows(player, gate):
            allowed.append({
                "location_to": e["location_to"],
                "step": e.get("step"),
                "is_mainline": e.get("is_mainline", False),
                "gate": gate
            })

    # Ordena por passo (se existir), depois alfabético
    allowed.sort(key=lambda t: (t["step"] is None, t["step"] or 10**9, t["location_to"]))
    return allowed


def get_location_info(supabase, location_api_name: str) -> Optional[Dict]:
    """
    Retorna informações básicas de uma location.
    """
    try:
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
    except Exception as e:
        print(f"[event_utils] Erro em get_location_info: {e}")
        return None
