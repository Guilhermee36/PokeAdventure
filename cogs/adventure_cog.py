# cogs/adventure_cog.py
# -*- coding: utf-8 -*-

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
import os
import json
import discord
from discord.ext import commands

# utils do projeto (usa Supabase síncrono)
from utils import event_utils  # get_permitted_destinations, get_location_info, get_next_mainline_edge, next_gym_info, get_gym_order

MAX_DEST_PER_PAGE = 6


def slug_to_title(slug: str) -> str:
    return slug.replace("-", " ").title() if slug else "—"


def _friendly_flag_name(flag: str) -> str:
    """Mapeia algumas flags para nomes mais bonitos no UI."""
    f = (flag or "").strip().lower()
    aliases = {
        "hm_surf": "Surf",
        "hm_dive": "Dive",
        "hm_strength": "Strength",
        "hm_rock_climb": "Rock Climb",
        "hm_waterfall": "Waterfall",
        "flash": "Flash",
        "tea_event": "Chá (Tea)",
        "clear_snorlax": "Snorlax liberado",
    }
    return aliases.get(f, flag)


def _gate_summary(gate: dict) -> str:
    """Gera um texto curto com os requisitos/bloqueios do gate para mostrar na lista de destinos."""
    if not gate:
        return ""
    chunks = []
    # badges
    if gate.get("requires_badge") is not None:
        chunks.append(f"{int(gate['requires_badge'])}🏅")
    # requires_flags
    rfs = gate.get("requires_flags") or []
    if rfs:
        nice = ", ".join(_friendly_flag_name(x) for x in rfs)
        chunks.append(f"🔑 {nice}")
    # locked_until
    if gate.get("locked_until"):
        chunks.append(f"🔓 {_friendly_flag_name(str(gate['locked_until']))}")
    # blocked_by
    if gate.get("blocked_by"):
        chunks.append(f"⛔ {str(gate['blocked_by']).title()}")
    # recommended (não bloqueia)
    if gate.get("recommended"):
        chunks.append(f"💡 Recom.: {_friendly_flag_name(str(gate['recommended']))}")
    return " · Gate: " + " | ".join(chunks) if chunks else ""


class TravelViewSafe(discord.ui.View):
    """
    Viagem:
    - Embed com Próximo Passo (história) + lista de destinos
    - Select para viajar
    - Botões contextuais (curar, wild, pesca, surf)
    - 🏆 Botão de Líder do Ginásio (se a cidade tiver ginásio)
    - 🏅 Botão de Insígnias (atualiza/mostra contagem e ganha em vitória)
    - ❓ Help Travel (próximo ginásio + todos os passos)
    - Imagem por região em assets/Regions/<Região>.webp
    """
    def __init__(
        self,
        bot: commands.Bot,
        supabase: Any,
        player: "PlayerAdapter",
        mainline_only: bool = False,
        timeout: Optional[float] = 120.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.supabase = supabase
        self.player = player
        self.mainline_only = mainline_only

        self.message: Optional[discord.Message] = None
        self._dest_cache: List[dict] = []
        self._select: Optional[discord.ui.Select] = None
        self._region_img_filename: Optional[str] = None
        self._loc_info: Optional[dict] = None
        self._next_edge: Optional[dict] = None  # próxima aresta principal (step menor)

        # botões de ação (criados conforme location)
        self._btn_heal: Optional[discord.ui.Button] = None
        self._btn_wild: Optional[discord.ui.Button] = None
        self._btn_fish: Optional[discord.ui.Button] = None
        self._btn_surf: Optional[discord.ui.Button] = None

        # novos botões
        self._btn_gym: Optional[discord.ui.Button] = None
        self._btn_help: Optional[discord.ui.Button] = None
        self._btn_badges: Optional[discord.ui.Button] = None

    # ------------ lifecycle ------------

    async def start(self, ctx: commands.Context):
        # Refresca dados do player (região, localização, badges e flags) do BD
        await self._refresh_player_from_db(ctx.author.id)

        # imagem por região no primeiro envio
        region_name = (self.player.region or "Kanto").strip()
        img_path = os.path.join("assets", "Regions", f"{region_name}.webp")

        file = None
        if os.path.isfile(img_path):
            try:
                self._region_img_filename = f"{region_name}.webp"
                file = discord.File(img_path, filename=self._region_img_filename)
            except Exception:
                file = None

        # carrega destinos + UI inicial
        await self._reload_destinations()

        embed = discord.Embed(
            title=f"\U0001F9ED Viagem — {slug_to_title(self.player.location_api_name)}",
            description="Carregando destinos…",
            color=discord.Color.blurple(),
        )
        self.message = await ctx.send(embed=embed, file=file) if file else await ctx.send(embed=embed)
        await self._render()

    async def _refresh_player_from_db(self, user_id: int):
        try:
            res = (
                self.supabase.table("players")
                .select("current_region,current_location_name,badges,flags")
                .eq("discord_id", user_id)
                .limit(1)
                .execute()
            )
            rows = res.data or []
            if not rows:
                return
            row = rows[0]
            self.player.region = row.get("current_region") or "Kanto"
            self.player.location_api_name = row.get("current_location_name") or self.player.location_api_name
            self.player.badges = row.get("badges", 0) or 0
            self.player.flags = row.get("flags", []) or []
        except Exception as e:
            print(f"[TravelViewSafe:_refresh_player_from_db][WARN] {e}", flush=True)

    async def _show_error(self, e: Exception):
        if not self.message:
            return
        err = discord.Embed(
            title="\U0001F9ED Viagem — Falha ao carregar",
            description=f"Houve um erro ao consultar os destinos.\n```{e}```",
            color=discord.Color.red(),
        )
        try:
            await self.message.edit(embed=err, view=None)
        except discord.HTTPException:
            pass

    # ------------ dados ------------

    def _query_destinations_sync(self) -> List[dict]:
        return event_utils.get_permitted_destinations(
            self.supabase,
            region=self.player.region,
            location_from=self.player.location_api_name,
            player=self.player,
            mainline_only=self.mainline_only,
        )

    def _query_loc_info_sync(self) -> Optional[dict]:
        return event_utils.get_location_info(self.supabase, self.player.location_api_name)

    def _query_next_edge_sync(self) -> Optional[dict]:
        # próxima aresta principal (menor 'step' a partir do local atual)
        return event_utils.get_next_mainline_edge(self.supabase, self.player.region, self.player.location_api_name)

    async def _reload_destinations(self):
        try:
            self._dest_cache = self._query_destinations_sync()
            self._loc_info = self._query_loc_info_sync()
            self._next_edge = self._query_next_edge_sync()
        except Exception as e:
            print(f"[TravelViewSafe:_reload_destinations][ERROR] {e}", flush=True)
            self._dest_cache = []
            self._loc_info = None
            self._next_edge = None

    # ------------ helpers ------------

    def _label_for_route(self, d: dict) -> Tuple[str, Optional[str]]:
        """
        Retorna (label, desc) para a opção no Select.
        Regra:
          - se step é número => Principal — Passo X
          - se step é NULL  => Opcional
        """
        to_slug = d.get("location_to")
        label = slug_to_title(to_slug)
        step = d.get("step")
        if step is not None:
            desc = f"Principal — Passo {step}"
        else:
            desc = "Opcional"
        return label, desc

    async def _perform_travel(self, to_slug: str):
        try:
            (
                self.supabase.table("players")
                .update({"current_location_name": to_slug})
                .eq("discord_id", self.player.user_id)
                .execute()
            )
            self.player.location_api_name = to_slug
            await self.message.channel.send(f"✈️ Viajando para **{slug_to_title(to_slug)}**.")

            await self._reload_destinations()
            await self._render()
        except Exception as e:
            print(f"[TravelViewSafe:_perform_travel][ERROR] {e}", flush=True)
            await self.message.channel.send(f"Não consegui viajar agora: `{e}`")

    # ------------ features novas (gyms/badges/help) ------------

    def _has_gym_here(self) -> bool:
        """Retorna True se a location atual (cidade) tem ginásio."""
        loc = self._loc_info or {}
        return bool(loc.get("has_gym")) and (loc.get("type", "").lower() == "city")

    def _current_badges_int(self) -> int:
        b = getattr(self.player, "badges", 0) or 0
        if isinstance(b, (list, tuple, set)):
            return len(b)
        try:
            return int(b)
        except Exception:
            return 0

    def _get_next_gym_info(self) -> Optional[Dict[str, object]]:
        """Próximo ginásio baseado na região e no número de insígnias do player."""
        return event_utils.next_gym_info(self.player.region, self._current_badges_int())

    async def _increment_badge(self):
        """Incrementa a contagem de insígnias no BD e na memória."""
        new_val = self._current_badges_int() + 1
        if new_val > 8:
            new_val = 8
        try:
            (
                self.supabase.table("players")
                .update({
                    "D": new_val,
                    "wild_battles_since_badge": 0   # 🔽 reset aqui
                })
                .eq("discord_id", self.player.user_id)
                .execute()
            )
            self.player.badges = new_val
        except Exception as e:
            print(f"[TravelViewSafe:_increment_badge][ERROR] {e}", flush=True)

    async def _send_next_gym_hint(self):
        """Dica do próximo ginásio (líder, cidade, badge #) + passo mais próximo na mainline."""
        g = self._get_next_gym_info()
        if not g:
            await self.message.channel.send("🏆 Você já concluiu os ginásios desta região (ou ela não possui ginásios).")
            return

        step_txt = ""
        try:
            res = (
                self.supabase.table("routes")
                .select("location_from,location_to,step")
                .eq("region", self.player.region)
                .eq("is_mainline", True)
                .eq("location_to", g["city"])
                .order("step")
                .limit(1)
                .execute()
            )
            rows = res.data or []
            if rows and rows[0].get("step") is not None:
                step_txt = f" — Passo **{rows[0]['step']}**"
        except Exception:
            step_txt = ""

        await self.message.channel.send(
            f"👉 **Próximo ginásio:** **{g['leader']}** em **{slug_to_title(str(g['city']))}** "
            f"(Insígnia {g['badge_no']}: {g['badge_name']}){step_txt}."
        )

    async def _send_all_mainline_steps(self):
        """Lista ordenada (passo -> destino) da trilha principal da região atual."""
        try:
            res = (
                self.supabase.table("routes")
                .select("location_from,location_to,step")
                .eq("region", self.player.region)
                .eq("is_mainline", True)
                .not_.is_("step", "null")
                .order("step")
                .execute()
            )
            rows = res.data or []
            if not rows:
                await self.message.channel.send("Não encontrei passos principais cadastrados.")
                return

            lines = []
            for r in rows:
                to_name = slug_to_title(r.get("location_to"))
                lines.append(f"**Passo {int(r['step'])}** — {to_name}")
            text = "\n".join(lines[:100])
            embed = discord.Embed(
                title="\U0001F9FE\uFE0F  Todos os Passos da História (Mainline)",
                description=text,
                color=discord.Color.dark_teal(),
            )
            await self.message.channel.send(embed=embed)

        except Exception as e:
            await self.message.channel.send(f"Falha ao listar passos principais: `{e}`")

    # ------------ select / botões ------------

    def _rebuild_select(self):
        # remove select anterior, se houver
        if self._select and self._select in self.children:
            self.remove_item(self._select)

        options = []
        for idx, d in enumerate(self._dest_cache, 1):
            to_slug = d.get("location_to")
            label, desc = self._label_for_route(d)
            options.append(
                discord.SelectOption(
                    label=f"{idx}. {label}",
                    value=str(to_slug),
                    description=desc[:100] if desc else None
                )
            )

        if not options:
            self._select = None
            return

        class DestSelect(discord.ui.Select):
            def __init__(self, owner: "TravelViewSafe", options_):
                super().__init__(placeholder="Escolha um destino…", min_values=1, max_values=1, options=options_)
                self._owner = owner

            async def callback(self, interaction: discord.Interaction):
                if interaction.user.id != self._owner.player.user_id:
                    return await interaction.response.send_message("Esta viagem não é sua.", ephemeral=True)
                await interaction.response.defer()
                chosen = self.values[0]
                await self._owner._perform_travel(chosen)

        self._select = DestSelect(self, options)
        self.add_item(self._select)

    def _rebuild_action_buttons(self):
        # limpa botões antigos
        for b in [self._btn_heal, self._btn_wild, self._btn_fish, self._btn_surf, self._btn_gym, self._btn_help, self._btn_badges]:
            if b and b in self.children:
                self.remove_item(b)
        self._btn_heal = self._btn_wild = self._btn_fish = self._btn_surf = None
        self._btn_gym = self._btn_help = self._btn_badges = None

        # decide o que habilitar
        loc = self._loc_info or {}
        ltype = (loc.get("type") or "").lower()  # city/route/dungeon
        has_shop = bool(loc.get("has_shop"))     # proxy p/ "centro" (pode trocar por has_center)
        meta = loc.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}

        can_heal = has_shop or ltype == "city"
        can_wild = (ltype in ("route", "dungeon")) or bool(meta.get("grass"))
        can_fish = bool(meta.get("fishing"))
        # Surf: precisa a location permitir E o player ter a flag hm_surf
        can_surf = bool(meta.get("surf")) and ("hm_surf" in (self.player.flags or []))
        has_gym_here = self._has_gym_here()

        # === botões existentes (curar / wild / pesca / surf) ===
        if can_heal:
            self._btn_heal = discord.ui.Button(label="\U0001F3E5 Curar", style=discord.ButtonStyle.success)

            async def heal_cb(inter: discord.Interaction):
                if inter.user.id != self.player.user_id:
                    return await inter.response.send_message("Ação não é sua.", ephemeral=True)
                await inter.response.defer()

                try:
                    # Busca todos os Pokémon da party do jogador
                    res = (
                        self.supabase.table("player_pokemon")
                        .select("id,max_hp")
                        .eq("player_id", self.player.user_id)
                        .not_.is_("party_position", "null")
                        .execute()
                    )
                    rows = res.data or []

                    # Seta current_hp = max_hp para cada um
                    for r in rows:
                        self.supabase.table("player_pokemon") \
                            .update({"current_hp": r["max_hp"]}) \
                            .eq("id", r["id"]) \
                            .execute()

                    await self.message.channel.send("🧑‍⚕️ Seus Pokémon foram totalmente curados no Centro Pokémon!")
                except Exception as e:
                    await self.message.channel.send(f"Falha ao curar: `{e}`")

            self._btn_heal.callback = heal_cb
            self.add_item(self._btn_heal)


        if can_wild:
            self._btn_wild = discord.ui.Button(label="\U0001F33F Wild Area", style=discord.ButtonStyle.primary)
            async def wild_cb(inter: discord.Interaction):
                if inter.user.id != self.player.user_id:
                    return await inter.response.send_message("Ação não é sua.", ephemeral=True)
                await inter.response.defer()
                await self.message.channel.send("Você entrou na área selvagem! (placeholder)")
            self._btn_wild.callback = wild_cb
            self.add_item(self._btn_wild)

        if can_fish:
            self._btn_fish = discord.ui.Button(label="\U0001F3A3 Pescar", style=discord.ButtonStyle.secondary)
            async def fish_cb(inter: discord.Interaction):
                if inter.user.id != self.player.user_id:
                    return await inter.response.send_message("Ação não é sua.", ephemeral=True)
                await inter.response.defer()
                await self.message.channel.send("Você começou a pescar... (placeholder)")
            self._btn_fish.callback = fish_cb
            self.add_item(self._btn_fish)

        if can_surf:
            self._btn_surf = discord.ui.Button(label="\U0001F30A Surf", style=discord.ButtonStyle.secondary)
            async def surf_cb(inter: discord.Interaction):
                if inter.user.id != self.player.user_id:
                    return await inter.response.send_message("Ação não é sua.", ephemeral=True)
                await inter.response.defer()
                await self.message.channel.send("Você saiu surfando! (placeholder)")
            self._btn_surf.callback = surf_cb
            self.add_item(self._btn_surf)

        # === 🏅 Botão de Insígnias (sempre visível; atualiza label/estado) ===
        badges_label = f"🏅 Insígnias: {self._current_badges_int()}/8"
        self._btn_badges = discord.ui.Button(label=badges_label, style=discord.ButtonStyle.secondary)

        async def badges_cb(inter: discord.Interaction):
            if inter.user.id != self.player.user_id:
                return await inter.response.send_message("Ação não é sua.", ephemeral=True)
            # Recarrega do BD e atualiza a label
            await inter.response.defer()
            await self._refresh_player_from_db(self.player.user_id)
            # Re-render apenas os botões para atualizar a label
            self._rebuild_action_buttons()
            try:
                await self.message.edit(view=self)
            except Exception:
                pass
            await self.message.channel.send(f"🏅 Você tem **{self._current_badges_int()}** insígnias.")
        self._btn_badges.callback = badges_cb
        self.add_item(self._btn_badges)

        # === 🏆 Botão do Líder do Ginásio (só em cidades com ginásio) ===
        if has_gym_here:
            city_slug = (loc.get("location_api_name") or self.player.location_api_name)
            # resolve info do líder baseado NA REGIÃO
            leader = None
            badge_no = None
            badge_name = None
            for g in event_utils.get_gym_order(self.player.region):
                if g["city"] == city_slug:
                    leader, badge_no, badge_name = g["leader"], g["badge_no"], g["badge_name"]
                    break

            label = "🏆 Líder do Ginásio" if leader is None else f"🏆 Desafiar {leader}"
            self._btn_gym = discord.ui.Button(label=label, style=discord.ButtonStyle.danger)

            async def gym_cb(inter: discord.Interaction):
                if inter.user.id != self.player.user_id:
                    return await inter.response.send_message("Ação não é sua.", ephemeral=True)
                await inter.response.defer()

                # Verifica se esta cidade é o PRÓXIMO ginásio esperado
                next_g = self._get_next_gym_info()
                if not next_g:
                    return await self.message.channel.send("Esta região não possui ginásios ou você já tem 8 insígnias.")

                if str(next_g["city"]) != str(city_slug):
                    return await self.message.channel.send(
                        f"⚠️ O próximo ginásio esperado é **{next_g['leader']}** em **{slug_to_title(str(next_g['city']))}**."
                    )

                # Placeholder de batalha → vitória garante insígnia
                await self.message.channel.send(
                    f"🏆 Você desafia **{leader or 'o Líder'}** em **{slug_to_title(str(city_slug))}** "
                    f"(Insígnia {badge_no}: {badge_name})."
                )
                # Concede 1 insígnia
                await self._increment_badge()
                # Atualiza destinos (para liberar gates de 8 insignias) e UI
                await self._reload_destinations()
                self._rebuild_action_buttons()
                await self._render()
                await self.message.channel.send(f"✅ Você agora tem **{self._current_badges_int()}** insígnias!")

            self._btn_gym.callback = gym_cb
            self.add_item(self._btn_gym)

        # === ❓ Help Travel (menu de ajuda de viagem) ===
        self._btn_help = discord.ui.Button(label="❓ Help Travel", style=discord.ButtonStyle.secondary)
        async def help_cb(inter: discord.Interaction):
            if inter.user.id != self.player.user_id:
                return await inter.response.send_message("Ação não é sua.", ephemeral=True)
            view = discord.ui.View(timeout=60)

            btn_next_gym = discord.ui.Button(label="👉 Próximo Ginásio", style=discord.ButtonStyle.primary)
            btn_all_steps = discord.ui.Button(label="🧭 Mostrar Todos os Passos", style=discord.ButtonStyle.success)

            async def next_gym_cb(i2: discord.Interaction):
                if i2.user.id != self.player.user_id:
                    return await i2.response.send_message("Ação não é sua.", ephemeral=True)
                await i2.response.defer()
                await self._send_next_gym_hint()

            async def all_steps_cb(i2: discord.Interaction):
                if i2.user.id != self.player.user_id:
                    return await i2.response.send_message("Ação não é sua.", ephemeral=True)
                await i2.response.defer()
                await self._send_all_mainline_steps()

            btn_next_gym.callback = next_gym_cb
            btn_all_steps.callback = all_steps_cb
            view.add_item(btn_next_gym)
            view.add_item(btn_all_steps)

            await inter.response.send_message(
                "O que você precisa?",
                view=view,
                ephemeral=True
            )

        self._btn_help.callback = help_cb
        self.add_item(self._btn_help)

    # ------------ render ------------

    async def _render(self):
        if not self.message:
            return

        current_loc_title = slug_to_title(self.player.location_api_name)

        # monta a lista
        if not self._dest_cache:
            desc = "Nenhum destino disponível a partir daqui."
        else:
            lines = []
            for idx, d in enumerate(self._dest_cache, 1):
                to_name = slug_to_title(d.get("location_to"))
                step = d.get("step")
                principal = (step is not None)
                prefix = "🧭" if principal else "🗺️"
                gate = d.get("gate") or {}
                gate_txt = _gate_summary(gate)
                info = f"— **Passo {step}**{gate_txt}" if principal else f"— Opcional{gate_txt}"
                lines.append(f"**{idx}. {prefix} {to_name}** {info}")
            desc = "\n".join(lines)

        embed = discord.Embed(
            title=f"\U0001F9ED Viagem — {current_loc_title}",
            description=desc or "—",
            color=discord.Color.blurple(),
        )

        # Próximo passo recomendado
        if self._next_edge and self._next_edge.get("step") is not None:
            embed.add_field(
                name="👉 Próximo passo da história",
                value=f"**{slug_to_title(self._next_edge['location_to'])}** — Passo **{self._next_edge['step']}**",
                inline=False,
            )

        # imagem da região
        if self._region_img_filename:
            embed.set_image(url=f"attachment://{self._region_img_filename}")

        # (re)constrói select e botões de ação
        self._rebuild_select()
        self._rebuild_action_buttons()

        await self.message.edit(embed=embed, view=self)


# -----------------------
# PlayerAdapter mínimo (apenas campos usados aqui)
class PlayerAdapter:
    def __init__(self, user_id: int, region: str, location_api_name: str):
        self.user_id = user_id
        self.region = region
        self.location_api_name = location_api_name
        # campos opcionais usados por gates:
        self.badges = 0
        self.flags: List[str] = []


# -----------------------
# Cog

class AdventureCog(commands.Cog):
    def __init__(self, bot: commands.Bot, supabase: Any):
        self.bot = bot
        self.supabase = supabase

    # ===== Helper: carrega player do BD, aplica spawn se necessário =====
    def _load_player_from_db(self, user_id: int) -> Optional[PlayerAdapter]:
        try:
            res = (
                self.supabase.table("players")
                .select("current_region,current_location_name,badges,flags")
                .eq("discord_id", user_id)
                .limit(1)
                .execute()
            )
            rows = res.data or []
            if not rows:
                return None

            row = rows[0]
            region = row.get("current_region") or "Kanto"
            location = row.get("current_location_name")

            # se não houver location, aplica spawn da região
            if not location:
                location = event_utils.ensure_player_spawn(self.supabase, user_id, region) or event_utils.get_region_spawn(region)

            player = PlayerAdapter(user_id=user_id, region=region, location_api_name=location)
            player.badges = row.get("badges", 0) or 0
            player.flags = row.get("flags", []) or []
            return player
        except Exception as e:
            print(f"[AdventureCog:_load_player_from_db][ERROR] {e}", flush=True)
            return None

    @commands.command(name="travel", aliases=["viagem"])
    async def cmd_travel(self, ctx: commands.Context, *, apenas_principal: Optional[bool] = False):
        """
        Abre o menu de viagem. SEM fallback para Pallet:
        busca o player no BD e, se não tiver location, aplica o spawn da região.
        """
        player = self._load_player_from_db(ctx.author.id)
        if player is None:
            await ctx.send("Você ainda não tem perfil criado. Use `!setregion <Região>` para começar.")
            return

        # instancia a view
        view = TravelViewSafe(self.bot, self.supabase, player, bool(apenas_principal))
        await view.start(ctx)

    # ===============================
    # Comandos de admin / debug (give)
    # ===============================

    def _fetch_flags(self, user_id: int) -> List[str]:
        try:
            res = (
                self.supabase.table("players")
                .select("flags")
                .eq("discord_id", user_id)
                .limit(1)
                .execute()
            )
            rows = res.data or []
            flags = (rows[0] or {}).get("flags", []) if rows else []
            return list(flags or [])
        except Exception:
            return []

    def _save_flags(self, user_id: int, flags: List[str]) -> None:
        # salva único e ordenado (estético)
        unique = sorted(set(flags))
        self.supabase.table("players").update({"flags": unique}).eq("discord_id", user_id).execute()

    @commands.command(name="givebadges")
    async def give_badges(self, ctx: commands.Context, n: int):
        """Define o número de insígnias (0–8)."""
        n = max(0, min(8, int(n)))
        try:
            self.supabase.table("players").update({"badges": n}).eq("discord_id", ctx.author.id).execute()
            await ctx.send(f"🏅 Badges agora: **{n}/8**")
        except Exception as e:
            await ctx.send(f"Erro ao definir badges: `{e}`")

    @commands.command(name="giveflag")
    async def give_flag(self, ctx: commands.Context, *, flag: str):
        """Adiciona uma flag ao jogador (ex.: hm_surf, hm_dive, tea_event, clear_snorlax, flash)."""
        flag = (flag or "").strip().lower()
        if not flag:
            return await ctx.send("Informe a flag. Ex.: `!giveflag hm_surf`")
        flags = self._fetch_flags(ctx.author.id)
        if flag in flags:
            return await ctx.send(f"Flag **{flag}** já está setada.")
        flags.append(flag)
        try:
            self._save_flags(ctx.author.id, flags)
            await ctx.send(f"✅ Flag **{flag}** concedida.")
        except Exception as e:
            await ctx.send(f"Erro ao salvar flag: `{e}`")

    @commands.command(name="delflag")
    async def del_flag(self, ctx: commands.Context, *, flag: str):
        """Remove uma flag do jogador."""
        flag = (flag or "").strip().lower()
        flags = self._fetch_flags(ctx.author.id)
        if flag not in flags:
            return await ctx.send(f"Flag **{flag}** não estava setada.")
        flags = [f for f in flags if f != flag]
        try:
            self._save_flags(ctx.author.id, flags)
            await ctx.send(f"🗑️ Flag **{flag}** removida.")
        except Exception as e:
            await ctx.send(f"Erro ao salvar flag: `{e}`")

    # ===== Atalhos para seus gates atuais =====
    @commands.command(name="givesurf")
    async def give_surf(self, ctx): return await self.give_flag(ctx, flag="hm_surf")

    @commands.command(name="givedive")
    async def give_dive(self, ctx): return await self.give_flag(ctx, flag="hm_dive")

    @commands.command(name="givewaterfall")
    async def give_waterfall(self, ctx): return await self.give_flag(ctx, flag="hm_waterfall")

    @commands.command(name="givestrength")
    async def give_strength(self, ctx): return await self.give_flag(ctx, flag="hm_strength")

    @commands.command(name="giverockclimb")
    async def give_rock_climb(self, ctx): return await self.give_flag(ctx, flag="hm_rock_climb")

    @commands.command(name="giveflash")
    async def give_flash(self, ctx): return await self.give_flag(ctx, flag="flash")

    @commands.command(name="givetea")
    async def give_tea(self, ctx): return await self.give_flag(ctx, flag="tea_event")

    @commands.command(name="clearsnorlax")
    async def clear_snorlax(self, ctx): return await self.give_flag(ctx, flag="clear_snorlax")

    @commands.command(name="kitgates")
    async def kit_gates(self, ctx):
        """
        Dá todos os itens/flags que você listou:
        - hm_surf, hm_dive, hm_strength, hm_rock_climb, hm_waterfall, flash, tea_event, clear_snorlax
        """
        want = {"hm_surf", "hm_dive", "hm_strength", "hm_rock_climb", "hm_waterfall", "flash", "tea_event", "clear_snorlax"}
        flags = set(self._fetch_flags(ctx.author.id))
        if want.issubset(flags):
            return await ctx.send("Você já tem todas as flags do kit.")
        flags |= want
        try:
            self._save_flags(ctx.author.id, list(flags))
            await ctx.send("🎁 Kit de flags dos gates concedido com sucesso.")
        except Exception as e:
            await ctx.send(f"Erro ao salvar flags: `{e}`")


async def setup(bot: commands.Bot):
    supabase = getattr(bot, "supabase", None)
    if supabase is None:
        raise RuntimeError("AdventureCog: defina bot.supabase antes de carregar a extensão.")
    await bot.add_cog(AdventureCog(bot, supabase))
