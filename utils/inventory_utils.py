# utils/inventory_utils.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from supabase import Client

PLAYER_ITEMS_TABLE = "player_items"     # player_id, item_id, quantity
ITEMS_TABLE = "items"                   # id, name
POKEBALL_NAME = "Pokeball"              # conforme sua tabela items (seed usa "Pokeball")
POKEBALL_ALIASES = ["pokeball", "poke ball", "poké ball"]  # tolerância de nomes

def _get_item_id_by_name(supabase: Client, item_name: str):
    """
    Tenta achar o item por name exato; se não achar, tenta por aliases usando ILIKE.
    Retorna item_id ou None.
    """
    # 1) tentativa por name exato (seed costuma ser "Pokeball")
    it = (supabase.table(ITEMS_TABLE)
          .select("id")
          .eq("name", item_name)
          .limit(1)
          .execute()).data or []
    if it:
        return it[0]["id"]

    # 2) tentativa por ILIKE (case-insensitive) com o nome solicitado
    it = (supabase.table(ITEMS_TABLE)
          .select("id")
          .ilike("name", item_name)
          .limit(1)
          .execute()).data or []
    if it:
        return it[0]["id"]

    # 3) fallback: tentar aliases comuns
    for alias in POKEBALL_ALIASES:
        it = (supabase.table(ITEMS_TABLE)
              .select("id")
              .ilike("name", alias)
              .limit(1)
              .execute()).data or []
        if it:
            return it[0]["id"]

    return None

async def get_item_qty(supabase: Client, player_id: int, item_name: str) -> int:
    item_id = _get_item_id_by_name(supabase, item_name)
    if item_id is None:
        return 0
    row = (supabase.table(PLAYER_ITEMS_TABLE)
           .select("quantity")
           .eq("player_id", player_id)
           .eq("item_id", item_id)
           .limit(1)
           .execute()).data or []
    return int(row[0]["quantity"]) if row else 0

async def consume_item(supabase: Client, player_id: int, item_name: str, amount: int = 1) -> bool:
    item_id = _get_item_id_by_name(supabase, item_name)
    if item_id is None:
        return False
    row = (supabase.table(PLAYER_ITEMS_TABLE)
           .select("quantity")
           .eq("player_id", player_id)
           .eq("item_id", item_id)
           .limit(1)
           .execute()).data or []
    qty = int(row[0]["quantity"]) if row else 0
    if qty < amount:
        return False
    new_qty = max(0, qty - amount)
    (supabase.table(PLAYER_ITEMS_TABLE)
     .update({"quantity": new_qty})
     .eq("player_id", player_id)
     .eq("item_id", item_id)
     .execute())
    return True

# ---- Helpers específicos de Pokébola (opcionais, mas úteis) ----
async def get_pokeball_qty(supabase: Client, player_id: int) -> int:
    return await get_item_qty(supabase, player_id, POKEBALL_NAME)

async def consume_pokeball(supabase: Client, player_id: int, amount: int = 1) -> bool:
    return await consume_item(supabase, player_id, POKEBALL_NAME, amount)
