# cogs/adventure_cog.py
# -*- coding: utf-8 -*-

from __future__ import annotations
from typing import Any, List, Optional
import math
import discord
from discord.ext import commands

# utils do projeto (usa Supabase)
from utils import event_utils  # get_permitted_destinations, get_location_info

MAX_DEST_PER_PAGE = 6


def slug_to_title(slug: str) -> str:
    return slug.replace("-", " ").title() if slug else "—"


class TravelViewSafe(discord.ui.View):
    """
    View segura para o fluxo de viagem.
    - Sempre envia um embed imediatamente (feedback ao usuário)
    - Carrega destinos de forma resiliente (try/except)
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
        self.page: int = 0
        self._dest_cache: List[dict] = []

    # ------------ lifecycle ------------

    async def start(self, ctx: commands.Context):
        # 1) Mostra algo na tela imediatamente
        embed = discord.Embed(
            title=f"🧭 Viagem — {slug_to_title(self.player.location_api_name)}",
            description="Carregando destinos...",
            color=discord.Color.blurple(),
        )
        self.message = await ctx.send(embed=embed, view=self)

        # 2) Tenta carregar e renderizar
        try:
            await self._reload_destinations()
            await self._render()
        except Exception as e:
            print(f"[TravelViewSafe:start][ERROR] {e}", flush=True)
            await self._show_error(e)

    async def _show_error(self, e: Exception):
        if not self.message:
            return
        err = discord.Embed(
            title="🧭 Viagem — Falha ao carregar",
            description=f"Houve um erro ao consultar os destinos.\n```{e}```",
            color=discord.Color.red(),
        )
        try:
            await self.message.edit(embed=err, view=None)
        except discord.HTTPException:
            pass

    # ------------ dados ------------

    async def _reload_destinations(self):
        """
        IMPORTANTE: event_utils usa cliente síncrono, então NÃO usar await.
        """
        try:
            print(
                "[TravelViewSafe:_reload_destinations:BEGIN]",
                "region=", self.player.region,
                "from=", self.player.location_api_name,
                "mainline_only=", self.mainline_only,
                flush=True,
            )
            # chamada síncrona:
            self._dest_cache = event_utils.get_permitted_destinations(
                self.supabase,
                region=self.player.region,
                location_from=self.player.location_api_name,
                player=self.player,
                mainline_only=self.mainline_only,
            )
            print(
                "[TravelViewSafe:_reload_destinations:END]",
                "type=", type(self._dest_cache),
                "len=", len(self._dest_cache),
                "sample=", self._dest_cache[:2],
                flush=True,
            )
        except Exception as e:
            print(f"[TravelViewSafe:_reload_destinations][ERROR] {e}", flush=True)
            # Se algo der errado, não quebra a view inteira
            self._dest_cache = []

        max_page = max(0, (max(len(self._dest_cache), 1) - 1) // MAX_DEST_PER_PAGE)
        self.page = max(0, min(self.page, max_page))

    # ------------ UI helpers ------------

    def _page_slice(self) -> List[dict]:
        i0 = self.page * MAX_DEST_PER_PAGE
        i1 = i0 + MAX_DEST_PER_PAGE
        return self._dest_cache[i0:i1]

    async def _render(self):
        if not self.message:
            return

        current_loc_title = slug_to_title(self.player.location_api_name)

        if not self._dest_cache:
            desc = "Nenhum destino disponível a partir daqui."
        else:
            lines = []
            for idx, d in enumerate(self._page_slice(), 1):
                try:
                    to_name = slug_to_title(d.get("location_to"))
                    step = d.get("step")
                    gate = d.get("gate")
                    badge = " (rota principal)" if d.get("is_mainline") else ""
                    gate_txt = f" — gate: `{gate}`" if gate else ""
                    step_txt = f" — passo {step}" if step is not None else ""
                    lines.append(f"**{idx}.** {to_name}{badge}{step_txt}{gate_txt}")
                except Exception as e:
                    print(f"[TravelViewSafe:_render][ERROR item] {e} d={d}", flush=True)
            desc = "\n".join(lines)

        total_pages = max(1, math.ceil(len(self._dest_cache) / MAX_DEST_PER_PAGE))
        embed = discord.Embed(
            title=f"🧭 Viagem — {current_loc_title}",
            description=desc or "—",
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"Página {self.page + 1} / {total_pages}")
        await self.message.edit(embed=embed, view=self)

    # ------------ botões ------------

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player.user_id:
            return await interaction.response.send_message("Esta viagem não é sua.", ephemeral=True)
        self.page = max(0, self.page - 1)
        await interaction.response.defer()
        await self._render()

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player.user_id:
            return await interaction.response.send_message("Esta viagem não é sua.", ephemeral=True)
        max_page = max(0, (max(len(self._dest_cache), 1) - 1) // MAX_DEST_PER_PAGE)
        self.page = min(max_page, self.page + 1)
        await interaction.response.defer()
        await self._render()


# -----------------------
# PlayerAdapter mínimo (apenas campos usados aqui)
class PlayerAdapter:
    def __init__(self, user_id: int, region: str, location_api_name: str):
        self.user_id = user_id
        self.region = region
        self.location_api_name = location_api_name
        # campos opcionais usados por gates:
        self.badges = 0
        self.flags: list[str] = []


# -----------------------
# Cog

class AdventureCog(commands.Cog):
    def __init__(self, bot: commands.Bot, supabase: Any):
        self.bot = bot
        self.supabase = supabase

    @commands.command(name="travel", aliases=["viagem"])
    async def cmd_travel(self, ctx: commands.Context, *, apenas_principal: Optional[bool] = False):
        """
        Abre o menu de viagem para a location atual do jogador.
        Aqui usamos um player "stub" apenas para teste.
        """
        # >>> Troque isso pelo seu mecanismo real de player <<<
        player = getattr(ctx, "player", None)
        if player is None:
            player = PlayerAdapter(
                user_id=ctx.author.id,
                region="Kanto",
                location_api_name="pallet-town",
            )

        print(f"[AdventureCog:cmd_travel] user={ctx.author.id} region={player.region} "
              f"loc={player.location_api_name} mainline_only={apenas_principal}", flush=True)

        view = TravelViewSafe(self.bot, self.supabase, player, bool(apenas_principal))
        await view.start(ctx)


# -------- setup para loader automático --------

async def setup(bot: commands.Bot):
    """
    O loader automático chamará apenas setup(bot).
    Aqui esperamos que você tenha definido bot.supabase antes de carregar a extensão.
    """
    supabase = getattr(bot, "supabase", None)
    if supabase is None:
        raise RuntimeError("AdventureCog: defina bot.supabase antes de carregar a extensão.")
    await bot.add_cog(AdventureCog(bot, supabase))
