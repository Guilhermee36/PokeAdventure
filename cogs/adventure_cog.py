# cogs/adventure_cog.py
# -*- coding: utf-8 -*-

from __future__ import annotations
from typing import Any, List, Optional, Tuple
import math
import datetime as dt

import discord
from discord.ext import commands

# utils do projeto (versão supabase logo abaixo)
from utils import event_utils  # get_permitted_destinations, get_location_info

# -----------------------
# Helpers de apresentação
# -----------------------

def slug_to_title(slug: str) -> str:
    return (slug or "—").replace("-", " ").title()

def fmt_bool(b: Optional[bool]) -> str:
    return "✅" if b else "—"

# -----------------------
# Adaptador de Player
# -----------------------

class PlayerAdapter:
    def __init__(self, raw: Any, user_id: int):
        # `raw` vindo do supabase é um dict
        get = (lambda k, d=None: raw.get(k, d)) if isinstance(raw, dict) else (lambda k, d=None: getattr(raw, k, d))
        self.id = get("discord_id") or get("id") or user_id
        self.region = get("current_region") or get("region") or "Kanto"
        self.location_api_name = get("current_location_name") or get("location_api_name") or "pallet-town"
        self.badges: int = int(get("badges", 0) or 0)
        flags_val = get("flags", []) or []
        self.flags: List[str] = list(flags_val)

    def as_display(self) -> str:
        return f"Região: **{self.region}** · Local: **{slug_to_title(self.location_api_name)}** · Badges: **{self.badges}**"


MAX_DEST_PER_PAGE = 10

class TravelViewSafe(discord.ui.View):
    def __init__(
        self,
        *,
        bot: commands.Bot,
        supabase,              # <— client do Supabase (bot.supabase)
        author_id: int,
        player: PlayerAdapter,
        mainline_only: bool,
        timeout: Optional[float] = 120.0,
    ):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.supabase = supabase
        self.author_id = author_id
        self.player = player
        self.mainline_only = mainline_only

        self.message: Optional[discord.Message] = None
        self.page = 0
        self._dest_cache: List[Tuple[str, Optional[int]]] = []
        self._persist_move = None  # injetado pelo Cog

        self._draw_static_controls()

    # ----- guard -----
    def _is_owner(self, user: discord.abc.User) -> bool:
        return int(user.id) == int(self.author_id)

    async def interaction_guard(self, interaction: discord.Interaction) -> bool:
        if not self._is_owner(interaction.user):
            await interaction.response.send_message("Só o dono desta jornada pode usar estes botões.", ephemeral=True)
            return False
        return True

    # ----- UI -----
    def _draw_static_controls(self):
        label = "Modo: História" if self.mainline_only else "Modo: Livre"
        style = discord.ButtonStyle.primary if self.mainline_only else discord.ButtonStyle.secondary

        self.toggle_button = discord.ui.Button(label=label, style=style, row=0)
        self.toggle_button.callback = self.on_toggle_mode  # type: ignore
        self.add_item(self.toggle_button)

        self.prev_btn = discord.ui.Button(emoji="◀", style=discord.ButtonStyle.secondary, row=0)
        self.next_btn = discord.ui.Button(emoji="▶", style=discord.ButtonStyle.secondary, row=0)
        self.prev_btn.callback = self.on_prev  # type: ignore
        self.next_btn.callback = self.on_next  # type: ignore
        self.add_item(self.prev_btn)
        self.add_item(self.next_btn)

        self.refresh_btn = discord.ui.Button(emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
        self.refresh_btn.callback = self.on_refresh  # type: ignore
        self.add_item(self.refresh_btn)

    def _clear_dynamic_buttons(self):
        keep = [self.toggle_button, self.prev_btn, self.next_btn, self.refresh_btn]
        self.clear_items()
        for item in keep:
            self.add_item(item)

    def _add_destination_buttons(self, page_dests: List[Tuple[str, Optional[int]]]):
        for idx, (loc_to, step) in enumerate(page_dests):
            label = slug_to_title(loc_to)
            if step is not None:
                label = f"{step:02d} · {label}"
            btn = discord.ui.Button(
                label=label[:80],
                style=discord.ButtonStyle.success if step is not None else discord.ButtonStyle.secondary,
                row=1 + (idx // 5),
            )
            async def go_cb(interaction: discord.Interaction, _loc=loc_to):
                await self.on_go(interaction, _loc)
            btn.callback = go_cb  # type: ignore
            self.add_item(btn)

    def _slice_for_page(self) -> List[Tuple[str, Optional[int]]]:
        s, e = self.page * MAX_DEST_PER_PAGE, (self.page + 1) * MAX_DEST_PER_PAGE
        return self._dest_cache[s:e]

    async def _reload_destinations(self):
        self._dest_cache = await event_utils.get_permitted_destinations(
            self.supabase,
            region=self.player.region,
            location_from=self.player.location_api_name,
            player=self.player,
            mainline_only=self.mainline_only,
        )
        max_page = max(0, (len(self._dest_cache) - 1) // MAX_DEST_PER_PAGE)
        self.page = max(0, min(self.page, max_page))

    async def _render(self, interaction: Optional[discord.Interaction] = None):
        loc_info = await event_utils.get_location_info(self.supabase, self.player.location_api_name)

        title = f"🧭 Viagem — {slug_to_title(self.player.location_api_name)}"
        desc = [self.player.as_display(), ""]
        if loc_info:
            desc.append(
                f"Tipo: **{loc_info.get('type', '—')}** · Gym: {fmt_bool(loc_info.get('has_gym'))} · Shop: {fmt_bool(loc_info.get('has_shop'))}"
            )
        desc += ["", "Escolha um destino abaixo para viajar:"]

        embed = discord.Embed(
            title=title,
            description="\n".join(desc),
            color=discord.Color.blurple(),
            timestamp=dt.datetime.utcnow(),
        ).set_footer(text="Dica: use ◀ ▶ para navegar entre páginas de destinos.")

        self._clear_dynamic_buttons()
        self._add_destination_buttons(self._slice_for_page())

        self.toggle_button.label = "Modo: História" if self.mainline_only else "Modo: Livre"
        self.toggle_button.style = discord.ButtonStyle.primary if self.mainline_only else discord.ButtonStyle.secondary
        self.prev_btn.disabled = self.page <= 0
        self.next_btn.disabled = (self.page + 1) * MAX_DEST_PER_PAGE >= len(self._dest_cache)

        if interaction:
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=self)
            else:
                await interaction.response.edit_message(embed=embed, view=self)
        else:
            if self.message:
                await self.message.edit(embed=embed, view=self)

    # ----- callbacks -----
    async def on_toggle_mode(self, interaction: discord.Interaction):
        if not await self.interaction_guard(interaction): return
        self.mainline_only = not self.mainline_only
        self.page = 0
        await self._reload_destinations()
        await self._render(interaction)

    async def on_prev(self, interaction: discord.Interaction):
        if not await self.interaction_guard(interaction): return
        if self.page > 0:
            self.page -= 1
            await self._render(interaction)

    async def on_next(self, interaction: discord.Interaction):
        if not await self.interaction_guard(interaction): return
        if (self.page + 1) * MAX_DEST_PER_PAGE < len(self._dest_cache):
            self.page += 1
            await self._render(interaction)

    async def on_refresh(self, interaction: discord.Interaction):
        if not await self.interaction_guard(interaction): return
        await self._reload_destinations()
        await self._render(interaction)

    async def on_go(self, interaction: discord.Interaction, target_slug: str):
        if not await self.interaction_guard(interaction): return
        await self._reload_destinations()
        allowed = {d[0] for d in self._dest_cache}
        if target_slug not in allowed:
            await interaction.response.send_message("Esse destino não está mais disponível. Atualizei a lista.", ephemeral=True)
            await self._render()
            return
        if callable(self._persist_move):
            await self._persist_move(self.author_id, target_slug)
        self.player.location_api_name = target_slug
        self.page = 0
        await self._reload_destinations()
        await interaction.response.defer()
        await self._render()

    async def start(self, ctx: commands.Context):
        await self._reload_destinations()
        embed = discord.Embed(
            title=f"🧭 Viagem — {slug_to_title(self.player.location_api_name)}",
            description="Carregando destinos...",
            color=discord.Color.blurple(),
        )
        self.message = await ctx.send(embed=embed, view=self)
        await self._render()

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class AdventureCog(commands.Cog):
    def __init__(self, bot: commands.Bot, supabase):
        self.bot = bot
        self.supabase = supabase

    # ----- player helpers (via Supabase) -----

    async def _load_player(self, user_id: int) -> PlayerAdapter:
        sb = self.supabase
        # 1) tenta buscar
        res = sb.table("players").select(
            "discord_id,current_region,current_location_name,badges,flags"
        ).eq("discord_id", int(user_id)).limit(1).execute()
        rows = res.data or []
        if not rows:
            # 2) cria registro mínimo
            insert = sb.table("players").insert({
                "discord_id": int(user_id),
                "current_region": "Kanto",
                "current_location_name": "pallet-town",
                "badges": 0,
                "flags": [],
            }).execute()
            rows = insert.data or []
        raw = rows[0]
        return PlayerAdapter(raw, user_id)

    async def _move_player(self, user_id: int, new_location_slug: str):
        sb = self.supabase
        sb.table("players").update({
            "current_location_name": new_location_slug
        }).eq("discord_id", int(user_id)).execute()

    # ----- comando -----

    @commands.command(name="travel", aliases=["viagem", "viajar"])
    @commands.cooldown(1, 5, type=commands.BucketType.user)
    async def travel_cmd(self, ctx: commands.Context, modo: Optional[str] = None):
        user_id = int(ctx.author.id)
        player = await self._load_player(user_id)
        modo = (modo or "historia").strip().lower()
        mainline_only = False if modo in ("livre", "free", "open") else True

        view = TravelViewSafe(
            bot=self.bot,
            supabase=self.supabase,
            author_id=user_id,
            player=player,
            mainline_only=mainline_only,
            timeout=180.0,
        )

        async def _persist_move(uid: int, loc: str):
            await self._move_player(uid, loc)
        view._persist_move = _persist_move

        await view.start(ctx)


# -------- setup para loader automático --------

async def setup(bot: commands.Bot):
    """
    O loader automático chamará apenas setup(bot).
    Aqui esperamos que você tenha definido bot.supabase antes
    de carregar a extensão.
    """
    supabase = getattr(bot, "supabase", None)
    if supabase is None:
        raise RuntimeError("AdventureCog: defina bot.supabase antes de load_extension.")
    await bot.add_cog(AdventureCog(bot, supabase))
