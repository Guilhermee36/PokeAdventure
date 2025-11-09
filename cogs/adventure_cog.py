# cogs/adventure_cog.py
# -*- coding: utf-8 -*-

from __future__ import annotations
from typing import Any, List, Optional
import math
import os
import discord
from discord.ext import commands

# utils do projeto (usa Supabase síncrono)
from utils import event_utils  # get_permitted_destinations, get_location_info

MAX_DEST_PER_PAGE = 6


def slug_to_title(slug: str) -> str:
    return slug.replace("-", " ").title() if slug else "—"


class TravelViewSafe(discord.ui.View):
    """
    Viagem:
    - Embed com Próximo Passo (história) + lista de destinos
    - Select para viajar
    - Botões contextuais (curar, wild, pesca, surf) conforme a location
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

    # ------------ lifecycle ------------

    async def start(self, ctx: commands.Context):
        # imagem por região no primeiro envio
        region_name = (self.player.region or "Kanto").strip()
        img_path = os.path.join("assets", "Regions", f"{region_name}.webp")

        file = None
        if os.path.isfile(img_path):
            try:
                self._region_img_filename = f"{region_name}.webp"
                file = discord.File(img_path, filename=self._region_img_filename)
            except Exception as e:
                print(f"[TravelViewSafe:start][WARN] falha ao anexar imagem: {e}", flush=True)

        embed = discord.Embed(
            title=f"🧭 Viagem — {slug_to_title(self.player.location_api_name)}",
            description="Carregando destinos...",
            color=discord.Color.blurple(),
        )
        if self._region_img_filename:
            embed.set_image(url=f"attachment://{self._region_img_filename}")

        self.message = await ctx.send(embed=embed, view=self, file=file) if file else await ctx.send(embed=embed, view=self)

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

    def _label_for_route(self, d: dict) -> tuple[str, Optional[str]]:
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
            # Atualiza BD
            (
                self.supabase.table("players")
                .update({"current_location_name": to_slug})
                .eq("discord_id", self.player.user_id)
                .execute()
            )
            # Atualiza memória
            self.player.location_api_name = to_slug

            await self.message.channel.send(f"✈️ Viajando para **{slug_to_title(to_slug)}**...")

            await self._reload_destinations()
            await self._render()
        except Exception as e:
            print(f"[TravelViewSafe:_perform_travel][ERROR] {e}", flush=True)
            await self.message.channel.send(f"Não consegui viajar agora: `{e}`")

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
                    value=to_slug,
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
        for b in [self._btn_heal, self._btn_wild, self._btn_fish, self._btn_surf]:
            if b and b in self.children:
                self.remove_item(b)
        self._btn_heal = self._btn_wild = self._btn_fish = self._btn_surf = None

        # decide o que habilitar
        loc = self._loc_info or {}
        ltype = (loc.get("type") or "").lower()  # city/route/dungeon
        has_shop = bool(loc.get("has_shop"))     # proxy p/ "centro" (pode trocar depois por has_center)
        meta = loc.get("metadata") or {}
        if isinstance(meta, str):
            try:
                import json; meta = json.loads(meta)
            except Exception:
                meta = {}

        can_heal = has_shop or ltype == "city"
        can_wild = (ltype in ("route", "dungeon")) or bool(meta.get("grass"))
        can_fish = bool(meta.get("fishing"))
        can_surf = bool(meta.get("surf"))

        # cria botões
        if can_heal:
            self._btn_heal = discord.ui.Button(label="🏥 Curar", style=discord.ButtonStyle.success)
            async def heal_cb(inter: discord.Interaction):
                if inter.user.id != self.player.user_id:
                    return await inter.response.send_message("Ação não é sua.", ephemeral=True)
                await inter.response.defer()
                # aqui você pode chamar sua lógica real; por enquanto feedback
                await self.message.channel.send("Seus Pokémon foram curados no Centro Pokémon!")
            self._btn_heal.callback = heal_cb
            self.add_item(self._btn_heal)

        if can_wild:
            self._btn_wild = discord.ui.Button(label="🌿 Wild Area", style=discord.ButtonStyle.primary)
            async def wild_cb(inter: discord.Interaction):
                if inter.user.id != self.player.user_id:
                    return await inter.response.send_message("Ação não é sua.", ephemeral=True)
                await inter.response.defer()
                await self.message.channel.send("Você entrou na área selvagem! (placeholder)")
            self._btn_wild.callback = wild_cb
            self.add_item(self._btn_wild)

        if can_fish:
            self._btn_fish = discord.ui.Button(label="🎣 Pescar", style=discord.ButtonStyle.secondary)
            async def fish_cb(inter: discord.Interaction):
                if inter.user.id != self.player.user_id:
                    return await inter.response.send_message("Ação não é sua.", ephemeral=True)
                await inter.response.defer()
                await self.message.channel.send("Você começou a pescar... (placeholder)")
            self._btn_fish.callback = fish_cb
            self.add_item(self._btn_fish)

        if can_surf:
            self._btn_surf = discord.ui.Button(label="🌊 Surf", style=discord.ButtonStyle.secondary)
            async def surf_cb(inter: discord.Interaction):
                if inter.user.id != self.player.user_id:
                    return await inter.response.send_message("Ação não é sua.", ephemeral=True)
                await inter.response.defer()
                await self.message.channel.send("Você saiu surfando! (placeholder)")
            self._btn_surf.callback = surf_cb
            self.add_item(self._btn_surf)

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
                info = f"— **Passo {step}**" if principal else "— Opcional"
                lines.append(f"**{idx}. {prefix} {to_name}** {info}")
            desc = "\n".join(lines)

        # monta o embed e elementos
        embed = discord.Embed(
            title=f"🧭 Viagem — {current_loc_title}",
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
