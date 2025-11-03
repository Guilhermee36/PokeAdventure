# cogs/team_cog.py
import discord
import os
from discord.ext import commands
from discord import ui
from supabase import create_client, Client
import asyncio
import json # Importado para o debug

# Importa nossos helpers
# Agora usamos mais funções do pokeapi_service
import utils.pokeapi_service as pokeapi

# --- HELPER: Barra de Progresso (Corrigida na última interação) ---
def _create_progress_bar(
    current: int, 
    total: int, 
    bar_length: int = 8, # <-- 1ª MUDANÇA: Alterado de 10 para 8
    emojis: tuple = ('🟩', '⬛')
) -> str:
    """Cria uma barra de progresso em texto com emojis customizáveis e porcentagem."""
    
    # Evita divisão por zero se o total for 0 (ex: Lvl 1 para Lvl 1)
    if total <= 0:
        return f"[{emojis[0] * bar_length}]\nProgresso Inicial!"
    
    current = min(current, total)
    percent = float(current) / total
    filled = int(bar_length * percent)
    empty = bar_length - filled
    
    bar_filled = emojis[0]
    bar_empty = emojis[1]
    
    # ✅ CORREÇÃO: Adicionado \n para forçar quebra de linha
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
            
            # ✅ ATUALIZAÇÃO: Esta função agora também busca os dados de XP e Shiny
            focused_pokemon = await self.cog._get_focused_pokemon_details(focused_db_data)
            
            if not focused_pokemon:
                await interaction.followup.send("Erro ao buscar dados do Pokémon principal da PokeAPI.", ephemeral=True)
                return
            
            # ✅ ATUALIZAÇÃO: O embed usará os novos dados de XP e Shiny
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

    
    def _get_player_team_sync(self, player_id: int) -> list:
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


    async def _get_focused_pokemon_details(self, p_mon_db: dict) -> dict:
        """
        Função ATUALIZADA:
        Agora busca dados da API, tradução, limites de XP e sprite SHINY.
        """
        api_data = await pokeapi.get_pokemon_data(p_mon_db['pokemon_api_name'])
        if not api_data:
            return None
        
        # 1. Busca dados da espécie (para tradução e XP)
        species_data = await pokeapi.get_pokemon_species_data(p_mon_db['pokemon_api_name'])
        
        # 2. Pega o texto em PT-BR
        flavor_text = pokeapi.get_portuguese_flavor_text(species_data) if species_data else "Descrição não encontrada."

        # --- ✅ NOVA LÓGICA DE SHINY (Ponto 3) ---
        is_shiny = p_mon_db.get('is_shiny', False)
        artwork_sprites = api_data.get('sprites', {}).get('other', {}).get('official-artwork', {})
        
        if is_shiny and artwork_sprites.get('front_shiny'):
            sprite_url = artwork_sprites['front_shiny']
        else:
            sprite_url = artwork_sprites.get('front_default')

        # Fallback se o 'official-artwork' falhar
        if not sprite_url:
            sprite_url = api_data.get('sprites', {}).get('front_shiny') if is_shiny else api_data.get('sprites', {}).get('front_default', '')
        # --- Fim da Lógica de Shiny ---

        # --- Lógica de XP (Existente) ---
        xp_for_next_level = float('inf') 
        xp_for_current_level = 0       
        
        if species_data and 'growth_rate' in species_data:
            growth_rate_url = species_data['growth_rate']['url']
            current_level = p_mon_db['current_level']
            
            xp_for_next_level = await pokeapi.get_total_xp_for_level(growth_rate_url, current_level + 1)
            
            if current_level > 1:
                xp_for_current_level = await pokeapi.get_total_xp_for_level(growth_rate_url, current_level)
        # --- Fim da Lógica de XP ---

        return {
            "db_data": p_mon_db,
            "api_data": api_data,
            "flavor_text": flavor_text,
            "sprite_url": sprite_url,
            "xp_for_next_level": xp_for_next_level,
            "xp_for_current_level": xp_for_current_level,
            "is_shiny": is_shiny # Passa o status de shiny para o embed
        }
        
    async def _build_team_embed(self, focused_pokemon_details: dict, full_team_db: list, focused_slot: int) -> discord.Embed:
        # (Função atualizada com as melhorias)
        db_data = focused_pokemon_details['db_data']
        api_data = focused_pokemon_details['api_data']
        
        nickname = db_data['nickname'].capitalize()
        level = db_data['current_level']
        
        # --- ✅ MUDANÇA: Adiciona emoji shiny e cor (Ponto 3) ---
        is_shiny = focused_pokemon_details.get('is_shiny', False)
        shiny_indicator = " ✨" if is_shiny else ""
        
        embed = discord.Embed(
            title=f"{nickname} - LV{level}{shiny_indicator}",
            description=f"_{focused_pokemon_details['flavor_text']}_", 
            color=discord.Color.yellow() if is_shiny else discord.Color.blue()
        )
        
        if focused_pokemon_details['sprite_url']:
            embed.set_thumbnail(url=focused_pokemon_details['sprite_url'])
        
        # --- Barra de HP (Inalterada) ---
        hp_emojis = ('🟩', '⬛')
        hp_bar = _create_progress_bar(
            db_data['current_hp'], 
            db_data['max_hp'], 
            emojis=hp_emojis
        )
        
        # --- LÓGICA DE XP ATUALIZADA (Inalterada) ---
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
        # --- Fim da Melhoria de XP ---
        
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
            
            # (Agora busca dados de XP, tradução e SHINY)
            focused_pokemon = await self._get_focused_pokemon_details(focused_db_data)
            
            if not focused_pokemon:
                await msg.edit(content="Erro ao buscar dados do Pokémon principal da PokeAPI.")
                return
            
            # (Agora usa os novos dados para o embed)
            embed = await self.cog._build_team_embed(focused_pokemon, full_team_data_db, focused_slot)
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

    
    @commands.command(name="debugteam")
    @commands.is_owner()
    async def debug_team(self, ctx: commands.Context):
        player_id = ctx.author.id
        await ctx.send(f"--- 🔎 Iniciando Debug do Time para Player ID: `{player_id}` ---")
        
        try:
            # Teste 1: A consulta exata que o !team usa
            await ctx.send(f"**TESTE 1:** Buscando Pokémon COM `.filter(\"party_position\", \"not.is\", \"null\")`...")
            response_with_not_null = (
                self.supabase.table("player_pokemon")
                .select("*")
                .eq("player_id", player_id)
                .filter("party_position", "not.is", "null")
                .execute()
            )
            
            await ctx.send(f"**Resultado (Teste 1):**\n> Total encontrado: {len(response_with_not_null.data)}\n> ```json\n{json.dumps(response_with_not_null.data, indent=2)}\n```")

            # Teste 2: Buscando TODOS os Pokémon do seu ID, sem filtro
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