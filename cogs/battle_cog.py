# cogs/battle_cog.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import math
import random
from typing import Optional, List, Dict, Any, Tuple, Callable

import discord
from discord.ext import commands
from supabase import create_client, Client

# Utils do projeto (ajuste conforme seus caminhos)
import utils.pokeapi_service as pokeapi  # get_pokemon_data, get_pokemon_species_data, get_total_xp_for_level, calculate_stats_for_level
from utils import battle_utils  # calc_damage, hp_bar, capture_chance, attempt_capture, describe_effectiveness
from utils.inventory_utils import get_item_qty, consume_item, POKEBALL_NAME

# Se tiver helper de captura persistida:
try:
    from cogs.player_cog import add_pokemon_to_player
except Exception:
    add_pokemon_to_player = None  # fallback

# =========================
# Supabase helper
# =========================
def get_supabase_client() -> Client:
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY")
    return create_client(url, key)

# =========================
# Config
# =========================
LEVEL_CAP = 100
HAPPINESS_GAIN_ON_WIN = 2
HAPPINESS_CAP = 255
DEFAULT_WILD = "pidgey"  # oponente selvagem de teste

# =========================
# Estado de batalha
# =========================
class BattleState:
    def __init__(self, user_id: int, seed: Optional[int] = None):
        self.user_id = user_id
        self.rng = random.Random(seed or random.randrange(1, 10**9))
        self.turn = 1

        # Player snapshot
        self.player_mon: Dict[str, Any] = {}
        self.player_types: List[str] = []
        self.player_moves: List[Dict[str, Any]] = []
        self.player_sprite_url: Optional[str] = None

        # Oponente
        self.opp_name: str = DEFAULT_WILD
        self.opp_level: int = 5
        self.opp_types: List[str] = []
        self.opp_stats: Dict[str, int] = {}
        self.opp_hp: int = 1
        self.opp_base_exp: int = 50
        self.opp_capture_rate: int = 255
        self.opp_sprite_url: Optional[str] = None

        # Flag de término
        self.ended: bool = False

# =========================
# Helpers BD
# =========================
def fetch_active_party_mon(supabase: Client, player_id: int) -> Optional[dict]:
    """Pega o primeiro Pokémon da party (menor party_position)."""
    try:
        res = (
            supabase.table("player_pokemon")
            .select("*")
            .eq("player_id", player_id)
            .filter("party_position", "not.is", "null")
            .order("party_position")
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return dict(rows[0]) if rows else None
    except Exception as e:
        print(f"[Battle] erro party: {e}", flush=True)
        return None

def fetch_party_list(supabase: Client, player_id: int) -> List[dict]:
    """Lista completa da party (1..6), ordenada, com campos úteis."""
    try:
        res = (
            supabase.table("player_pokemon")
            .select("*")
            .eq("player_id", player_id)
            .filter("party_position", "not.is", "null")
            .order("party_position", desc=False)
            .execute()
        )
        return res.data or []
    except Exception as e:
        print(f"[Battle] erro listar party: {e}", flush=True)
        return []

def update_player_mon_hp(supabase: Client, mon_id: str, new_hp: int):
    try:
        supabase.table("player_pokemon").update({"current_hp": max(0, int(new_hp))}).eq("id", mon_id).execute()
    except Exception as e:
        print(f"[Battle] falha update HP: {e}", flush=True)

# =========================
# Cog
# =========================
class BattleCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.supabase = get_supabase_client()
        self.active_battles: Dict[int, BattleState] = {}  # uma por jogador

    # ---------- util ----------
    async def _send_log(self, ctx_or_inter, text: str):
        try:
            if hasattr(ctx_or_inter, "send"):
                await ctx_or_inter.send(text)
            else:
                await ctx_or_inter.followup.send(text)
        except Exception:
            pass

    async def _load_player_active_mon(self, user_id: int) -> Optional[dict]:
        return fetch_active_party_mon(self.supabase, user_id)

    async def _get_party(self, user_id: int) -> List[dict]:
        return fetch_party_list(self.supabase, user_id)

    async def _load_move_info(self, move_name: str) -> Dict[str, Any]:
        try:
            url = f"https://pokeapi.co/api/v2/move/{str(move_name).lower()}"
            data = await pokeapi.get_data_from_url(url)
            if not data:
                return {"name": move_name, "type": "normal", "power": 40, "damage_class": {"name": "physical"}}
            return {
                "name": data.get("name", move_name),
                "type": (data.get("type") or {}).get("name", "normal"),
                "power": data.get("power") or 40,
                "damage_class": data.get("damage_class") or {"name": "physical"},
            }
        except Exception:
            return {"name": move_name, "type": "normal", "power": 40, "damage_class": {"name": "physical"}}

    async def _inflate_player_moves(self, mon_row: dict) -> List[Dict[str, Any]]:
        moves = mon_row.get("moves") or []
        result: List[Dict[str, Any]] = []
        for m in moves[:4]:
            if not m:
                continue
            info = await self._load_move_info(m)
            result.append({
                "name": info["name"],
                "type": info["type"],
                "power": int(info["power"] or 0),
                "category": (info["damage_class"] or {}).get("name", "physical"),
            })
        if not result:
            result = [{"name": "tackle", "type": "normal", "power": 40, "category": "physical"}]
        return result

    async def _build_state(self, ctx: commands.Context) -> Optional[BattleState]:
        mon = await self._load_player_active_mon(ctx.author.id)
        if not mon:
            await ctx.send("Você não tem Pokémon na party. Use `!addpokemon` para adicionar um.")
            return None

        st = BattleState(user_id=ctx.author.id)

        # Player snapshot
        st.player_mon = mon
        st.player_sprite_url = await self._get_sprite_url(mon.get("pokemon_api_name"), shiny=bool(mon.get("is_shiny")))
        pkmn_data = await pokeapi.get_pokemon_data(mon.get("pokemon_api_name"))
        st.player_types = [t["type"]["name"] for t in (pkmn_data or {}).get("types", [])] if pkmn_data else []
        st.player_moves = await self._inflate_player_moves(mon)

        # Oponente simples (mesmo level)
        st.opp_name = DEFAULT_WILD
        st.opp_level = int(mon.get("current_level") or 5)
        opp_data = await pokeapi.get_pokemon_data(st.opp_name)
        opp_species = await pokeapi.get_pokemon_species_data((opp_data or {}).get("species", {}).get("name", st.opp_name))
        st.opp_types = [t["type"]["name"] for t in (opp_data or {}).get("types", [])] if opp_data else []
        st.opp_sprite_url = (opp_data or {}).get("sprites", {}).get("other", {}).get("official-artwork", {}).get("front_default") or (opp_data or {}).get("sprites", {}).get("front_default")
        st.opp_base_exp = int((opp_data or {}).get("base_experience") or 50)
        st.opp_capture_rate = int((opp_species or {}).get("capture_rate") or 255)

        base_stats = (opp_data or {}).get("stats", [])
        st.opp_stats = pokeapi.calculate_stats_for_level(base_stats, st.opp_level)
        st.opp_hp = int(st.opp_stats.get("max_hp", 10))
        return st

    async def _get_sprite_url(self, name: str, shiny: bool = False) -> Optional[str]:
        data = await pokeapi.get_pokemon_data(name)
        if not data:
            return None
        if shiny:
            return data["sprites"].get("front_shiny") or data["sprites"].get("other", {}).get("official-artwork", {}).get("front_shiny")
        return data["sprites"].get("front_default") or data["sprites"].get("other", {}).get("official-artwork", {}).get("front_default")

    def _hp_texts(self, st: BattleState) -> Tuple[str, str]:
        php = int(st.player_mon.get("current_hp") or 1)
        pmax = int(st.player_mon.get("max_hp") or 1)
        player_hp_line, _ = battle_utils.hp_bar(php, pmax)
        oline, _ = battle_utils.hp_bar(st.opp_hp, int(st.opp_stats.get("max_hp", 1)))
        return player_hp_line, oline

    async def _reward_on_win(self, st: BattleState) -> Tuple[int, int]:
        level = int(st.player_mon["current_level"])
        reward_xp = max(1, math.floor((st.opp_base_exp * max(1, level)) / 7))

        species = await pokeapi.get_pokemon_species_data(st.player_mon["pokemon_api_name"])
        growth_url = (species or {}).get("growth_rate", {}).get("url")
        current_xp = int(st.player_mon.get("current_xp") or 0)
        new_total_xp = current_xp + reward_xp

        current_level = int(st.player_mon.get("current_level") or 1)
        target_level = current_level
        if growth_url:
            for lv in range(current_level + 1, LEVEL_CAP + 1):
                need = await pokeapi.get_total_xp_for_level(growth_url, lv)
                if need == float("inf"):
                    break
                if new_total_xp >= int(need):
                    target_level = lv
                else:
                    break

        update_payload: Dict[str, Any] = {
            "current_xp": new_total_xp,
            "happiness": min(HAPPINESS_CAP, int(st.player_mon.get("happiness") or 0) + HAPPINESS_GAIN_ON_WIN),
        }
        if target_level > current_level:
            pkmn_data = await pokeapi.get_pokemon_data(st.player_mon["pokemon_api_name"])
            new_stats = pokeapi.calculate_stats_for_level((pkmn_data or {}).get("stats", []), target_level)
            delta_hp = int(new_stats.get("max_hp", st.player_mon["max_hp"])) - int(st.player_mon["max_hp"])
            new_cur_hp = int(st.player_mon["current_hp"]) + max(0, delta_hp)
            update_payload.update({
                "current_level": target_level,
                "max_hp": new_stats.get("max_hp", st.player_mon["max_hp"]),
                "attack": new_stats.get("attack", st.player_mon["attack"]),
                "defense": new_stats.get("defense", st.player_mon["defense"]),
                "special_attack": new_stats.get("special_attack", st.player_mon["special_attack"]),
                "special_defense": new_stats.get("special_defense", st.player_mon["special_defense"]),
                "speed": new_stats.get("speed", st.player_mon["speed"]),
                "current_hp": min(update_payload.get("max_hp", st.player_mon["max_hp"]), new_cur_hp),
            })

        self.supabase.table("player_pokemon").update(update_payload).eq("id", st.player_mon["id"]).execute()
        st.player_mon.update(update_payload)
        return reward_xp, new_total_xp

    def _build_embed(self, st: BattleState) -> discord.Embed:
        player_hp_line, opp_hp_line = self._hp_texts(st)
        emb = discord.Embed(
            title=f"⚔️ Batalha Selvagem — Turno {st.turn}",
            description="Escolha **Lutar**, **Capturar**, **Trocar** ou **Fugir** abaixo.",
            color=discord.Color.blurple()
        )
        emb.add_field(
            name="Seu Pokémon",
            value=f"{(st.player_mon.get('nickname') or st.player_mon.get('pokemon_api_name','?')).capitalize()} "
                  f"(Lv. {st.player_mon.get('current_level', 1)})\n{player_hp_line}",
            inline=False
        )
        emb.add_field(
            name="Oponente",
            value=f"{st.opp_name.capitalize()} (Lv. {st.opp_level})\n{opp_hp_line}",
            inline=False
        )
        if st.opp_sprite_url:
            emb.set_image(url=st.opp_sprite_url)
        if st.player_sprite_url:
            emb.set_thumbnail(url=st.player_sprite_url)
        return emb

    # ---------- Views ----------
    class BattleView(discord.ui.View):
        """
        View com:
         - 4 botões de ataque (linha 0)
         - 3 botões: Capturar / Trocar / Fugir (linha 1)
        Timeout: 300s -> fuga por inatividade
        """
        def __init__(self, cog: "BattleCog", st: "BattleState"):
            super().__init__(timeout=300)
            self.cog = cog
            self.st = st
            self.message: Optional[discord.Message] = None

            # === Linha 0: quatro botões de ataque ===
            moves = (st.player_moves or [])[:4]
            labels = [m.get("name", "tackle") for m in moves]
            while len(labels) < 4:
                labels.append(None)

            for idx in range(4):
                lbl = labels[idx]
                btn = discord.ui.Button(
                    label=(lbl.capitalize() if lbl else "—"),
                    style=discord.ButtonStyle.success,
                    row=0,
                    disabled=(lbl is None),
                    custom_id=f"battle_atk_{idx}"
                )
                btn.callback = self._make_attack_callback(idx, lbl)
                self.add_item(btn)

            # === Linha 1: Capturar / Trocar / Fugir ===
            cap_btn = discord.ui.Button(label="🎯 Capturar", style=discord.ButtonStyle.primary, row=1, custom_id="battle_capture_btn")
            cap_btn.callback = self._on_capture_clicked
            self.add_item(cap_btn)

            swap_btn = discord.ui.Button(label="🔄 Trocar Pokémon", style=discord.ButtonStyle.secondary, row=1, custom_id="battle_swap_btn")
            swap_btn.callback = self._on_swap_clicked
            self.add_item(swap_btn)

            run_btn = discord.ui.Button(label="🏃 Fugir", style=discord.ButtonStyle.danger, row=1, custom_id="battle_run_btn")
            run_btn.callback = self._on_run_clicked
            self.add_item(run_btn)

        # --- callbacks de botões ---
        def _make_attack_callback(self, idx: int, label: Optional[str]) -> Callable[[discord.Interaction], Any]:
            async def _cb(interaction: discord.Interaction):
                self.message = interaction.message
                if not await self._pre_check(interaction):
                    return
                move: Optional[Dict[str, Any]] = None
                if label:
                    for m in self.st.player_moves:
                        if str(m.get("name")).lower() == str(label).lower():
                            move = m
                            break
                if not move:
                    move = {"name": "tackle", "type": "normal", "power": 40, "category": "physical"}
                await self.cog._on_player_move(interaction, self.st, move)
            return _cb

        async def _on_capture_clicked(self, interaction: discord.Interaction):
            self.message = interaction.message
            if not await self._pre_check(interaction):
                return
            await self.cog._on_player_capture(interaction, self.st)

        async def _on_swap_clicked(self, interaction: discord.Interaction):
            self.message = interaction.message
            if not await self._pre_check(interaction):
                return
            # Troca voluntária -> consome turno (oponente ataca depois)
            await self.cog._prompt_switch(interaction, self.st, forced=False)

        async def _on_run_clicked(self, interaction: discord.Interaction):
            self.message = interaction.message
            if not await self._pre_check(interaction):
                return
            try:
                await interaction.response.defer()
            except Exception:
                pass
            await self.cog._end_battle(interaction, self.st, escaped=True, finished=False, reason="você fugiu")

        async def _pre_check(self, interaction: discord.Interaction) -> bool:
            try:
                if int(interaction.user.id) != int(self.st.user_id):
                    await interaction.response.send_message("Essa batalha não é sua. 😉", ephemeral=True)
                    return False
            except Exception:
                pass
            if getattr(self.st, "ended", False):
                try:
                    await interaction.response.send_message("A batalha já foi encerrada.", ephemeral=True)
                except Exception:
                    pass
                return False
            return True

        async def on_timeout(self) -> None:
            if getattr(self.st, "ended", False):
                return
            try:
                if self.message:
                    await self.message.edit(view=None)
            except (discord.NotFound, discord.HTTPException):
                pass
            except Exception:
                pass
            try:
                await self.cog._end_battle_from_message(
                    message=self.message,
                    st=self.st,
                    escaped=True,
                    reason="inatividade (5 min)"
                )
            except Exception:
                try:
                    self.cog.active_battles.pop(self.st.user_id, None)
                    if self.message and self.message.channel:
                        await self.message.channel.send("O Pokémon se cansou de esperar e fugiu (inatividade: 5 min).")
                except Exception:
                    pass

    # ---------- Encerramento centralizado ----------
    async def _end_battle(self, ctx_or_inter, st: BattleState, escaped: bool, finished: bool, reason: Optional[str] = None):
        if getattr(st, "ended", False):
            return
        st.ended = True
        self.active_battles.pop(st.user_id, None)

        try:
            if hasattr(ctx_or_inter, "message") and ctx_or_inter.message:
                try:
                    await ctx_or_inter.edit_original_response(view=None)
                except Exception:
                    try:
                        await ctx_or_inter.message.edit(view=None)
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            if escaped and not finished:
                msg = "🏃 A batalha terminou: você fugiu."
            elif escaped and finished:
                msg = "✨ A batalha terminou: captura realizada."
            elif not escaped and finished:
                msg = "🏆 A batalha terminou: você venceu!"
            else:
                msg = "💀 A batalha terminou: você perdeu."
            if reason:
                msg += f" (Motivo: {reason})"
            await self._send_log(ctx_or_inter, msg)
        except Exception:
            pass

    async def _end_battle_from_message(self, message: Optional[discord.Message], st: BattleState, escaped: bool, reason: Optional[str] = None):
        if getattr(st, "ended", False):
            return
        st.ended = True
        self.active_battles.pop(st.user_id, None)

        try:
            if message:
                await message.edit(view=None)
        except Exception:
            pass

        try:
            if message and message.channel:
                base = "🏃 A batalha terminou: o Pokémon fugiu por esperar demais."
                if reason:
                    base += f" (Motivo: {reason})"
                await message.channel.send(base)
        except Exception:
            pass

    # ---------- Troca de Pokémon ----------
    async def _prompt_switch(self, interaction: discord.Interaction, st: BattleState, forced: bool):
        """
        Abre uma UI de troca. Se forced=True (por desmaio), sem botão cancelar.
        Se a troca for voluntária (forced=False), consome 1 turno: após trocar, o oponente ataca.
        """
        try:
            await interaction.response.defer()
        except Exception:
            pass

        party = await self._get_party(st.user_id)
        # elegíveis: vivos e diferentes do atual
        candidates = [r for r in party if r.get("id") != st.player_mon.get("id") and int(r.get("current_hp", 0)) > 0]

        if not candidates:
            if forced:
                # sem opções -> derrota
                emb = self._build_embed(st)
                try:
                    await interaction.followup.edit_message(message_id=interaction.message.id, embed=emb, view=None)
                except Exception:
                    pass
                await self._end_battle(interaction, st, escaped=False, finished=False, reason="sem Pokémon disponíveis")
                return
            else:
                await self._send_log(interaction, "Não há Pokémon saudáveis na party para trocar.")
                # re-render view atual
                emb = self._build_embed(st)
                view = BattleCog.BattleView(self, st)
                view.message = interaction.message
                try:
                    await interaction.followup.edit_message(message_id=interaction.message.id, embed=emb, view=view)
                except Exception:
                    pass
                return

        # monta select
        options: List[discord.SelectOption] = []
        for r in candidates:
            name = (r.get("nickname") or r.get("pokemon_api_name") or "").capitalize()
            lvl = r.get("current_level", 1)
            hp = r.get("current_hp", 0)
            mhp = r.get("max_hp", 1)
            options.append(discord.SelectOption(label=f"{name} (Lv.{lvl}) — {hp}/{mhp} HP", value=str(r["id"]))[:])

        class SwapSelect(discord.ui.Select):
            def __init__(self, opts, owner_id: int):
                super().__init__(placeholder="Escolha o substituto…", min_values=1, max_values=1, options=opts)
                self.value_id: Optional[str] = None
                self.owner_id = owner_id
            async def callback(self, inter: discord.Interaction):
                if inter.user.id != self.owner_id:
                    return await inter.response.send_message("Não é sua interface.", ephemeral=True)
                self.value_id = self.values[0]
                await inter.response.defer()

        sel = SwapSelect(options, st.user_id)
        btn_confirm = discord.ui.Button(label="Confirmar troca", style=discord.ButtonStyle.success)
        view = discord.ui.View(timeout=120)
        view.add_item(sel)
        view.add_item(btn_confirm)
        if not forced:
            btn_cancel = discord.ui.Button(label="Cancelar", style=discord.ButtonStyle.secondary)
            view.add_item(btn_cancel)

            async def on_cancel(inter: discord.Interaction):
                if inter.user.id != st.user_id:
                    return await inter.response.send_message("Não é sua interface.", ephemeral=True)
                emb = self._build_embed(st)
                v = BattleCog.BattleView(self, st)
                v.message = interaction.message
                await inter.response.edit_message(embed=emb, view=v)
            btn_cancel.callback = on_cancel

        async def on_confirm(inter: discord.Interaction):
            if inter.user.id != st.user_id:
                return await inter.response.send_message("Não é sua interface.", ephemeral=True)
            if not sel.value_id:
                return await inter.response.send_message("Escolha um Pokémon para trocar.", ephemeral=True)

            # aplica a troca no snapshot
            target = next((r for r in candidates if str(r["id"]) == sel.value_id), None)
            if not target or int(target.get("current_hp", 0)) <= 0:
                return await inter.response.send_message("Esse Pokémon não pode entrar.", ephemeral=True)

            # snapshot do novo ativo
            st.player_mon = dict(target)
            st.player_sprite_url = await self._get_sprite_url(target.get("pokemon_api_name"), shiny=bool(target.get("is_shiny")))
            pkmn_data = await pokeapi.get_pokemon_data(target.get("pokemon_api_name"))
            st.player_types = [t["type"]["name"] for t in (pkmn_data or {}).get("types", [])] if pkmn_data else []
            st.player_moves = await self._inflate_player_moves(target)

            await inter.response.edit_message(content="🔄 **Troca realizada!**", view=None)
            await self._send_log(inter, f"Você enviou **{(target.get('nickname') or target.get('pokemon_api_name')).capitalize()}** para o campo!")

            emb = self._build_embed(st)

            if not forced:
                # troca voluntária consome turno -> oponente ataca
                opp_move = await self._choose_ai_move(st)
                await self._resolve_attack(attacker="opp", st=st, move=opp_move, ctx_or_inter=inter)

                # verifica derrota após o golpe
                if int(st.player_mon["current_hp"]) <= 0:
                    await self._send_log(inter, f"Seu {st.player_mon.get('pokemon_api_name').capitalize()} desmaiou após a troca!")
                    # tenta nova escolha forçada; se não tiver, derrota
                    await self._prompt_switch(inter, st, forced=True)
                    return

                st.turn += 1  # consumiu turno
                emb = self._build_embed(st)

            # re-render batalha com a nova view
            v = BattleCog.BattleView(self, st)
            v.message = interaction.message
            try:
                await interaction.followup.edit_message(message_id=interaction.message.id, embed=emb, view=v)
            except Exception:
                pass

        btn_confirm.callback = on_confirm

        # mostra UI de seleção
        try:
            await interaction.followup.edit_message(message_id=interaction.message.id, content="Escolha o substituto:", embed=None, view=view)
        except Exception:
            try:
                await interaction.channel.send("Escolha o substituto:", view=view)
            except Exception:
                pass

    # ---------- Turno ----------
    async def _on_player_move(self, interaction: discord.Interaction, st: BattleState, move: Dict[str, Any]):
        try:
            await interaction.response.defer()
        except Exception:
            pass
        try:
            await interaction.edit_original_response(view=None)
        except Exception:
            pass

        # Player ataca
        await self._resolve_attack(attacker="player", st=st, move=move, ctx_or_inter=interaction)

        # Opp responde se vivo
        if st.opp_hp > 0:
            opp_move = await self._choose_ai_move(st)
            await self._resolve_attack(attacker="opp", st=st, move=opp_move, ctx_or_inter=interaction)

        # Checa condições
        if st.opp_hp <= 0:
            await self._send_log(interaction, f"{st.opp_name.capitalize()} desmaiou!")
            reward_xp, _ = await self._reward_on_win(st)
            await self._send_log(interaction, f"Você ganhou **{reward_xp} XP** e +{HAPPINESS_GAIN_ON_WIN} de amizade.")
            emb = self._build_embed(st)
            try:
                await interaction.followup.edit_message(message_id=interaction.message.id, embed=emb, view=None)
            except Exception:
                pass
            await self._end_battle(interaction, st, escaped=False, finished=True)
            return

        if int(st.player_mon["current_hp"]) <= 0:
            # Player desmaiou -> tentar troca forçada (sem custo de turno imediato)
            await self._send_log(interaction, "Seu Pokémon desmaiou! Escolha um substituto.")
            await self._prompt_switch(interaction, st, forced=True)
            return

        # segue batalha
        st.turn += 1
        emb = self._build_embed(st)
        view = BattleCog.BattleView(self, st)
        view.message = interaction.message
        try:
            await interaction.followup.edit_message(message_id=interaction.message.id, embed=emb, view=view)
        except Exception:
            pass

    async def _resolve_attack(self, attacker: str, st: BattleState, move: Dict[str, Any], ctx_or_inter) -> Tuple[int, Optional[str]]:
        if attacker == "player":
            category = (move.get("category") or "physical").lower()
            a_atk = int(st.player_mon["attack"] if category == "physical" else st.player_mon["special_attack"])
            d_def = int(st.opp_stats["defense"] if category == "physical" else st.opp_stats["special_defense"])
            dmg, eff, _ = battle_utils.calc_damage(
                level=int(st.player_mon["current_level"]),
                power=int(move.get("power") or 0),
                atk=a_atk, deff=d_def,
                move_type=move.get("type") or "normal",
                attacker_types=st.player_types,
                defender_types=st.opp_types,
                rng=st.rng,
            )
            st.opp_hp = max(0, st.opp_hp - dmg)
            eff_txt = battle_utils.describe_effectiveness(eff)
            line = f"{(st.player_mon.get('nickname') or st.player_mon['pokemon_api_name']).capitalize()} usou **{move['name'].capitalize()}**!"
            if eff_txt: line += f" {eff_txt}"
            line += f" Causou {dmg} de dano."
            await self._send_log(ctx_or_inter, line)
            return dmg, eff_txt

        # Oponente ataca
        category = (move.get("category") or "physical").lower()
        a_atk = int(st.opp_stats["attack"] if category == "physical" else st.opp_stats["special_attack"])
        d_def = int(st.player_mon["defense"] if category == "physical" else st.player_mon["special_defense"])
        dmg, eff, _ = battle_utils.calc_damage(
            level=st.opp_level,
            power=int(move.get("power") or 0),
            atk=a_atk, deff=d_def,
            move_type=move.get("type") or "normal",
            attacker_types=st.opp_types,
            defender_types=st.player_types,
            rng=st.rng,
        )
        new_hp = max(0, int(st.player_mon["current_hp"]) - dmg)
        st.player_mon["current_hp"] = new_hp
        update_player_mon_hp(self.supabase, st.player_mon["id"], new_hp)
        eff_txt = battle_utils.describe_effectiveness(eff)
        line = f"O {st.opp_name.capitalize()} usou **{move['name'].capitalize()}**!"
        if eff_txt: line += f" {eff_txt}"
        line += f" Você levou {dmg} de dano."
        await self._send_log(ctx_or_inter, line)
        return dmg, eff_txt

    async def _choose_ai_move(self, st: BattleState) -> Dict[str, Any]:
        for cand in ["gust", "quick-attack", "tackle"]:
            info = await self._load_move_info(cand)
            if info and info.get("power"):
                return {"name": info["name"], "type": info["type"], "power": info["power"], "category": info["damage_class"]["name"]}
        return {"name": "tackle", "type": "normal", "power": 40, "category": "physical"}

    async def _on_player_capture(self, interaction: discord.Interaction, st: BattleState):
        try:
            await interaction.response.defer()
        except Exception:
            pass

        try:
            if st.user_id not in self.active_battles:
                return await self._send_log(interaction, "Esta batalha não está mais ativa.")

            # inventário
            try:
                qty = await get_item_qty(self.supabase, st.user_id, POKEBALL_NAME)
            except Exception as inv_e:
                return await self._send_log(interaction, f"❌ Erro ao checar inventário: `{inv_e}`")

            if qty <= 0:
                await self._send_log(interaction, "❌ Você não tem Pokébolas suficientes.")
                emb = self._build_embed(st)
                view = BattleCog.BattleView(self, st)
                view.message = interaction.message
                try:
                    await interaction.followup.edit_message(message_id=interaction.message.id, embed=emb, view=view)
                except Exception:
                    pass
                return

            try:
                ok_consume = await consume_item(self.supabase, st.user_id, POKEBALL_NAME, amount=1)
            except Exception as inv_e:
                return await self._send_log(interaction, f"❌ Erro ao consumir item: `{inv_e}`")
            if not ok_consume:
                await self._send_log(interaction, "❌ Falha ao consumir a Pokébola.")
                emb = self._build_embed(st)
                view = BattleCog.BattleView(self, st)
                view.message = interaction.message
                try:
                    await interaction.followup.edit_message(message_id=interaction.message.id, embed=emb, view=view)
                except Exception:
                    pass
                return

            await self._send_log(interaction, f"🎯 Você arremessou uma **{POKEBALL_NAME}**. ({qty-1} restantes)")

            # captura
            chance = battle_utils.capture_chance(
                base_capture_rate=st.opp_capture_rate,
                wild_max_hp=int(st.opp_stats.get("max_hp", 1)),
                wild_current_hp=st.opp_hp,
                ball_mult=1.0, status_mult=1.0,
            )
            success = battle_utils.attempt_capture(st.rng, chance)
            await self._send_log(interaction, "A Pokébola balançou…")

            if success:
                await self._send_log(interaction, "✨ **Captura bem-sucedida!**")
                if add_pokemon_to_player:
                    try:
                        res = await add_pokemon_to_player(
                            player_id=st.user_id,
                            pokemon_api_name=st.opp_name,
                            level=st.opp_level,
                            captured_at="Batalha selvagem",
                            assign_to_party_if_space=True,
                        )
                        if not res or not res.get("success"):
                            await self._send_log(interaction, f"(Aviso) Falha ao registrar captura: {res and res.get('error')}")
                    except Exception as save_e:
                        await self._send_log(interaction, f"(Aviso) Erro ao salvar captura: `{save_e}`")

                emb = self._build_embed(st)
                try:
                    await interaction.followup.edit_message(message_id=interaction.message.id, embed=emb, view=None)
                except Exception:
                    pass
                await self._end_battle(interaction, st, escaped=True, finished=True)
                return

            # falhou a captura -> oponente ataca
            await self._send_log(interaction, "😓 O Pokémon escapou!")
            opp_move = await self._choose_ai_move(st)
            await self._resolve_attack(attacker="opp", st=st, move=opp_move, ctx_or_inter=interaction)

            # se desmaiou após o contra-ataque, aciona troca forçada
            if int(st.player_mon["current_hp"]) <= 0:
                await self._send_log(interaction, "Seu Pokémon desmaiou! Escolha um substituto.")
                await self._prompt_switch(interaction, st, forced=True)
                return

            st.turn += 1
            emb = self._build_embed(st)
            view = BattleCog.BattleView(self, st)
            view.message = interaction.message
            try:
                await interaction.followup.edit_message(message_id=interaction.message.id, embed=emb, view=view)
            except Exception:
                pass

        except Exception as e:
            await self._send_log(interaction, f"❌ Erro ao tentar capturar: `{e}`")
            try:
                emb = self._build_embed(st)
                view = BattleCog.BattleView(self, st)
                view.message = interaction.message
                await interaction.followup.edit_message(message_id=interaction.message.id, embed=emb, view=view)
            except Exception:
                pass

    # ---------- comandos públicos ----------
    @commands.command(name="battle")
    async def battle_cmd(self, ctx: commands.Context):
        if ctx.author.id in self.active_battles:
            await ctx.send("Você já está em uma batalha ativa. Termine-a antes de começar outra.")
            return

        mon = await self._load_player_active_mon(ctx.author.id)
        if not mon:
            await ctx.send("Você não tem Pokémon na party. Use `!addpokemon <nome>` para adicionar um.")
            return
        if int(mon.get("current_hp") or 0) <= 0:
            await ctx.send("Seu Pokémon ativo está desmaiado. Cure-o antes de batalhar.")
            return

        st = await self._build_state(ctx)
        if not st:
            return
        self.active_battles[ctx.author.id] = st

        await ctx.send(f"Um selvagem **{st.opp_name.capitalize()}** Lv.{st.opp_level} apareceu!")
        embed = self._build_embed(st)
        view = BattleCog.BattleView(self, st)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg

# -------- setup --------
async def setup(bot: commands.Bot):
    await bot.add_cog(BattleCog(bot))
