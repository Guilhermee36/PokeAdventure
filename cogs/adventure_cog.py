# adventure_cog.py
# Cog de aventura com navegação segura por locations/routes.
# Mantém o estilo do seu projeto: embed + botões (View), sem mudar player repo.  :contentReference[oaicite:3]{index=3}

from __future__ import annotations

import asyncio
from typing import Optional, List, Tuple

import discord
from discord.ext import commands
from discord import ui

from evolution_cog import event_utils  # funções auxiliares definidas acima  :contentReference[oaicite:4]{index=4}


def slug_to_title(s: str) -> str:
    return s.replace("-", " ").title()


class TravelViewSafe(ui.View):
    """View de viagem robusta: lida com lista vazia, gates e alternância História/Livre."""
    def __init__(self, db, player, region: str, current_loc: str, mainline_only: bool):
        super().__init__(timeout=180)
        self.db = db
        self.player = player
        self.region = region
        self.current_loc = current_loc
        self.mainline_only = mainline_only
        self.destinations: List[Tuple[str, Optional[int]]] = []
        self.message: Optional[discord.Message] = None

    async def on_timeout(self):
        for child in self.children:
            if isinstance(child, ui.Button):
                child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

    async def _reload_destinations(self):
        self.destinations = await event_utils.get_permitted_destinations(
            self.db, self.player, self.region, self.current_loc, mainline_only=self.mainline_only
        )
        self.clear_items()

        # Nenhum destino → mostra aviso e botão para alternar modo
        if not self.destinations:
            self.add_item(ui.Button(label="Sem destinos disponíveis", disabled=True))
            toggle_label = "Modo Livre" if self.mainline_only else "Modo História"
            self.add_item(ToggleModeButton(toggle_label, self))
            return

        # Cria botões de destino (limite de 10 por simplicidade)
        for loc_to, step in self.destinations[:10]:
            label = f"{slug_to_title(loc_to)}"
            if step is not None:
                label = f"[{step}] {label}"
            self.add_item(GoButton(label, loc_to, self))

        # Botão para alternar modo
        toggle_label = "Modo Livre" if self.mainline_only else "Modo História"
        self.add_item(ToggleModeButton(toggle_label, self))

    async def _make_embed(self) -> discord.Embed:
        title = f"{slug_to_title(self.current_loc)} • {self.region}"
        mode = "História" if self.mainline_only else "Livre"
        embed = discord.Embed(
            title=title,
            description=f"Modo: **{mode}**\nEscolha seu próximo destino.",
            color=discord.Color.blurple()
        )

        # Info de localização (para possíveis eventos)
        info = await event_utils.get_location_info(self.db, self.current_loc)
        if info:
            evts = event_utils.get_possible_events(info.get("type") or "route", bool(info.get("has_gym")))
            embed.add_field(
                name="Eventos possíveis",
                value="• " + "\n• ".join(evts),
                inline=False
            )

        # Lista de destinos
        if not self.destinations:
            embed.add_field(
                name="Destinos",
                value="Nenhum destino disponível (gates não cumpridos ou sem rotas).",
                inline=False
            )
        else:
            lines = []
            for loc, step in self.destinations[:10]:
                s = f"`{step:02d}` " if step is not None else ""
                lines.append(f"{s}**{slug_to_title(loc)}**")
            embed.add_field(name="Destinos", value="\n".join(lines), inline=False)

        return embed

    async def send_or_update(self, ctx_or_inter):
        embed = await self._make_embed()
        await self._reload_destinations()
        if isinstance(ctx_or_inter, discord.Interaction):
            if self.message:
                await ctx_or_inter.edit_original_response(embed=embed, view=self)
            else:
                self.message = await ctx_or_inter.followup.send(embed=embed, view=self, wait=True)
        else:
            if self.message:
                await self.message.edit(embed=embed, view=self)
            else:
                self.message = await ctx_or_inter.send(embed=embed, view=self)

    # Utilidade para persistir a movimentação (ponto de integração)
    async def _persist_move(self, user_id: int, new_location: str):
        """
        PONTO DE INTEGRAÇÃO:
        Substitua pelo seu repo/serviço de jogadores.
        Ex.: await self.db.execute("UPDATE players SET location_api_name=%s WHERE id=%s", new_location, user_id)
        ou chame PlayerRepo.move_to(user_id, new_location)
        """
        # placeholder no-op; ajuste conforme seu projeto
        pass


class GoButton(ui.Button):
    def __init__(self, label: str, target_loc: str, view_ref: TravelViewSafe):
        super().__init__(style=discord.ButtonStyle.primary, label=label, custom_id=f"go::{target_loc}")
        self.target_loc = target_loc
        self.view_ref = view_ref

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False, thinking=False)

        # Confere se o destino ainda está permitido
        current_allowed = {loc for loc, _ in self.view_ref.destinations}
        if self.target_loc not in current_allowed:
            await interaction.followup.send("Esse destino não está mais disponível. Atualizando…", ephemeral=True)
            await self.view_ref.send_or_update(interaction)
            return

        # Persiste a movimentação do jogador (integração com seu repo)
        try:
            await self.view_ref._persist_move(interaction.user.id, self.target_loc)
        except Exception:
            # se ainda não integrou, ignore silenciosamente
            pass

        # Atualiza estado da view e do embed
        self.view_ref.current_loc = self.target_loc
        await self.view_ref.send_or_update(interaction)


class ToggleModeButton(ui.Button):
    def __init__(self, label: str, view_ref: TravelViewSafe):
        super().__init__(style=discord.ButtonStyle.secondary, label=label, custom_id="toggle_mode")
        self.view_ref = view_ref

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False, thinking=False)
        self.view_ref.mainline_only = not self.view_ref.mainline_only
        await self.view_ref.send_or_update(interaction)


class AdventureCog(commands.Cog):
    """
    Cog de Aventura:
    - Comando `travel` para navegar no mundo por routes/locations de forma segura.
    - NÃO altera seu módulo de players (integração por método privado).
    """
    def __init__(self, bot: commands.Bot, db, player_repo):
        """
        bot: instância do discord.py
        db: conector assíncrono com .fetch/.fetchrow (ex.: asyncpg / supabase-async)
        player_repo: serviço existente do seu projeto (não alterado)
            - esperado: await player_repo.get_or_create(user_id)
            - o objeto player deve ter: region (str), location_api_name (str),
              badges (int ou lista), flags (lista) se existirem.
        """
        self.bot = bot
        self.db = db
        self.player_repo = player_repo

    # ---------- Integrações privadas (não mudam seu players) ----------

    async def _get_player(self, user_id: int):
        """
        Usa seu repositório existente de players.  :contentReference[oaicite:5]{index=5}
        """
        return await self.player_repo.get_or_create(user_id)

    async def _move_player(self, user_id: int, new_location: str):
        """
        Atualiza a localização do player usando seu repositório (sem mudar contrato).
        Se seu repo tiver outro nome de método, ajuste aqui.
        """
        # Exemplos possíveis:
        # await self.player_repo.move_to(user_id, new_location)
        # ou:
        # await self.db.execute("UPDATE players SET location_api_name=%s WHERE user_id=%s", new_location, user_id)
        try:
            await self.player_repo.move_to(user_id, new_location)  # se existir
        except AttributeError:
            # fallback: tente uma atualização direta via DB, se fizer sentido no seu projeto
            await self.db.execute(
                "UPDATE players SET location_api_name=%s WHERE user_id=%s",
                new_location,
                user_id,
            )

    # ---------- Comandos públicos ----------

    @commands.command(name="travel")
    async def cmd_travel(self, ctx: commands.Context, mode: Optional[str] = None):
        """
        Mostra destinos a partir da location atual.
        Ex.: !travel            -> modo Livre
             !travel historia   -> modo História (segue is_mainline/step)
        """
        player = await self._get_player(ctx.author.id)
        region = getattr(player, "region", None) or "Kanto"
        current_loc = getattr(player, "location_api_name", None) or "pallet-town"
        mainline_only = (mode or "").lower() in ("historia", "história", "story")

        view = TravelViewSafe(self.db, player, region, current_loc, mainline_only)

        # injeta integrador de movimentação na própria view
        async def _persist_move(user_id: int, new_loc: str):
            await self._move_player(user_id, new_loc)
        view._persist_move = _persist_move  # type: ignore

        await view.send_or_update(ctx)


# Setup padrão do discord.py
async def setup(bot: commands.Bot, db, player_repo):
    """
    Chame em seu loader passando `db` e `player_repo` do seu projeto:
    await adventure_cog.setup(bot, db, player_repo)
    """
    await bot.add_cog(AdventureCog(bot, db, player_repo))
