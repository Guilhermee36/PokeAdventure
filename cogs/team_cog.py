# cogs/team_cog.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import json
from typing import List, Optional, Dict, Any

import discord
from discord.ext import commands
from discord import ui
from supabase import create_client, Client

# Usa helpers da sua PokeAPI
import utils.pokeapi_service as pokeapi


# =========================
# Supabase helper
# =========================
def get_supabase_client() -> Client:
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY")
    return create_client(url, key)


# =========================
# Helpers visuais simples
# =========================
def _create_progress_bar(
    current: int,
    total: int,
    bar_length: int = 8,
    emojis: tuple[str, str] = ('🟩', '⬛')
) -> str:
    """Cria barra de progresso (HP/XP) em texto."""
    if total <= 0:
        return f"[{emojis[1] * bar_length}]\n0/0 (0%)"
    current = max(0, min(current, total))
    ratio = current / total
    filled = int(bar_length * ratio)
    return f"[{emojis[0] * filled}{emojis[1] * (bar_length - filled)}]\n{current}/{total} ({ratio:.0%})"


# =========================
# View de navegação do time (!team)
# =========================
class TeamNavigationView(ui.View):
    def __init__(self, cog: "TeamCog", player_id: int, current_slot: int, max_slot: int, full_team_data_db: list):
        super().__init__(timeout=600)
        self.cog = cog
        self.player_id = player_id
        self.current_slot = current_slot
        self.max_slot = max_slot
        self.full_team_data_db = full_team_data_db
        self.supabase: Client = get_supabase_client()
        self._update_buttons()

    def _update_buttons(self):
        self.previous_pokemon.disabled = self.current_slot == 1
        self.next_pokemon.disabled = self.current_slot == self.max_slot

    async def _send_updated_team_embed(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        try:
            self.full_team_data_db = self.cog._get_player_team_sync(self.player_id)
            focused_db_data = self.full_team_data_db[self.current_slot - 1]
            focused_pokemon = await self.cog._get_focused_pokemon_details(focused_db_data)

            if not focused_pokemon:
                await interaction.followup.send("Erro ao buscar dados do Pokémon principal da PokeAPI.", ephemeral=True)
                return

            embed = await self.cog._build_team_embed(focused_pokemon, self.full_team_data_db, self.current_slot)
            self._update_buttons()
            await interaction.message.edit(content=None, embed=embed, view=self)
        except Exception as e:
            print(f"Erro ao atualizar embed do time: {e}")
            if not interaction.is_done():
                await interaction.followup.send("Erro ao atualizar o time.", ephemeral=True)

    @ui.button(label="<", style=discord.ButtonStyle.primary, row=0)
    async def previous_pokemon(self, interaction: discord.Interaction, button: ui.Button):
        if self.current_slot > 1:
            self.current_slot -= 1
            await self._send_updated_team_embed(interaction)
        else:
            await interaction.response.defer()

    @ui.button(label=">", style=discord.ButtonStyle.primary, row=0)
    async def next_pokemon(self, interaction: discord.Interaction, button: ui.Button):
        if self.current_slot < self.max_slot:
            self.current_slot += 1
            await self._send_updated_team_embed(interaction)
        else:
            await interaction.response.defer()


# =========================
# Team Cog (Tudo em um)
# =========================
class TeamCog(commands.Cog):
    """
    Tudo do seu gerenciador de time:
    - !team: visualização detalhada com navegação
    - !box: Party + Box em Embed com sprites
    - !SelectTeam / !MoveParty: UI de mover com SWAP (NULL temporário) + Embeds
    - !partyset: atalho textual para mover/swap
    - debugteam: utilitário de diagnóstico
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.supabase: Client = get_supabase_client()

    # ---------- Helpers de BD ----------
    def _get_player_team_sync(self, player_id: int) -> list:
        """Retorna a party (party_position NOT NULL), ordenada por slot."""
        try:
            response = (
                self.supabase.table("player_pokemon")
                .select("*")
                .eq("player_id", player_id)
                .filter("party_position", "not.is", "null")
                .order("party_position", desc=False)
                .execute()
            )
            return response.data or []
        except Exception as e:
            print(f"Erro ao buscar time no Supabase (Sync): {e}")
            return []

    def _fetch_all_mons(self, user_id: int) -> List[dict]:
        """
        Retorna todos os Pokémon do jogador (party e box), com campos mínimos para listagem.
        Ordena por party_position asc (NULLs ao final).
        """
        res = (
            self.supabase.table("player_pokemon")
            .select("id,pokemon_api_name,nickname,party_position,current_hp,max_hp,current_level,is_shiny")
            .eq("player_id", user_id)
            .order("party_position", desc=False)
            .execute()
        )
        return res.data or []

    def _swap_or_move(self, user_id: int, src_id: str, dest_slot: int) -> str:
        """
        MOVE/SWAP seguro entre posições da PARTY (1..6):
        • Se destino estiver ocupado → SWAP real (source <-> destino) usando NULL temporário.
        • Se destino estiver vazio → MOVE simples.
        Observação importante: buscamos o ocupante do destino ANTES de qualquer limpeza,
        para não mandar o ocupante pra Box por engano.
        """
        # 1) slot atual do source
        src_row = (
            self.supabase.table("player_pokemon")
            .select("id,party_position")
            .eq("id", src_id)
            .eq("player_id", user_id)
            .limit(1)
            .execute()
        ).data or []
        if not src_row:
            return "Pokémon selecionado não encontrado."
        src_slot = src_row[0]["party_position"]
        if src_slot is None:
            return "O Pokémon selecionado não está na party."
        src_slot = int(src_slot)
        if src_slot == dest_slot:
            return "Esse Pokémon já está nesse slot."

        # 2) BUSCA primeiro o ocupante do destino (se houver) — sem limpar nada ainda
        dst_row = (
            self.supabase.table("player_pokemon")
            .select("id,party_position")
            .eq("player_id", user_id)
            .eq("party_position", dest_slot)
            .limit(1)
            .execute()
        ).data or []

        if dst_row:
            # ---- SWAP clássico usando NULL temporário ----
            dst_id = dst_row[0]["id"]

            # a) source -> NULL (Box temporária)
            self.supabase.table("player_pokemon").update({"party_position": None}).eq("id", src_id).execute()

            # b) destino -> slot original do source
            self.supabase.table("player_pokemon").update({"party_position": src_slot}).eq("id", dst_id).execute()

            # c) source (que está em NULL) -> slot destino
            self.supabase.table("player_pokemon").update({"party_position": dest_slot}).eq("id", src_id).execute()

            # d) limpeza defensiva de duplicatas residuais nos dois slots (se houver dados "sujos")
            self.supabase.table("player_pokemon").update({"party_position": None}) \
                .eq("player_id", user_id).eq("party_position", dest_slot).neq("id", src_id).execute()
            self.supabase.table("player_pokemon").update({"party_position": None}) \
                .eq("player_id", user_id).eq("party_position", src_slot).neq("id", dst_id).execute()

            return f"✅ Slots trocados: #{src_slot} ↔ #{dest_slot}."
        else:
            # ---- MOVE simples: destino vazio ----
            self.supabase.table("player_pokemon").update({"party_position": dest_slot}).eq("id", src_id).execute()

            # limpeza defensiva de duplicatas no slot destino (exclui o próprio src_id)
            self.supabase.table("player_pokemon").update({"party_position": None}) \
                .eq("player_id", user_id).eq("party_position", dest_slot).neq("id", src_id).execute()

            return f"✅ Pokémon movido para o slot #{dest_slot}."

        
    def _move_from_box_to_party(self, user_id: int, box_mon_id: str, dest_slot: int) -> str:
        """
        Move um Pokémon da BOX (party_position NULL) para a Party no slot desejado.
        Se o slot estiver ocupado, o ocupante vai para a BOX (NULL) — efeito de SWAP.
        Também limpa duplicatas do slot destino.
        """
        # validar que o mon está na BOX
        row = (
            self.supabase.table("player_pokemon")
            .select("id,party_position")
            .eq("id", box_mon_id)
            .eq("player_id", user_id)
            .limit(1)
            .execute()
        ).data or []
        if not row:
            return "Pokémon não encontrado."
        if row[0]["party_position"] is not None:
            return "Esse Pokémon já está na party."

        # limpa quaisquer duplicatas no destino
        self.supabase.table("player_pokemon").update({"party_position": None}) \
            .eq("player_id", user_id) \
            .eq("party_position", dest_slot) \
            .execute()

        # se tinha um ocupante legítimo, já está NULL (Box). agora coloca o mon da Box no slot
        self.supabase.table("player_pokemon").update({"party_position": dest_slot}).eq("id", box_mon_id).execute()
        return f"✅ Pokémon movido da Box para o slot #{dest_slot}."

    # ---------- Helpers PokeAPI / Embeds ----------
    async def _get_sprite_url(self, api_name: str, shiny: bool = False) -> Optional[str]:
        """
        Busca sprite estável (prioriza official-artwork; fallback front_default).
        """
        try:
            data = await pokeapi.get_pokemon_data(api_name)
            if not data:
                return None
            sprites = data.get("sprites") or {}
            other = sprites.get("other") or {}
            art = other.get("official-artwork") or {}
            if shiny:
                return art.get("front_shiny") or sprites.get("front_shiny")
            return art.get("front_default") or sprites.get("front_default")
        except Exception:
            return None

    async def _get_focused_pokemon_details(self, p_mon_db: dict) -> Optional[dict]:
        """
        Busca dados do Pokémon na API + species para flavor/XP e resolve sprite (shiny/normal).
        (Usado no !team)
        """
        api_data = await pokeapi.get_pokemon_data(p_mon_db['pokemon_api_name'])
        if not api_data:
            return None

        base_species_name = api_data.get('species', {}).get('name') or p_mon_db['pokemon_api_name']
        species_data = await pokeapi.get_pokemon_species_data(base_species_name)
        flavor_text = pokeapi.get_portuguese_flavor_text(species_data) if species_data else "Descrição não encontrada."

        # sprite
        is_shiny = p_mon_db.get('is_shiny', False)
        artwork = api_data.get('sprites', {}).get('other', {}).get('official-artwork', {})
        sprite_url = artwork.get('front_shiny') if is_shiny else artwork.get('front_default')
        if not sprite_url:
            sprite_url = api_data.get('sprites', {}).get('front_shiny' if is_shiny else 'front_default', '')

        # XP thresholds
        xp_for_next_level = float('inf')
        xp_for_current_level = 0
        if species_data and 'growth_rate' in species_data:
            growth_rate_url = species_data['growth_rate']['url']
            current_level = p_mon_db['current_level']
            xp_for_next_level = await pokeapi.get_total_xp_for_level(growth_rate_url, current_level + 1)
            if current_level > 1:
                xp_for_current_level = await pokeapi.get_total_xp_for_level(growth_rate_url, current_level)

        return {
            "db_data": p_mon_db,
            "api_data": api_data,
            "flavor_text": flavor_text,
            "sprite_url": sprite_url,
            "xp_for_next_level": xp_for_next_level,
            "xp_for_current_level": xp_for_current_level,
            "is_shiny": is_shiny
        }

    async def _build_team_embed(self, focused_pokemon_details: dict, full_team_db: list, focused_slot: int) -> discord.Embed:
        """
        Monta o Embed detalhado do !team (HP/XP/Moves, etc.)
        """
        db_data = focused_pokemon_details['db_data']
        api_data = focused_pokemon_details['api_data']

        nickname = (db_data['nickname'] or db_data['pokemon_api_name']).capitalize()
        level = db_data['current_level']
        is_shiny = focused_pokemon_details.get('is_shiny', False)
        shiny_indicator = " ✨" if is_shiny else ""

        embed = discord.Embed(
            title=f"{nickname} - LV{level}{shiny_indicator}",
            description=f"_{focused_pokemon_details['flavor_text']}_",
            color=discord.Color.yellow() if is_shiny else discord.Color.blue()
        )

        if focused_pokemon_details['sprite_url']:
            embed.set_thumbnail(url=focused_pokemon_details['sprite_url'])

        # HP bar
        hp_bar = _create_progress_bar(
            db_data['current_hp'],
            db_data['max_hp'],
            emojis=('🟩', '⬛')
        )

        # XP bar
        current_total_xp = db_data['current_xp']
        xp_base_level = focused_pokemon_details['xp_for_current_level']
        xp_prox_level = focused_pokemon_details['xp_for_next_level']
        if xp_prox_level == float('inf'):
            xp_bar = f"[{'🟦' * 8}]\nNível Máximo"
        else:
            total_xp_for_this_level = max(1, xp_prox_level - xp_base_level)
            current_xp_in_this_level = max(0, current_total_xp - xp_base_level)
            xp_bar = _create_progress_bar(current_xp_in_this_level, total_xp_for_this_level, emojis=('🟦', '⬛'))

        embed.add_field(name="HP", value=hp_bar, inline=False)
        embed.add_field(name="XP", value=xp_bar, inline=False)

        # Moves
        moves_list = []
        if db_data.get('moves'):
            for move_name in db_data['moves']:
                if move_name:
                    moves_list.append(f"• {str(move_name).replace('-', ' ').capitalize()}")
        if not moves_list:
            moves_list.append("Nenhum movimento aprendido.")
        embed.add_field(name="GOLPES", value="\n".join(moves_list), inline=False)

        species_name = api_data['name'].capitalize()
        pokedex_id = api_data['id']
        embed.set_footer(text=f"Slot {focused_slot}/{len(full_team_db)} | {species_name} (Pokedex Nº {pokedex_id})")
        return embed

    async def _render_box_only_embed(self, user_id: int) -> discord.Embed:
        rows = (
            self.supabase.table("player_pokemon")
            .select("id,pokemon_api_name,nickname,current_level,is_shiny")
            .eq("player_id", user_id)
            .is_("party_position", None)
            .order("pokemon_api_name")
            .execute()
        ).data or []

        emb = discord.Embed(title="📦 Box", description="Pokémon disponíveis na sua Box.", color=discord.Color.blurple())
        if not rows:
            emb.description = "Sua Box está vazia."
            return emb

        shown = 0
        for r in rows:
            if shown >= 18:  # limita para caber bem
                break
            name = (r.get("nickname") or r.get("pokemon_api_name") or "").capitalize()
            lvl = r.get("current_level", 1)
            sprite = await self._get_sprite_url(r["pokemon_api_name"], bool(r.get("is_shiny")))
            val = f"Lv.{lvl}"
            if sprite:
                val += f" — [sprite]({sprite})"
            emb.add_field(name=name, value=val, inline=True)
            shown += 1

        if len(rows) > shown:
            emb.add_field(name="…", value=f"+{len(rows)-shown} na Box", inline=False)

        return emb


    async def _render_party_embed(self, user_id: int, title: str, desc: str) -> discord.Embed:
        """
        Embed só com a PARTY atual (slots 1..6), para início e fim do SelectTeam.
        """
        party_rows = [r for r in self._fetch_all_mons(user_id) if r.get("party_position") is not None]
        party_rows.sort(key=lambda x: x["party_position"])

        emb = discord.Embed(title=title, description=desc, color=discord.Color.blue())
        pass

        for r in party_rows:
            name = (r.get("nickname") or r.get("pokemon_api_name") or "").capitalize()
            lvl = r["current_level"]
            hp = f"{r['current_hp']}/{r['max_hp']} HP"
            sprite = await self._get_sprite_url(r["pokemon_api_name"], bool(r.get("is_shiny")))
            val = f"Lv.{lvl} — {hp}\n"
            if sprite:
                val += f"[sprite]({sprite})"
            emb.add_field(name=f"#{r['party_position']} • {name}", value=val, inline=True)

        return emb

    # ---------------- Comando !team (embed com navegação) ----------------
    @commands.command(name="team", aliases=["time"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def team(self, ctx: commands.Context, slot: int = 1):
        player_id = ctx.author.id
        msg = await ctx.send(f"Buscando seu time, {ctx.author.display_name}... 🔍")
        try:
            full_team_data_db = self._get_player_team_sync(player_id)
            if not full_team_data_db:
                await msg.edit(content="Você ainda não tem um time Pokémon! Use `!start` para começar sua jornada.")
                return

            max_slot = len(full_team_data_db)
            focused_slot = max(1, min(slot, max_slot))
            focused_db_data = full_team_data_db[focused_slot - 1]
            await msg.edit(content=f"Buscando dados de **{(focused_db_data['nickname'] or focused_db_data['pokemon_api_name']).capitalize()}**...")

            focused_pokemon = await self._get_focused_pokemon_details(focused_db_data)
            if not focused_pokemon:
                await msg.edit(content="Erro ao buscar dados do Pokémon principal da PokeAPI.")
                return

            embed = await self._build_team_embed(focused_pokemon, full_team_data_db, focused_slot)
            view = TeamNavigationView(self, player_id, focused_slot, max_slot, full_team_data_db)

            await msg.edit(content=None, embed=embed, view=view)
            view.message = msg
        except Exception as e:
            print(f"Erro no comando !team (embed): {e}")
            await msg.edit(content=f"Ocorreu um erro inesperado.")

    @team.error
    async def team_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Acalme-se, Treinador! Você pode checar seu time novamente em {error.retry_after:.1f} segundos.", delete_after=5)
        else:
            await ctx.send(f"Ocorreu um erro: {error}")

    # ---------------- Comando !box (Embed com sprites) ----------------
    @commands.command(name="box")
    async def cmd_box(self, ctx: commands.Context):
        user_id = ctx.author.id

        # 1) Embed só com a Box
        emb = await self._render_box_only_embed(user_id)
        await ctx.send(embed=emb)

        # 2) Monta UI (Box -> Party)
        # carrega BOX
        box_rows = (
            self.supabase.table("player_pokemon")
            .select("id,pokemon_api_name,nickname,current_level,is_shiny")
            .eq("player_id", user_id)
            .is_("party_position", None)
            .order("pokemon_api_name")
            .execute()
        ).data or []

        if not box_rows:
            return  # nada para mover

        # Select de Pokémon da Box
        options_mon: List[discord.SelectOption] = []
        for r in box_rows:
            name = (r.get("nickname") or r.get("pokemon_api_name") or "").capitalize()
            lvl = r.get("current_level", 1)
            options_mon.append(discord.SelectOption(label=f"{name} (Lv.{lvl})", value=str(r["id"])))

        class PickMon(discord.ui.Select):
            def __init__(self, opts, owner_id: int):
                super().__init__(placeholder="Escolha um Pokémon da Box…", min_values=1, max_values=1, options=opts)
                self.value_id: Optional[str] = None
                self.owner_id = owner_id
            async def callback(self, inter: discord.Interaction):
                if inter.user.id != self.owner_id:
                    return await inter.response.send_message("Não é sua interface.", ephemeral=True)
                self.value_id = self.values[0]
                await inter.response.defer()

        # Select de slot destino (na Party)
        options_slot = [discord.SelectOption(label=f"Slot {i}", value=str(i)) for i in range(1, 7)]
        class PickSlot(discord.ui.Select):
            def __init__(self, opts, owner_id: int):
                super().__init__(placeholder="Mover para o slot…", min_values=1, max_values=1, options=opts)
                self.slot_val: Optional[str] = None
                self.owner_id = owner_id
            async def callback(self, inter: discord.Interaction):
                if inter.user.id != self.owner_id:
                    return await inter.response.send_message("Não é sua interface.", ephemeral=True)
                self.slot_val = self.values[0]
                await inter.response.defer()

        sel_mon = PickMon(options_mon, ctx.author.id)
        sel_slot = PickSlot(options_slot, ctx.author.id)
        btn_confirm = discord.ui.Button(label="Mover da Box → Party", style=discord.ButtonStyle.success)
        btn_cancel = discord.ui.Button(label="Cancelar", style=discord.ButtonStyle.secondary)

        view = discord.ui.View(timeout=120)
        view.add_item(sel_mon); view.add_item(sel_slot); view.add_item(btn_confirm); view.add_item(btn_cancel)

        async def on_confirm(inter: discord.Interaction):
            if inter.user.id != ctx.author.id:
                return await inter.response.send_message("Não é sua interface.", ephemeral=True)
            if not sel_mon.value_id or not sel_slot.slot_val:
                return await inter.response.send_message("Escolha o Pokémon e o slot de destino.", ephemeral=True)
            try:
                dest_slot = int(sel_slot.slot_val)
                msg_txt = self._move_from_box_to_party(user_id, sel_mon.value_id, dest_slot)
                # renderiza embeds atualizados (box e party)
                emb_party = await self._render_party_embed(user_id, "👥 Party atualizada", msg_txt)
                emb_box = await self._render_box_only_embed(user_id)
                await inter.response.edit_message(content=None, embed=emb_party, view=None)
                await ctx.send(embed=emb_box)  # mostra a box após a mudança
            except Exception as e:
                await inter.response.edit_message(content=f"Falha ao mover: `{e}`", view=None)

        async def on_cancel(inter: discord.Interaction):
            if inter.user.id != ctx.author.id:
                return await inter.response.send_message("Não é sua interface.", ephemeral=True)
            await inter.response.edit_message(content="Operação cancelada.", view=None)

        btn_confirm.callback = on_confirm
        btn_cancel.callback = on_cancel

        await ctx.send("Mover da **Box** para a **Party**:", view=view)

    # ---------------- Comando textual opcional: !partyset ----------------
    @commands.command(name="partyset")
    async def cmd_partyset(self, ctx: commands.Context, *, args: str):
        """
        Uso: !partyset <nome|apelido> <slot>
        Move o Pokémon da PARTY para o slot desejado. Se ocupado, faz SWAP.
        """
        try:
            parts = args.rsplit(" ", 1)
            target_name = parts[0].strip().lower()
            slot = int(parts[1])
            if not 1 <= slot <= 6:
                return await ctx.send("Slot inválido (use 1–6).")
        except Exception:
            return await ctx.send("Uso: `!partyset <nome|apelido> <slot>`")

        rows = self._fetch_all_mons(ctx.author.id)
        party = [r for r in rows if r.get("party_position") is not None]

        cand = None
        for r in party:
            nm = (r.get("nickname") or r.get("pokemon_api_name") or "").lower()
            if nm == target_name:
                cand = r
                break
        if not cand:
            return await ctx.send("Pokémon não encontrado na party pelo nome/apelido.")

        msg_txt = self._swap_or_move(ctx.author.id, cand["id"], slot)
        emb = await self._render_party_embed(ctx.author.id, "👥 Party atualizada", msg_txt)
        await ctx.send(embed=emb)

    # ---------------- UI SelectTeam / MoveParty (swap com NULL) ----------------
    @commands.command(name="SelectTeam", aliases=["selectteam", "MoveParty", "moveparty"])
    async def select_team(self, ctx: commands.Context):
        """
        UI com 2 selects:
         1) Pokémon (mostra slot atual, nome, lv, HP)
         2) Slot destino (1..6)
        SWAP se destino ocupado; MOVE se vazio. Embeds no início e ao final.
        """
        user_id = ctx.author.id

        # Embed inicial com a party
        emb_start = await self._render_party_embed(user_id, "👥 Gerenciador de Party", "Escolha o Pokémon e o slot de destino.")
        await ctx.send(embed=emb_start)

        # Carrega party para montar selects
        rows = self._fetch_all_mons(user_id)
        party = [r for r in rows if r.get("party_position") is not None]
        if not party:
            return

        # Select de Pokémon
        options_mon: List[discord.SelectOption] = []
        for r in sorted(party, key=lambda x: x["party_position"]):
            pos = r.get("party_position")
            name = (r.get("nickname") or r.get("pokemon_api_name") or "").capitalize()
            lvl = r.get("current_level", 1)
            hp = r.get("current_hp", 0)
            mhp = r.get("max_hp", 1)
            label = f"#{pos} • {name} (Lv.{lvl}) — {hp}/{mhp} HP"
            options_mon.append(discord.SelectOption(label=label[:100], value=str(r["id"])))

        class PickMon(discord.ui.Select):
            def __init__(self, opts, owner_id: int):
                super().__init__(placeholder="Escolha o Pokémon…", min_values=1, max_values=1, options=opts)
                self.value_id: Optional[str] = None
                self.owner_id = owner_id
            async def callback(self, inter: discord.Interaction):
                if inter.user.id != self.owner_id:
                    return await inter.response.send_message("Não é sua interface.", ephemeral=True)
                self.value_id = self.values[0]
                await inter.response.defer()

        # Select de slot destino
        options_slot = [discord.SelectOption(label=f"Slot {i}", value=str(i)) for i in range(1, 7)]
        class PickSlot(discord.ui.Select):
            def __init__(self, opts, owner_id: int):
                super().__init__(placeholder="Escolha o slot de destino…", min_values=1, max_values=1, options=opts)
                self.slot_val: Optional[str] = None
                self.owner_id = owner_id
            async def callback(self, inter: discord.Interaction):
                if inter.user.id != self.owner_id:
                    return await inter.response.send_message("Não é sua interface.", ephemeral=True)
                self.slot_val = self.values[0]
                await inter.response.defer()

        sel_mon = PickMon(options_mon, ctx.author.id)
        sel_slot = PickSlot(options_slot, ctx.author.id)
        btn_confirm = discord.ui.Button(label="Mover (Swap)", style=discord.ButtonStyle.success)
        btn_cancel = discord.ui.Button(label="Cancelar", style=discord.ButtonStyle.secondary)

        view = discord.ui.View(timeout=120)
        view.add_item(sel_mon); view.add_item(sel_slot); view.add_item(btn_confirm); view.add_item(btn_cancel)

        async def on_confirm(inter: discord.Interaction):
            if inter.user.id != ctx.author.id:
                return await inter.response.send_message("Não é sua interface.", ephemeral=True)
            if not sel_mon.value_id or not sel_slot.slot_val:
                return await inter.response.send_message("Escolha o Pokémon e o slot de destino.", ephemeral=True)
            try:
                dest_slot = int(sel_slot.slot_val)
                msg_txt = self._swap_or_move(user_id, sel_mon.value_id, dest_slot)
                new_emb = await self._render_party_embed(user_id, "👥 Party atualizada", msg_txt)
                await inter.response.edit_message(embed=new_emb, view=None)
            except Exception as e:
                await inter.response.edit_message(content=f"Falha ao mover: `{e}`", view=None)

        async def on_cancel(inter: discord.Interaction):
            if inter.user.id != ctx.author.id:
                return await inter.response.send_message("Não é sua interface.", ephemeral=True)
            await inter.response.edit_message(content="Operação cancelada.", view=None)

        btn_confirm.callback = on_confirm
        btn_cancel.callback = on_cancel

        await ctx.send("Gerenciador de Party — selecione o Pokémon e o slot de destino:", view=view)

    # ---------------- Debug ----------------
    @commands.command(name="debugteam")
    @commands.is_owner()
    async def debug_team(self, ctx: commands.Context):
        player_id = ctx.author.id
        await ctx.send(f"--- 🔎 Iniciando Debug do Time para Player ID: `{player_id}` ---")
        try:
            await ctx.send(f"**TESTE 1:** Party (party_position NOT NULL)...")
            response_with_not_null = (
                self.supabase.table("player_pokemon")
                .select("*")
                .eq("player_id", player_id)
                .filter("party_position", "not.is", "null")
                .execute()
            )
            await ctx.send(f"**Resultado (Teste 1):**\n> Total: {len(response_with_not_null.data)}\n> ```json\n{json.dumps(response_with_not_null.data, indent=2)}\n```")

            await ctx.send(f"\n**TESTE 2:** Todos os Pokémon...")
            response_all = (
                self.supabase.table("player_pokemon")
                .select("*")
                .eq("player_id", player_id)
                .execute()
            )
            await ctx.send(f"**Resultado (Teste 2):**\n> Total: {len(response_all.data)}\n> ```json\n{json.dumps(response_all.data, indent=2)}\n```")

            await ctx.send("\n--- ✅ Debug Concluído ---")
        except Exception as e:
            await ctx.send(f"**ERRO DURANTE O DEBUG:**\n> ```{e}```")


# -------- setup --------
async def setup(bot: commands.Bot):
    await bot.add_cog(TeamCog(bot))
