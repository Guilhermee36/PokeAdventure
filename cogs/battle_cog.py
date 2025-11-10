# cogs/battle_cog.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import math
import random
from typing import Optional, List, Dict, Any, Tuple

import discord
from discord.ext import commands
from supabase import create_client, Client

# Utils do projeto
import utils.pokeapi_service as pokeapi  # get_pokemon_data, get_pokemon_species_data, get_total_xp_for_level, calculate_stats_for_level
from utils import battle_utils  # regras puras (dano, tipos, captura, hp bar)
# reaproveita a mesma função de adicionar Pokémon já usada no fluxo de starter / addpokemon
from cogs.player_cog import add_pokemon_to_player  # :contentReference[oaicite:4]{index=4}

# =========================
# Supabase helper (mesmo padrão do projeto)
# =========================
def get_supabase_client() -> Client:
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY")
    return create_client(url, key)

# =========================
# Config / Constantes
# =========================
LEVEL_CAP = 100
HAPPINESS_GAIN_ON_WIN = 2
HAPPINESS_CAP = 255
# Oponente default (selvagem de teste). Você pode variar por localização depois.
DEFAULT_WILD = "pidgey"

# =========================
# Estado de batalha
# =========================
class BattleState:
    def __init__(self, user_id: int, seed: Optional[int] = None):
        self.user_id = user_id
        self.rng = random.Random(seed or random.randrange(1, 10**9))
        self.turn = 1
        self.logs: List[str] = []

        # Player active mon (snapshot de BD)
        self.player_mon: Dict[str, Any] = {}
        self.player_types: List[str] = []
        self.player_moves: List[Dict[str, Any]] = []  # [{name,type,power,category}]
        # Opponent (API-based)
        self.opp_name: str = DEFAULT_WILD
        self.opp_level: int = 5
        self.opp_types: List[str] = []
        self.opp_stats: Dict[str, int] = {}  # {"max_hp":..,"attack":..,"defense":..,"special_attack":..,"special_defense":..,"speed":..}
        self.opp_hp: int = 1
        self.opp_base_exp: int = 50
        self.opp_capture_rate: int = 255
        self.opp_sprite_url: Optional[str] = None

        # Rendering convenience
        self.player_sprite_url: Optional[str] = None

    def short_log(self) -> str:
        # mostra as últimas 2–3 entradas
        return "\n".join(self.logs[-3:]) if self.logs else "—"

# =========================
# Helpers BD
# =========================
def fetch_active_party_mon(supabase: Client, player_id: int) -> Optional[dict]:
    try:
        res = (
            supabase.table("player_pokemon")
            .select("*")
            .eq("player_id", player_id)
            .not_.is_("party_position", "null")
            .order("party_position")
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return dict(rows[0]) if rows else None
    except Exception as e:
        print(f"[Battle] erro party: {e}", flush=True)
        return None

def update_player_mon_hp(supabase: Client, mon_id: str, new_hp: int):
    try:
        supabase.table("player_pokemon").update({"current_hp": max(0, int(new_hp))}).eq("id", mon_id).execute()
    except Exception as e:
        print(f"[Battle] falha update HP: {e}", flush=True)

def persist_rewards_levelups(
    supabase: Client,
    mon_row: dict,
    reward_xp: int,
    happiness_gain: int = HAPPINESS_GAIN_ON_WIN,
) -> Tuple[dict, int]:
    """
    Aplica XP total, verifica level-up (usando growth-rate da espécie), recalcula stats se subir,
    e aplica +happiness (cap 255). Retorna (payload_update_salvo, new_level).
    """
    current_level = int(mon_row.get("current_level") or 1)
    current_xp = int(mon_row.get("current_xp") or 0)
    new_total_xp = current_xp + max(0, int(reward_xp))

    # species → growth-rate
    species = mon_row.get("pokemon_api_name")
    species_data = None
    if species:
        species_data = None
        try:
            species_data = None
            species_data = None
        except Exception:
            pass
        species_data = None
    species_data = None
    # pegar species corretamente
    sdata = None
    try:
        sdata = pokeapi.get_pokemon_species_data  # para mypy
    except Exception:
        pass

    # Busca species de verdade
    import asyncio
    async def _go() -> Tuple[int, Optional[dict]]:
        sp = await pokeapi.get_pokemon_species_data(mon_row["pokemon_api_name"])
        return (current_level, sp)
    # Como estamos em sync, rodamos via loop atual
    loop = None
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        pass
    if loop and loop.is_running():
        # estamos em um contexto async, então só marca para fora
        pass

    # fazemos tudo async dentro do Cog (onde chamamos)
    # Aqui apenas retornamos dados necessários; a função async estará no Cog.

    return {}, current_level  # placeholder (não usado aqui nesta versão síncrona)


# =========================
# Battle Cog
# =========================
class BattleCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.supabase = get_supabase_client()
        # uma batalha por jogador
        self.active_battles: Dict[int, BattleState] = {}

    # ---------- util async ----------

    async def _load_player_active_mon(self, user_id: int) -> Optional[dict]:
        row = fetch_active_party_mon(self.supabase, user_id)
        return row

    async def _load_move_info(self, move_name: str) -> Dict[str, Any]:
        # pega type/category/power do move via API
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
            # fallback
            result = [{"name": "tackle", "type": "normal", "power": 40, "category": "physical"}]
        return result

    async def _build_state(self, ctx: commands.Context) -> Optional[BattleState]:
        mon = await self._load_player_active_mon(ctx.author.id)
        if not mon:
            await ctx.send("Você não tem Pokémon na party. Use `!addpokemon` para adicionar um.")
            return None

        # monta estado
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
        opp_species = await pokeapi.get_pokemon_species_data(opp_data["species"]["name"]) if opp_data else None
        st.opp_types = [t["type"]["name"] for t in (opp_data or {}).get("types", [])] if opp_data else []
        st.opp_sprite_url = (opp_data or {}).get("sprites", {}).get("other", {}).get("official-artwork", {}).get("front_default") or (opp_data or {}).get("sprites", {}).get("front_default")
        st.opp_base_exp = int((opp_data or {}).get("base_experience") or 50)
        st.opp_capture_rate = int((opp_species or {}).get("capture_rate") or 255)

        # stats do oponente calculados para o nível
        base_stats = (opp_data or {}).get("stats", [])
        st.opp_stats = pokeapi.calculate_stats_for_level(base_stats, st.opp_level)
        st.opp_hp = int(st.opp_stats.get("max_hp", 10))

        # log inicial
        st.logs.append(f"Um selvagem **{st.opp_name.capitalize()}** Lv.{st.opp_level} apareceu!")
        return st

    async def _get_sprite_url(self, name: str, shiny: bool = False) -> Optional[str]:
        data = await pokeapi.get_pokemon_data(name)
        if not data:
            return None
        if shiny:
            return data["sprites"]["front_shiny"] or data["sprites"]["other"]["official-artwork"]["front_shiny"]
        return data["sprites"]["front_default"] or data["sprites"]["other"]["official-artwork"]["front_default"]

    def _hp_texts(self, st: BattleState) -> Tuple[str, str]:
        # Player
        php = int(st.player_mon.get("current_hp") or 1)
        pmax = int(st.player_mon.get("max_hp") or 1)
        player_hp_line, _ = battle_utils.hp_bar(php, pmax)
        # Opp
        oline, _ = battle_utils.hp_bar(st.opp_hp, int(st.opp_stats.get("max_hp", 1)))
        return player_hp_line, oline

    async def _reward_on_win(self, st: BattleState) -> Tuple[int, int]:
        """Retorna (reward_xp, new_total_xp) e persiste XP/happiness/level/stats no BD."""
        level = int(st.player_mon["current_level"])
        # fórmula simples: base_exp * level / 7
        reward_xp = max(1, math.floor((st.opp_base_exp * max(1, level)) / 7))

        # calcular level-ups pela growth-rate da espécie do SEU Pokémon
        species = await pokeapi.get_pokemon_species_data(st.player_mon["pokemon_api_name"])
        growth_url = (species or {}).get("growth_rate", {}).get("url")
        current_xp = int(st.player_mon.get("current_xp") or 0)
        new_total_xp = current_xp + reward_xp

        # checar thresholds até cap 100
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

        # recalcular stats se subir
        update_payload: Dict[str, Any] = {
            "current_xp": new_total_xp,
            "happiness": min(HAPPINESS_CAP, int(st.player_mon.get("happiness") or 0) + HAPPINESS_GAIN_ON_WIN),
        }
        if target_level > current_level:
            pkmn_data = await pokeapi.get_pokemon_data(st.player_mon["pokemon_api_name"])
            new_stats = pokeapi.calculate_stats_for_level((pkmn_data or {}).get("stats", []), target_level)
            # HP atual aumenta pela diferença do novo max_hp, sem ultrapassar
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

        # persistir
        self.supabase.table("player_pokemon").update(update_payload).eq("id", st.player_mon["id"]).execute()
        # também atualizar o snapshot em memória (para mostrar no embed final)
        st.player_mon.update(update_payload)
        return reward_xp, new_total_xp

    # ---------- Render ----------

    def _build_embed(self, st: BattleState) -> discord.Embed:
        player_hp_line, opp_hp_line = self._hp_texts(st)
        title = f"⚔️ Batalha Selvagem — Turno {st.turn}"
        emb = discord.Embed(title=title, description=st.short_log(), color=discord.Color.blurple())
        emb.add_field(name="Seu Pokémon",
                      value=f"{st.player_mon.get('nickname', st.player_mon.get('pokemon_api_name','?')).capitalize()} "
                            f"(Lv. {st.player_mon.get('current_level', 1)})\n{player_hp_line}",
                      inline=False)
        emb.add_field(name="Oponente",
                      value=f"{st.opp_name.capitalize()} (Lv. {st.opp_level})\n{opp_hp_line}",
                      inline=False)
        if st.opp_sprite_url:
            emb.set_image(url=st.opp_sprite_url)
        if st.player_sprite_url:
            emb.set_thumbnail(url=st.player_sprite_url)
        return emb

    # ---------- Views / UI ----------

    class BattleView(discord.ui.View):
        def __init__(self, cog: "BattleCog", st: BattleState):
            super().__init__(timeout=120)
            self.cog = cog
            self.st = st

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self.st.user_id:
                await interaction.response.send_message("Esta batalha não é sua.", ephemeral=True)
                return False
            return True

        @discord.ui.button(label="Lutar", style=discord.ButtonStyle.danger)
        async def fight(self, interaction: discord.Interaction, button: discord.ui.Button):
            # Construir view de moves
            mv_view = discord.ui.View(timeout=90)
            # até 4 moves
            for mv in (self.st.player_moves or [])[:4]:
                label = f"{mv['name'].capitalize()} • {mv['type'].upper()}"
                b = discord.ui.Button(label=label, style=discord.ButtonStyle.primary)
                async def _mkcb(i: discord.Interaction, move=mv):
                    await self.cog._on_player_move(i, self.st, move)
                b.callback = _mkcb
                mv_view.add_item(b)

            # botão voltar
            back = discord.ui.Button(label="Voltar", style=discord.ButtonStyle.secondary)
            async def _back(i: discord.Interaction):
                await i.response.edit_message(view=BattleCog.BattleView(self.cog, self.st))
            back.callback = _back
            mv_view.add_item(back)

            await interaction.response.edit_message(view=mv_view)

        @discord.ui.button(label="Trocar", style=discord.ButtonStyle.primary)
        async def switch(self, interaction: discord.Interaction, button: discord.ui.Button):
            # (v1) apenas mensagem: “troca gasta turno” — futura party select pode ser plugada
            await interaction.response.send_message("Troca de Pokémon ainda será ligada à sua party completa (v2). Por ora, mantenha o ativo.", ephemeral=True)

        @discord.ui.button(label="Bolsa", style=discord.ButtonStyle.success)
        async def bag(self, interaction: discord.Interaction, button: discord.ui.Button):
            # Captura com Poké Ball
            ball_btn = discord.ui.Button(label="Poké Ball", style=discord.ButtonStyle.success, emoji="🧶")
            v = discord.ui.View(timeout=60)

            async def _cap(i: discord.Interaction):
                await self.cog._on_player_capture(i, self.st)
            ball_btn.callback = _cap
            v.add_item(ball_btn)

            back = discord.ui.Button(label="Voltar", style=discord.ButtonStyle.secondary)
            async def _back(i: discord.Interaction):
                await i.response.edit_message(view=BattleCog.BattleView(self.cog, self.st))
            back.callback = _back
            v.add_item(back)

            await interaction.response.edit_message(view=v)

        @discord.ui.button(label="Fugir", style=discord.ButtonStyle.secondary)
        async def run(self, interaction: discord.Interaction, button: discord.ui.Button):
            # Fugir 100% por enquanto
            await interaction.response.defer()
            await self.cog._end_battle(interaction, self.st, escaped=True)

    # ---------- Turn resolution ----------

    async def _on_player_move(self, interaction: discord.Interaction, st: BattleState, move: Dict[str, Any]):
        await interaction.response.defer()
        # desabilita UI
        try:
            await interaction.edit_original_response(view=None)
        except Exception:
            pass

        # 1) Player ataca (sem prioridade/esquiva por ora)
        dmg1, msg1 = await self._resolve_attack(
            attacker="player", st=st, move=move
        )

        # 2) Se oponente ainda vivo, ele ataca com um golpe simples (tackle/quick-attack se existir)
        if st.opp_hp > 0:
            opp_move = await self._choose_ai_move(st)
            dmg2, msg2 = await self._resolve_attack(attacker="opp", st=st, move=opp_move)
        else:
            dmg2, msg2 = 0, None

        # 3) Checa fim
        ended = False
        if st.opp_hp <= 0:
            st.logs.append(f"{st.opp_name.capitalize()} desmaiou!")
            # Vitória → recompensa
            reward_xp, _ = await self._reward_on_win(st)
            st.logs.append(f"Você ganhou **{reward_xp} XP** e +{HAPPINESS_GAIN_ON_WIN} de amizade.")
            ended = True

        # Player pode cair (não persistimos oponente, mas HP do player sim)
        p_hp = int(st.player_mon["current_hp"])
        if p_hp <= 0:
            st.logs.append(f"Seu Pokémon desmaiou!")
            ended = True

        # Render
        emb = self._build_embed(st)
        if ended:
            await interaction.followup.edit_message(message_id=interaction.message.id, embed=emb, view=None)
            # fim
            await self._end_battle(interaction, st, escaped=False, finished=True)
            return
        else:
            # segue batalha
            st.turn += 1
            await interaction.followup.edit_message(message_id=interaction.message.id, embed=emb, view=self.BattleView(self, st))

    async def _resolve_attack(self, attacker: str, st: BattleState, move: Dict[str, Any]) -> Tuple[int, Optional[str]]:
        if attacker == "player":
            # Player -> Opp
            category = (move.get("category") or "physical").lower()
            a_atk = int(st.player_mon["attack"] if category == "physical" else st.player_mon["special_attack"])
            d_def = int(st.opp_stats["defense"] if category == "physical" else st.opp_stats["special_defense"])
            dmg, eff, stab = battle_utils.calc_damage(
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
            line = f"{st.player_mon.get('nickname', st.player_mon['pokemon_api_name']).capitalize()} usou **{move['name'].capitalize()}**! "
            if eff_txt:
                line += eff_txt + " "
            line += f"Causou {dmg} de dano."
            st.logs.append(line)
            return dmg, eff_txt
        else:
            # Opp -> Player
            # escolher categoria e power do golpe do oponente
            category = (move.get("category") or "physical").lower()
            a_atk = int(st.opp_stats["attack"] if category == "physical" else st.opp_stats["special_attack"])
            d_def = int(st.player_mon["defense"] if category == "physical" else st.player_mon["special_defense"])
            dmg, eff, stab = battle_utils.calc_damage(
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
            line = f"O {st.opp_name.capitalize()} usou **{move['name'].capitalize()}**! "
            if eff_txt:
                line += eff_txt + " "
            line += f"Você levou {dmg} de dano."
            st.logs.append(line)
            return dmg, eff_txt

    async def _choose_ai_move(self, st: BattleState) -> Dict[str, Any]:
        # simples: tenta um set padrão de golpes comuns, senão "tackle"
        for cand in ["gust", "quick-attack", "tackle"]:
            info = await self._load_move_info(cand)
            if info and info.get("power"):
                return {"name": info["name"], "type": info["type"], "power": info["power"], "category": info["damage_class"]["name"]}
        return {"name": "tackle", "type": "normal", "power": 40, "category": "physical"}

    async def _on_player_capture(self, interaction: discord.Interaction, st: BattleState):
        await interaction.response.defer()
        # chance
        chance = battle_utils.capture_chance(
            base_capture_rate=st.opp_capture_rate,
            wild_max_hp=int(st.opp_stats.get("max_hp", 1)),
            wild_current_hp=st.opp_hp,
            ball_mult=1.0, status_mult=1.0,
        )
        success = battle_utils.attempt_capture(st.rng, chance)
        if success:
            st.logs.append("Jogou uma Poké Ball… Capturou com sucesso! 🎉")
            # inserir no BD usando o fluxo padrão do projeto
            res = await add_pokemon_to_player(
                player_id=st.user_id,
                pokemon_api_name=st.opp_name,
                level=st.opp_level,
                captured_at="Batalha selvagem",
            )
            if not res.get("success"):
                st.logs.append(f"(Aviso) Falha ao registrar captura: {res.get('error')}")
            # fim da batalha (vitória por captura) — não dá XP adicional
            emb = self._build_embed(st)
            await interaction.followup.edit_message(message_id=interaction.message.id, embed=emb, view=None)
            await self._end_battle(interaction, st, escaped=False, finished=True)
        else:
            st.logs.append("A Poké Ball balançou… mas o Pokémon escapou!")
            # IA age (turno segue com a ação do oponente)
            opp_move = await self._choose_ai_move(st)
            await self._resolve_attack(attacker="opp", st=st, move=opp_move)
            st.turn += 1
            emb = self._build_embed(st)
            await interaction.followup.edit_message(message_id=interaction.message.id, embed=emb, view=self.BattleView(self, st))

    async def _end_battle(self, interaction: discord.Interaction, st: BattleState, escaped: bool, finished: bool = False):
        # limpeza
        self.active_battles.pop(st.user_id, None)
        if escaped:
            st.logs.append("Você fugiu da batalha.")
        # editar embed final (se ainda não editamos)
        try:
            emb = self._build_embed(st)
            await interaction.followup.edit_message(message_id=interaction.message.id, embed=emb, view=None)
        except Exception:
            pass

    # ---------- comando público ----------

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

        embed = self._build_embed(st)
        msg = await ctx.send(embed=embed, view=self.BattleView(self, st))

async def setup(bot: commands.Bot):
    await bot.add_cog(BattleCog(bot))