# adventure_cog.py
# -*- coding: utf-8 -*-

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

import asyncio
import math
import datetime as dt

import discord
from discord.ext import commands

# utilitários do seu projeto
from utils import event_utils  # espera: get_permitted_destinations, get_location_info

# ============================================================
# Helpers (apresentação)
# ============================================================

def slug_to_title(slug: str) -> str:
    if not slug:
        return "—"
    return slug.replace("-", " ").title()

def fmt_bool(b: Optional[bool]) -> str:
    return "✅" if b else "—"

# ============================================================
# Modelo “adapter” do Player (evita depender do formato real)
# ============================================================

class PlayerAdapter:
    """
    Adapta o objeto/dict de player para a interface esperada pelo fluxo.
    Garante defaults seguros para badges/flags.
    """
    def __init__(self, raw: Any, user_id: int):
        # Em alguns casos virá como objeto com atributos; em outros, como dict
        get = (lambda k, d=None: getattr(raw, k, d)) if not isinstance(raw, dict) else (lambda k, d=None: raw.get(k, d))

        # campos (tentamos ambos os padrões)
        self.id = get("discord_id") or get("id") or user_id
        self.region = get("region") or get("current_region") or "Kanto"
        self.location_api_name = get("location_api_name") or get("current_location_name") or "pallet-town"

        # progresso
        badges_val = get("badges", 0)
        self.badges: int = int(badges_val or 0)

        flags_val = get("flags", [])
        if flags_val is None:
            flags_val = []
        self.flags: List[str] = list(flags_val)

    def as_display(self) -> str:
        return f"Região: **{self.region}** · Local: **{slug_to_title(self.location_api_name)}** · Badges: **{self.badges}**"


# ============================================================
# View/Buttons
# ============================================================

MAX_DEST_PER_PAGE = 10

class TravelViewSafe(discord.ui.View):
    def __init__(
        self,
        *,
        bot: commands.Bot,
        db,  # conector com .fetch/.fetchrow para event_utils
        author_id: int,
        player: PlayerAdapter,
        mainline_only: bool,
        timeout: Optional[float] = 120.0,
    ):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.db = db
        self.author_id = author_id
        self.player = player
        self.mainline_only = mainline_only

        self.message: Optional[discord.Message] = None

        # paginação
        self.page = 0
        self._dest_cache: List[Tuple[str, Optional[int]]] = []  # (location_to, step)

        # callback de persistência é injetado pelo Cog
        self._persist_move = None  # type: Optional[callable]

        # desenha controles “fixos”
        self._draw_static_controls()

    # ------------- permissionamento -------------
    def _is_owner(self, user: discord.abc.User) -> bool:
        return int(user.id) == int(self.author_id)

    async def interaction_guard(self, interaction: discord.Interaction) -> bool:
        if not self._is_owner(interaction.user):
            await interaction.response.send_message(
                "Só o dono desta jornada pode usar estes botões.",
                ephemeral=True
            )
            return False
        return True

    # ------------- UI building -------------

    def _draw_static_controls(self):
        # Botão alternar modo (História/Livre)
        label = "Modo: História" if self.mainline_only else "Modo: Livre"
        style = discord.ButtonStyle.primary if self.mainline_only else discord.ButtonStyle.secondary

        self.toggle_button = discord.ui.Button(label=label, style=style, row=0)
        self.toggle_button.callback = self.on_toggle_mode  # type: ignore
        self.add_item(self.toggle_button)

        # Página anterior / próxima
        self.prev_btn = discord.ui.Button(emoji="◀", style=discord.ButtonStyle.secondary, row=0)
        self.next_btn = discord.ui.Button(emoji="▶", style=discord.ButtonStyle.secondary, row=0)
        self.prev_btn.callback = self.on_prev  # type: ignore
        self.next_btn.callback = self.on_next  # type: ignore
        self.add_item(self.prev_btn)
        self.add_item(self.next_btn)

        # Refresh
        self.refresh_btn = discord.ui.Button(emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
        self.refresh_btn.callback = self.on_refresh  # type: ignore
        self.add_item(self.refresh_btn)

    def _clear_dynamic_buttons(self):
        # remove apenas os itens de destino (linhas 1..)
        keep = [self.toggle_button, self.prev_btn, self.next_btn, self.refresh_btn]
        self.clear_items()
        for item in keep:
            self.add_item(item)

    def _add_destination_buttons(self, page_dests: List[Tuple[str, Optional[int]]]):
        # cria até 10 botões de destino (linha 1..2)
        for idx, (loc_to, step) in enumerate(page_dests):
            label = slug_to_title(loc_to)
            if step is not None:
                label = f"{step:02d} · {label}"

            btn = discord.ui.Button(
                label=label[:80],  # limite de segurança
                style=discord.ButtonStyle.success if step is not None else discord.ButtonStyle.secondary,
                row=1 + (idx // 5)
            )
            # bind do destino
            async def go_cb(interaction: discord.Interaction, _loc=loc_to):
                await self.on_go(interaction, _loc)
            btn.callback = go_cb  # type: ignore
            self.add_item(btn)

    def _slice_for_page(self) -> List[Tuple[str, Optional[int]]]:
        start = self.page * MAX_DEST_PER_PAGE
        end = start + MAX_DEST_PER_PAGE
        return self._dest_cache[start:end]

    async def _reload_destinations(self):
        # recarrega do BD, aplicando gates
        self._dest_cache = await event_utils.get_permitted_destinations(
            self.db,
            region=self.player.region,
            location_api_name=self.player.location_api_name,
            player=self.player,
            mainline_only=self.mainline_only,
        )
        # Ajusta paginação dentro do range
        max_page = max(0, math.ceil(len(self._dest_cache) / MAX_DEST_PER_PAGE) - 1)
        self.page = max(0, min(self.page, max_page))

    async def _render(self, interaction: Optional[discord.Interaction] = None):
        # dados da location atual
        loc_info = await event_utils.get_location_info(
            self.db, self.player.region, self.player.location_api_name
        )
        title = f"🧭 Viagem — {slug_to_title(self.player.location_api_name)}"
        desc_lines = [
            self.player.as_display(),
            "",
        ]
        if loc_info:
            desc_lines.append(
                f"Tipo: **{loc_info.get('type', '—')}** · Gym: {fmt_bool(loc_info.get('has_gym'))} · Shop: {fmt_bool(loc_info.get('has_shop'))}"
            )
        desc_lines.append("")
        desc_lines.append("Escolha um destino abaixo para viajar:")

        embed = discord.Embed(
            title=title,
            description="\n".join(desc_lines),
            color=discord.Color.blurple(),
            timestamp=dt.datetime.utcnow()
        )
        embed.set_footer(text="Dica: use ◀ ▶ para navegar entre páginas de destinos.")

        # refaz botões dinâmicos
        self._clear_dynamic_buttons()
        page_dests = self._slice_for_page()
        self._add_destination_buttons(page_dests)

        # estado dos botões fixos
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

    # ------------- Button Callbacks -------------

    async def on_toggle_mode(self, interaction: discord.Interaction):
        if not await self.interaction_guard(interaction):
            return
        self.mainline_only = not self.mainline_only
        self.page = 0
        await self._reload_destinations()
        await self._render(interaction)

    async def on_prev(self, interaction: discord.Interaction):
        if not await self.interaction_guard(interaction):
            return
        if self.page > 0:
            self.page -= 1
            await self._render(interaction)

    async def on_next(self, interaction: discord.Interaction):
        if not await self.interaction_guard(interaction):
            return
        if (self.page + 1) * MAX_DEST_PER_PAGE < len(self._dest_cache):
            self.page += 1
            await self._render(interaction)

    async def on_refresh(self, interaction: discord.Interaction):
        if not await self.interaction_guard(interaction):
            return
        await self._reload_destinations()
        await self._render(interaction)

    async def on_go(self, interaction: discord.Interaction, target_slug: str):
        if not await self.interaction_guard(interaction):
            return

        # Revalida se o destino ainda é permitido
        await self._reload_destinations()
        allowed = {d[0] for d in self._dest_cache}
        if target_slug not in allowed:
            await interaction.response.send_message(
                "Esse destino não está mais disponível. Atualizei a lista pra você.",
                ephemeral=True,
            )
            await self._render()
            return

        # Persiste e move
        if callable(self._persist_move):
            await self._persist_move(self.author_id, target_slug)

        # Atualiza player local e UI
        self.player.location_api_name = target_slug
        self.page = 0
        await self._reload_destinations()

        await interaction.response.defer()
        await self._render()

    # ------------- lifecycle -------------

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
        # desabilita a view ao expirar
        for item in self.children:
            item.disabled = True  # type: ignore
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


# ============================================================
# Cog
# ============================================================

class AdventureCog(commands.Cog):
    """
    Cog de viagem/aventura:
    - Comando: !travel [historia|livre] (default: historia)
    - Mostra destinos paginados, com gating e persistência de movimento.
    """
    def __init__(self, bot: commands.Bot, db, player_repo=None):
        self.bot = bot
        self.db = db  # precisa expor .fetch/.fetchrow para event_utils
        self.player_repo = player_repo  # opcional; se não houver, cai no UPDATE direto

    # ----------------- Helpers de player/persistência -----------------

    async def _load_player(self, user_id: int) -> PlayerAdapter:
        """
        Busca o player pelo repositório (se houver) ou por SELECT simples.
        Adapta o payload ao modelo usado na navegação.
        """
        raw = None
        if self.player_repo and hasattr(self.player_repo, "get_or_create"):
            raw = await self.player_repo.get_or_create(user_id)

        # fallback: tenta buscar direto no BD
        if raw is None:
            row = await self.db.fetchrow(
                """
                SELECT discord_id, current_region, current_location_name, badges, flags
                FROM public.players
                WHERE discord_id = $1
                """,
                int(user_id),
            )
            if row is None:
                # cria um registro mínimo (spawn Pallet)
                await self.db.fetchrow(
                    """
                    INSERT INTO public.players (discord_id, current_region, current_location_name, badges, flags)
                    VALUES ($1, 'Kanto', 'pallet-town', 0, '[]'::jsonb)
                    RETURNING discord_id, current_region, current_location_name, badges, flags
                    """,
                    int(user_id),
                )
                row = await self.db.fetchrow(
                    """
                    SELECT discord_id, current_region, current_location_name, badges, flags
                    FROM public.players
                    WHERE discord_id = $1
                    """,
                    int(user_id),
                )
            raw = row

        return PlayerAdapter(raw, user_id)

    async def _move_player(self, user_id: int, new_location_slug: str):
        """
        Persiste a movimentação do jogador.
        Preferência: player_repo.move_to; fallback: UPDATE em players.current_location_name.
        """
        # 1) Repositório, se existir
        if self.player_repo and hasattr(self.player_repo, "move_to"):
            await self.player_repo.move_to(user_id, new_location_slug)
            return

        # 2) UPDATE direto (Supabase/asyncpg)
        await self.db.fetchrow(
            """
            UPDATE public.players
               SET current_location_name = $1,
                   updated_at = NOW()
             WHERE discord_id = $2
            RETURNING discord_id
            """,
            new_location_slug,
            int(user_id),
        )

    # ----------------- Comando -----------------

    @commands.command(name="travel", aliases=["viagem", "viajar"])
    @commands.cooldown(1, 5, type=commands.BucketType.user)
    async def travel_cmd(self, ctx: commands.Context, modo: Optional[str] = None):
        """
        Use:
          !travel           -> modo história
          !travel livre     -> modo livre
          !travel historia  -> modo história
        """
        user_id = int(ctx.author.id)
        player = await self._load_player(user_id)

        modo = (modo or "historia").strip().lower()
        mainline_only = False if modo in ("livre", "free", "open") else True

        view = TravelViewSafe(
            bot=self.bot,
            db=self.db,
            author_id=user_id,
            player=player,
            mainline_only=mainline_only,
            timeout=180.0,
        )
        # injeta a função de persistência
        async def _persist_move(uid: int, loc: str):
            await self._move_player(uid, loc)
        view._persist_move = _persist_move

        await view.start(ctx)


# ============================================================
# Setup
# ============================================================

async def setup(bot: commands.Bot, db, player_repo=None):
    """
    Registrar o cog com injeção de dependências:
    await adventure_cog.setup(bot, db, player_repo)
    """
    await bot.add_cog(AdventureCog(bot, db, player_repo))
