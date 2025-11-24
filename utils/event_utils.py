from __future__ import annotations
from typing import Any, Dict, List, Optional
import json
import traceback

# ==============================================================
#  🌍 SPAWNS por região
# ==============================================================

START_SPAWNS: Dict[str, str] = {
    "Kanto":  "pallet-town",
    "Johto":  "new-bark-town",
    "Hoenn":  "littleroot-town",
    "Sinnoh": "twinleaf-town",
    "Unova":  "nuvema-town",
    "Kalos":  "vaniville-town",
    "Alola":  "iki-town",
    "Galar":  "postwick",
    "Paldea": "cabo-poco",
}

def get_region_spawn(region: str) -> str:
    """Slug de spawn padrão para a região."""
    return START_SPAWNS.get((region or "").strip(), "pallet-town")


def ensure_player_spawn(supabase: Any, discord_id: int, region: Optional[str]) -> Optional[str]:
    """
    Se o jogador não tiver current_location_name, seta o spawn padrão da região.
    Retorna o location aplicado (ou None se não alterou).
    """
    if not region:
        return None
    try:
        spawn = get_region_spawn(region)
        (
            supabase.table("players")
            .update({"current_location_name": spawn})
            .eq("discord_id", discord_id)
            .execute()
        )
        return spawn
    except Exception as e:
        print(f"[ensure_player_spawn][ERROR] {e}", flush=True)
        return None


# ==============================================================
#  🔒 GATES (regras para travas de acesso)
# ==============================================================

def _coerce_gate(gate_val: Any) -> Dict:
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
    gate = _coerce_gate(gate)
    if not gate:
        return True

    # 1) badges
    requires_badge = gate.get("requires_badge")
    if requires_badge is not None:
        badges = getattr(player, "badges", 0) or 0
        if isinstance(badges, (list, tuple, set)):
            badges = len(badges)
        if int(badges) < int(requires_badge):
            return False

    # 2) flags obrigatórias
    required_flags = gate.get("requires_flags")
    if required_flags:
        have = set(getattr(player, "flags", []) or [])
        need = set(required_flags or [])
        if not need.issubset(have):
            return False

    # 3) locked_until: exige possuir a flag X para liberar
    locked_until = gate.get("locked_until")
    if locked_until:
        have = set(getattr(player, "flags", []) or [])
        if locked_until not in have:
            return False

    # 4) blocked_by: bloqueia enquanto NÃO houver "clear_<blocked_by>"
    #    ex.: blocked_by: "snorlax" → requer flag "clear_snorlax"
    blocked_by = gate.get("blocked_by")
    if blocked_by:
        have = set(getattr(player, "flags", []) or [])
        clear_flag = f"clear_{str(blocked_by).strip()}"
        if clear_flag not in have:
            return False

    # 5) "recommended" não bloqueia
    return True



# ==============================================================
#  🧭 ORDENS DE GINÁSIOS (todas as regiões)
# ==============================================================

GYM_ORDERS: Dict[str, List[Dict[str, object]]] = {
    "Kanto": [
        {"city": "pewter-city",    "leader": "Brock",      "badge_no": 1, "badge_name": "Boulder Badge"},
        {"city": "cerulean-city",  "leader": "Misty",      "badge_no": 2, "badge_name": "Cascade Badge"},
        {"city": "vermilion-city", "leader": "Lt. Surge",  "badge_no": 3, "badge_name": "Thunder Badge"},
        {"city": "celadon-city",   "leader": "Erika",      "badge_no": 4, "badge_name": "Rainbow Badge"},
        {"city": "fuchsia-city",   "leader": "Koga",       "badge_no": 5, "badge_name": "Soul Badge"},
        {"city": "saffron-city",   "leader": "Sabrina",    "badge_no": 6, "badge_name": "Marsh Badge"},
        {"city": "cinnabar-island","leader": "Blaine",     "badge_no": 7, "badge_name": "Volcano Badge"},
        {"city": "viridian-city",  "leader": "Giovanni",   "badge_no": 8, "badge_name": "Earth Badge"},
    ],
    "Johto": [
        {"city": "violet-city",    "leader": "Falkner",    "badge_no": 1, "badge_name": "Zephyr Badge"},
        {"city": "azalea-town",    "leader": "Bugsy",      "badge_no": 2, "badge_name": "Hive Badge"},
        {"city": "goldenrod-city", "leader": "Whitney",    "badge_no": 3, "badge_name": "Plain Badge"},
        {"city": "ecruteak-city",  "leader": "Morty",      "badge_no": 4, "badge_name": "Fog Badge"},
        {"city": "cianwood-city",  "leader": "Chuck",      "badge_no": 5, "badge_name": "Storm Badge"},
        {"city": "olivine-city",   "leader": "Jasmine",    "badge_no": 6, "badge_name": "Mineral Badge"},
        {"city": "mahogany-town",  "leader": "Pryce",      "badge_no": 7, "badge_name": "Glacier Badge"},
        {"city": "blackthorn-city","leader": "Clair",      "badge_no": 8, "badge_name": "Rising Badge"},
    ],
    "Hoenn": [
        {"city": "rustboro-city",  "leader": "Roxanne",    "badge_no": 1, "badge_name": "Stone Badge"},
        {"city": "dewford-town",   "leader": "Brawly",     "badge_no": 2, "badge_name": "Knuckle Badge"},
        {"city": "mauville-city",  "leader": "Wattson",    "badge_no": 3, "badge_name": "Dynamo Badge"},
        {"city": "lavaridge-town", "leader": "Flannery",   "badge_no": 4, "badge_name": "Heat Badge"},
        {"city": "petalburg-city", "leader": "Norman",     "badge_no": 5, "badge_name": "Balance Badge"},
        {"city": "fortree-city",   "leader": "Winona",     "badge_no": 6, "badge_name": "Feather Badge"},
        {"city": "mossdeep-city",  "leader": "Tate & Liza","badge_no": 7, "badge_name": "Mind Badge"},
        {"city": "sootopolis-city","leader": "Wallace",    "badge_no": 8, "badge_name": "Rain Badge"},
    ],
    "Sinnoh": [
        {"city": "oreburgh-city",  "leader": "Roark",      "badge_no": 1, "badge_name": "Coal Badge"},
        {"city": "eterna-city",    "leader": "Gardenia",   "badge_no": 2, "badge_name": "Forest Badge"},
        {"city": "hearthome-city", "leader": "Fantina",    "badge_no": 3, "badge_name": "Relic Badge"},
        {"city": "veilstone-city", "leader": "Maylene",    "badge_no": 4, "badge_name": "Cobble Badge"},
        {"city": "pastoria-city",  "leader": "Crasher Wake","badge_no": 5,"badge_name": "Fen Badge"},
        {"city": "canalave-city",  "leader": "Byron",      "badge_no": 6, "badge_name": "Mine Badge"},
        {"city": "snowpoint-city", "leader": "Candice",    "badge_no": 7, "badge_name": "Icicle Badge"},
        {"city": "sunnyshore-city","leader": "Volkner",    "badge_no": 8, "badge_name": "Beacon Badge"},
    ],
    "Unova": [
        {"city": "striaton-city",  "leader": "Cilan/Chili/Cress","badge_no": 1, "badge_name": "Trio Badge"},
        {"city": "nacrene-city",   "leader": "Lenora",     "badge_no": 2, "badge_name": "Basic Badge"},
        {"city": "castelia-city",  "leader": "Burgh",      "badge_no": 3, "badge_name": "Insect Badge"},
        {"city": "nimbasa-city",   "leader": "Elesa",      "badge_no": 4, "badge_name": "Bolt Badge"},
        {"city": "driftveil-city", "leader": "Clay",       "badge_no": 5, "badge_name": "Quake Badge"},
        {"city": "mistralton-city","leader": "Skyla",      "badge_no": 6, "badge_name": "Jet Badge"},
        {"city": "icirrus-city",   "leader": "Brycen",     "badge_no": 7, "badge_name": "Freeze Badge"},
        {"city": "opelucid-city",  "leader": "Drayden/Iris","badge_no": 8, "badge_name": "Legend Badge"},
    ],
    "Kalos": [
        {"city": "santalune-city", "leader": "Viola",      "badge_no": 1, "badge_name": "Bug Badge"},
        {"city": "cyllage-city",   "leader": "Grant",      "badge_no": 2, "badge_name": "Cliff Badge"},
        {"city": "shalour-city",   "leader": "Korrina",    "badge_no": 3, "badge_name": "Rumble Badge"},
        {"city": "coumarine-city", "leader": "Ramos",      "badge_no": 4, "badge_name": "Plant Badge"},
        {"city": "lumiose-city",   "leader": "Clemont",    "badge_no": 5, "badge_name": "Voltage Badge"},
        {"city": "laverre-city",   "leader": "Valerie",    "badge_no": 6, "badge_name": "Fairy Badge"},
        {"city": "anistar-city",   "leader": "Olympia",    "badge_no": 7, "badge_name": "Psychic Badge"},
        {"city": "snowbelle-city", "leader": "Wulfric",    "badge_no": 8, "badge_name": "Iceberg Badge"},
    ],
    "Alola": [
    {"city": "verdant-cavern",                 "leader": "Ilima",     "badge_no": 1, "badge_name": "Trial 1"},
    {"city": "brooklet-hill",                  "leader": "Lana",      "badge_no": 2, "badge_name": "Trial 2"},
    {"city": "wela-volcano-park",              "leader": "Kiawe",     "badge_no": 3, "badge_name": "Trial 3"},
    {"city": "lush-jungle",                     "leader": "Mallow",    "badge_no": 4, "badge_name": "Trial 4"},
    {"city": "hokulani-observatory",           "leader": "Sophocles", "badge_no": 5, "badge_name": "Trial 5"},
    {"city": "thrifty-megamart-abandoned-site","leader": "Acerola",   "badge_no": 6, "badge_name": "Trial 6"},
    {"city": "tapu-village",                    "leader": "Nanu",      "badge_no": 7, "badge_name": "Kahuna Trial"},
    {"city": "seafolk-village",                 "leader": "Hapu",      "badge_no": 8, "badge_name": "Kahuna Grand Trial"},
],

    "Galar": [
        {"city": "turffield",      "leader": "Milo",       "badge_no": 1, "badge_name": "Grass Badge"},
        {"city": "hulbury",        "leader": "Nessa",      "badge_no": 2, "badge_name": "Water Badge"},
        {"city": "motostoke",      "leader": "Kabu",       "badge_no": 3, "badge_name": "Fire Badge"},
        {"city": "stow-on-side",   "leader": "Bea/Allister","badge_no": 4, "badge_name": "Fighting/Ghost Badge"},
        {"city": "circhester",     "leader": "Gordie/Melony","badge_no": 5, "badge_name": "Rock/Ice Badge"},
        {"city": "spikemuth",      "leader": "Piers",      "badge_no": 6, "badge_name": "Dark Badge"},
        {"city": "hammerlocke",    "leader": "Raihan",     "badge_no": 7, "badge_name": "Dragon Badge"},
        {"city": "wyndon",         "leader": "Champion Cup","badge_no": 8, "badge_name": "Champion Qualifier"},
    ],
    "Paldea": [
        {"city": "cortondo",       "leader": "Katy",       "badge_no": 1, "badge_name": "Bug Badge"},
        {"city": "artazon",        "leader": "Brassius",   "badge_no": 2, "badge_name": "Grass Badge"},
        {"city": "levincia",       "leader": "Iono",       "badge_no": 3, "badge_name": "Electric Badge"},
        {"city": "cascarrafa",     "leader": "Kofu",       "badge_no": 4, "badge_name": "Water Badge"},
        {"city": "medali",         "leader": "Larry",      "badge_no": 5, "badge_name": "Normal Badge"},
        {"city": "montenevera",    "leader": "Ryme",       "badge_no": 6, "badge_name": "Ghost Badge"},
        {"city": "alfornada",      "leader": "Tulip",      "badge_no": 7, "badge_name": "Psychic Badge"},
        {"city": "glaseado-gym",   "leader": "Grusha",     "badge_no": 8, "badge_name": "Ice Badge"},
    ],
}

def get_gym_order(region: str) -> List[Dict[str, object]]:
    return GYM_ORDERS.get(region, [])

def next_gym_info(region: str, current_badges: int) -> Optional[Dict[str, object]]:
    try:
        n = int(current_badges or 0) + 1
    except Exception:
        n = 1
    for g in get_gym_order(region):
        if int(g.get("badge_no", 0)) == n:
            return g
    return None


# ==============================================================
#  🗺️ Consultas de local e rotas
# ==============================================================

def get_adjacent_routes(supabase, region: str, location_from: str, *, mainline_only: bool = False) -> List[Dict]:
    try:
        q = (supabase.table("routes")
             .select("location_from,location_to,step,is_mainline,gate")
             .ilike("region", region)
             .ilike("location_from", location_from))
        if mainline_only:
            q = q.eq("is_mainline", True)
        q = q.order("step").order("location_to")
        res = q.execute()
        data = list(res.data or [])
        return data
    except Exception as e:
        return []


def get_next_mainline_edge(supabase, region: str, location_from: str) -> Optional[Dict]:
    try:
        q = (supabase.table("routes")
             .select("location_from,location_to,step,gate")
             .eq("region", region)
             .eq("location_from", location_from)
             .eq("is_mainline", True)
             .order("step")
             .limit(1))
        res = q.execute()
        rows = res.data or []
        edge = dict(rows[0]) if rows else None
        return edge
    except Exception as e:
        return None

def get_permitted_destinations(supabase, player: Any, region: str, location_from: str, *, mainline_only: bool = False) -> List[Dict]:
    edges = get_adjacent_routes(supabase, region, location_from, mainline_only=mainline_only)

    allowed: List[Dict] = []
    try:
        for e in edges:
            gate = _coerce_gate(e.get("gate"))
            if gate_allows(player, gate):
                allowed.append({
                    "location_to": e["location_to"],
                    "step": e.get("step"),
                    "is_mainline": e.get("is_mainline", False),
                    "gate": gate
                })
        allowed.sort(key=lambda d: (d["step"] is None, d["step"] or 10**9, d["location_to"]))
        return allowed          # ✅ FALTAVA ISSO
    except Exception as e:
        return []


def get_location_info(supabase, location_api_name: str) -> Optional[Dict]:
    try:
        res = (
            supabase.table("locations")
            .select("location_api_name,name,type,region,has_gym,has_shop,default_area,metadata")
            .eq("location_api_name", location_api_name)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        info = dict(rows[0]) if rows else None
        return info
    except Exception as e:
        print(f"[event_utils:get_location_info][ERROR] {e}", flush=True)
        traceback.print_exc()
        raise  # <--- deixa a exceção subir pra você ver o erro real
