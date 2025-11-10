# cogs/team_cog.py
import discord
import os
from discord.ext import commands
from discord import ui
from supabase import create_client, Client
import asyncio
import json

import utils.pokeapi_service as pokeapi

# --- HELPER: Barra de Progresso (Corrigida) ---
def _create_progress_bar(
    current: int,
    total: int,
    bar_length: int = 8,
    emojis: tuple = ('🟩', '⬛')
) -> str:
    """Cria uma barra de progresso em texto com emojis customizáveis e porcentagem."""
    if total <= 0:
        return f"[{emojis[0] * bar_length}]\nProgresso Inicial!"
    current = max(0, min(current, total))
    percent = float(current) / total
    filled = int(bar_length * percent)
    empty = bar_length - filled
    bar_filled = emojis[0]
    bar_empty = emojis[1]
    return f"[{bar_filled * filled}{bar_empty * empty}]\n{current}/{total} ({percent:.0%})"


class TeamNavigationView(ui.View):
    def __init__(self, cog: commands.Cog, player_id: int, current_slot: int, max_slot: int, full_team_data_db: list):
        super().__init__(timeout=600)
        self.cog = cog
        self.player_id = player_id
        self.current_slot = current_slot
        self.max_slot = max_slot
        self.full_team_data_db = full_team_data_db

        url: str = os.environ.get("SUPABASE_URL")
        key: str = os.environ.get("SUPABASE_KEY")
        self.supabase: Client = create_client(url, key)
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


class TeamCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        url: str = os.environ.get("SUPABASE_URL")
        key: str = os.environ.get("SUPABASE_KEY")
        self.supabase: Client = create_client(url, key)

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

    def _swap_or_move(self, user_id: int, src_id: str, dest_slot: int) -> str:
        """
        Faz swap (se o slot destino estiver ocupado) ou move (se vazio).
        Usa slot temporário (-999) para evitar conflito de UNIQUE.
        """
        # source + slot atual
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
        src_slot = int(src_row[0]["party_position"])

        if src_slot == dest_slot:
            return "Esse Pokémon já está nesse slot."

        # ocupante destino?
        dst_row = (
            self.supabase.table("player_pokemon")
            .select("id,party_position")
            .eq("player_id", user_id)
            .eq("party_position", dest_slot)
            .limit(1)
            .execute()
        ).data or []

        if dst_row:
            # SWAP
            dst_id = dst_row[0]["id"]
            # (a) source -> temporário
            self.supabase.table("player_pokemon").update({"party_position": -999}).eq("id", src_id).execute()
            # (b) dest -> src_slot
            self.supabase.table("player_pokemon").update({"party_position": src_slot}).eq("id", dst_id).execute()
            # (c) temp(source) -> dest_slot
            self.supabase.table("player_pokemon").update({"party_position": dest_slot}).eq("id", src_id).execute()
            return f"✅ Slots trocados: #{src_slot} ↔ #{dest_slot}."
        else:
            # MOVE simples
            self.supabase.table("player_pokemon").update({"party_position": dest_slot}).eq("id", src_id).execute()
            return f"✅ Pokémon movido para o slot #{dest_slot}."

    async def _get_focused_pokemon_details(self, p_mon_db: dict) -> dict:
        """
        Busca dados do Pokémon na API + species para flavor/XP e resolve sprite (shiny/normal).
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
        db_data = focused_pokemon_details['db_data']
        api_data = focused_pokemon_details['api_data']

        nickname = db_data['nickname'].capitalize()
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

        hp_emojis = ('🟩', '⬛')
        hp_bar = _create_progress_bar(
            db_data['current_hp'],
            db_data['max_hp'],
            emojis=hp_emojis
        )

        xp_emojis = ('🟦', '⬛')
        current_total_xp = db_data['current_xp']
        xp_base_level = focused_pokemon_details['xp_for_current_level']
        xp_prox_level = focused_pokemon_details['xp_for_next_level']

        if xp_prox_level == float('inf'):
            xp_bar = f"[{xp_emojis[0] * 8}]\nNível Máximo"
        else:
            total_xp_for_this_level = xp_prox_level - xp_base_level
            current_xp_in_this_level = current_total_xp - xp_base_level
            xp_bar = _create_progress_bar(
                current_xp_in_this_level,
                total_xp_for_this_level,
                emojis=xp_emojis
            )

        embed.add_field(name="HP", value=hp_bar, inline=False)
        embed.add_field(name="XP", value=xp_bar, inline=False)

        moves_list = []
        if db_data.get('moves'):
            for move_name in db_data['moves']:
                if move_name:
                    moves_list.append(f"• {move_name.replace('-', ' ').capitalize()}")
        if not moves_list:
            moves_list.append("Nenhum movimento aprendido.")

        embed.add_field(name="GOLPES", value="\n".join(moves_list), inline=False)

        species_name = api_data['name'].capitalize()
        pokedex_id = api_data['id']
        embed.set_footer(text=f"Slot {focused_slot}/{len(full_team_db)} | {species_name} (Pokedex Nº {pokedex_id})")

        return embed

    # ---------------- Comando de visualização do time (embed com navegação) ----------------
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
            await msg.edit(content=f"Buscando dados de **{focused_db_data['nickname'].capitalize()}**...")

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
            await msg.edit(content=f"Ocorreu um erro inesperado. O admin foi notificado.")

    @team.error
    async def team_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Acalme-se, Treinador! Você pode checar seu time novamente em {error.retry_after:.1f} segundos.", delete_after=5)
        else:
            await ctx.send(f"Ocorreu um erro: {error}")

    # ---------------- Gerenciador de party com swap: SelectTeam / MoveParty ----------------
    @commands.command(name="SelectTeam", aliases=["selectteam", "MoveParty", "moveparty"])
    async def select_team(self, ctx: commands.Context):
        """
        Abre o gerenciador de party com dois selects:
         1) Pokémon (mostra posição atual, nome, lv, HP)
         2) Slot de destino (1..6)
        Se o slot destino estiver ocupado, faz SWAP; senão, move.
        """
        user_id = ctx.author.id
        party_rows = self._get_player_team_sync(user_id)
        if not party_rows:
            return await ctx.send("Sua party está vazia (nenhum Pokémon com party_position definido).")

        # Resumo atual
        def fmt(r: dict) -> str:
            name = (r.get("nickname") or r.get("pokemon_api_name") or "").capitalize()
            return f"#{r['party_position']}: {name} (Lv.{r['current_level']}) — {r['current_hp']}/{r['max_hp']} HP"

        lines = ["**Party atual:**"]
        for r in party_rows:
            lines.append(fmt(r))
        await ctx.send("\n".join(lines))

        # Select de Pokémon (com posição no label)
        options_mon: list[discord.SelectOption] = []
        for r in party_rows:
            pos = r.get("party_position")
            name = (r.get("nickname") or r.get("pokemon_api_name") or "").capitalize()
            lvl = r.get("current_level", 1)
            hp = r.get("current_hp", 0)
            mhp = r.get("max_hp", 1)
            label = f"#{pos} • {name} (Lv.{lvl}) — {hp}/{mhp} HP"
            options_mon.append(discord.SelectOption(label=label[:100], value=str(r["id"])))

        class PickMon(discord.ui.Select):
            def __init__(self, opts, owner_id: int):
                super().__init__(placeholder="Escolha o Pokémon para mover…", min_values=1, max_values=1, options=opts)
                self.value_id: str | None = None
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
                self.slot_val: str | None = None
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
        view.add_item(sel_mon)
        view.add_item(sel_slot)
        view.add_item(btn_confirm)
        view.add_item(btn_cancel)

        async def on_confirm(inter: discord.Interaction):
            if inter.user.id != ctx.author.id:
                return await inter.response.send_message("Não é sua interface.", ephemeral=True)
            if not sel_mon.value_id or not sel_slot.slot_val:
                return await inter.response.send_message("Escolha o Pokémon e o slot de destino.", ephemeral=True)

            try:
                dest_slot = int(sel_slot.slot_val)
                msg = self._swap_or_move(user_id, sel_mon.value_id, dest_slot)
                # recarrega party para mostrar resultado
                new_party = self._get_player_team_sync(user_id)
                summary = ["**Party atualizada:**"]
                for r in new_party:
                    summary.append(fmt(r))
                await inter.response.edit_message(content=f"{msg}\n\n" + "\n".join(summary), view=None)
            except Exception as e:
                await inter.response.edit_message(content=f"Falha ao mover: `{e}`", view=None)

        async def on_cancel(inter: discord.Interaction):
            if inter.user.id != ctx.author.id:
                return await inter.response.send_message("Não é sua interface.", ephemeral=True)
            await inter.response.edit_message(content="Operação cancelada.", view=None)

        btn_confirm.callback = on_confirm
        btn_cancel.callback = on_cancel

        await ctx.send(
            "Gerenciador de Party — selecione o Pokémon e o slot de destino:",
            view=view
        )

    # ---------------- Debug ----------------
    @commands.command(name="debugteam")
    @commands.is_owner()
    async def debug_team(self, ctx: commands.Context):
        player_id = ctx.author.id
        await ctx.send(f"--- 🔎 Iniciando Debug do Time para Player ID: `{player_id}` ---")
        try:
            await ctx.send(f"**TESTE 1:** Buscando Pokémon COM `.filter(\"party_position\", \"not.is\", \"null\")`...")
            response_with_not_null = (
                self.supabase.table("player_pokemon")
                .select("*")
                .eq("player_id", player_id)
                .filter("party_position", "not.is", "null")
                .execute()
            )
            await ctx.send(f"**Resultado (Teste 1):**\n> Total encontrado: {len(response_with_not_null.data)}\n> ```json\n{json.dumps(response_with_not_null.data, indent=2)}\n```")

            await ctx.send(f"\n**TESTE 2:** Buscando TODOS os Pokémon para o seu ID (sem filtro de party)...")
            response_all = (
                self.supabase.table("player_pokemon")
                .select("*")
                .eq("player_id", player_id)
                .execute()
            )
            await ctx.send(f"**Resultado (Teste 2):**\n> Total encontrado: {len(response_all.data)}\n> ```json\n{json.dumps(response_all.data, indent=2)}\n```")

            await ctx.send("\n--- ✅ Debug Concluido ---")
        except Exception as e:
            await ctx.send(f"**ERRO DURANTE O DEBUG:**\n> ```{e}```")


async def setup(bot: commands.Bot):
    await bot.add_cog(TeamCog(bot))
