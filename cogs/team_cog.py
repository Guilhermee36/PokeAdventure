# cogs/team_cog.py
import discord
import os
from discord.ext import commands
from discord import ui
from supabase import create_client, Client
from io import BytesIO
import asyncio

# Importa nossos helpers
import utils.pokeapi_service as pokeapi
import utils.image_generator as img_gen # O gerador novo

class TeamNavigationView(ui.View):
    # VVV MUDANÇA VVV
    # Agora recebemos o 'cog' inteiro, não só o 'bot'
    def __init__(self, cog: commands.Cog, player_id: int, current_slot: int, max_slot: int, full_team_data_db: list):
        super().__init__(timeout=600)
        self.cog = cog # Armazena o cog
        # ^^^ FIM DA MUDANÇA ^^^
        
        self.player_id = player_id
        self.current_slot = current_slot
        self.max_slot = max_slot
        self.full_team_data_db = full_team_data_db
        
        url: str = os.environ.get("SUPABASE_URL")
        key: str = os.environ.get("SUPABASE_KEY")
        self.supabase: Client = create_client(url, key)

        self._update_buttons()

    def _update_buttons(self):
        self.children[0].disabled = self.current_slot == 1
        self.children[1].disabled = self.current_slot == self.max_slot


    async def _send_updated_team_image(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False, thinking=True)

        try:
            focused_db_data = next((p for p in self.full_team_data_db if p['party_position'] == self.current_slot), None)
            if not focused_db_data:
                await interaction.followup.send("Erro: Pokémon selecionado não encontrado.", ephemeral=True)
                return

            # VVV MUDANÇA VVV
            # Usamos a nova função helper do cog para pegar TODOS os dados
            focused_pokemon = await self.cog._get_focused_pokemon_details(focused_db_data)
            if not focused_pokemon:
                await interaction.followup.send("Erro ao buscar dados do Pokémon principal na PokeAPI.", ephemeral=True)
                return
            # ^^^ FIM DA MUDANÇA ^^^
            
            # Gerar a imagem
            image_buffer = await img_gen.create_team_image(focused_pokemon, self.full_team_data_db, self.current_slot)
            
            if not image_buffer:
                await interaction.followup.send("Erro ao gerar a imagem do time.", ephemeral=True)
                return

            file = discord.File(image_buffer, filename=f"{interaction.user.name}_team.png")
            embed = discord.Embed(
                title=f"Time de {interaction.user.display_name}",
                description=f"Mostrando detalhes de **{focused_db_data['nickname'].capitalize()}** (Slot {self.current_slot}).\nUse as setas para navegar.",
                color=discord.Color.blue()
            )
            embed.set_image(url=f"attachment://{file.filename}")
            
            await interaction.edit_original_response(embed=embed, attachments=[file], view=self)

        except Exception as e:
            print(f"Erro ao atualizar imagem do time: {e}")
            await interaction.followup.send(f"Ocorreu um erro inesperado: {e}", ephemeral=True)


    @ui.button(label="Anterior", style=discord.ButtonStyle.blurple, emoji="⬅️")
    async def previous_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("Este não é o seu time!", ephemeral=True)
            return
            
        if self.current_slot > 1:
            self.current_slot -= 1
            self._update_buttons()
            await self._send_updated_team_image(interaction)


    @ui.button(label="Próximo", style=discord.ButtonStyle.blurple, emoji="➡️")
    async def next_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("Este não é o seu time!", ephemeral=True)
            return

        if self.current_slot < self.max_slot:
            self.current_slot += 1
            self._update_buttons()
            await self._send_updated_team_image(interaction)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except discord.NotFound:
            pass 

class TeamCog(commands.Cog):
    """Cog para gerenciar o time do jogador e exibir a nova imagem."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        url: str = os.environ.get("SUPABASE_URL")
        key: str = os.environ.get("SUPABASE_KEY")
        self.supabase: Client = create_client(url, key)
        print("TeamCog carregado.")

    # VVV NOVO HELPER VVV
    async def _get_focused_pokemon_details(self, focused_db_data: dict) -> dict | None:
        """Busca dados da API e calcula o XP para o Pokémon focado."""
        try:
            f_api_data = await pokeapi.get_pokemon_data(focused_db_data['pokemon_api_name'])
            f_species_data = await pokeapi.get_pokemon_species_data(focused_db_data['pokemon_api_name'])
            
            if not f_api_data or not f_species_data:
                return None 

            # Lógica de Cálculo de XP
            f_level = focused_db_data['current_level']
            current_xp = focused_db_data['current_xp']
            growth_rate_url = f_species_data['growth_rate']['url']
            
            # Precisamos do XP total para o nível ATUAL e o PRÓXIMO
            xp_for_current_level = await pokeapi.get_total_xp_for_level(growth_rate_url, f_level)
            xp_for_next_level = await pokeapi.get_total_xp_for_level(growth_rate_url, f_level + 1)
            
            # A "fatia" de XP total necessária para este nível
            total_xp_in_this_level = xp_for_next_level - xp_for_current_level
            # O quanto de XP o jogador já ganhou *dentro* deste nível
            current_xp_in_this_level = current_xp - xp_for_current_level
            
            xp_percent = 0.0
            if total_xp_in_this_level > 0:
                # Garante que a % esteja entre 0 e 1 (min/max)
                xp_percent = max(0, min(1, current_xp_in_this_level / total_xp_in_this_level))

            return {
                'db_data': focused_db_data,
                'api_data': f_api_data,
                'species_data': f_species_data,
                'xp_percent': xp_percent,
                'current_xp_raw': current_xp,
                'xp_for_next_level_raw': xp_for_next_level
            }
        except Exception as e:
            print(f"Erro em _get_focused_pokemon_details: {e}")
            return None
    # ^^^ FIM DO NOVO HELPER ^^^


    @commands.command(name='team', help='Mostra seu time Pokémon. Use !team [1-6] para focar.')
    async def team(self, ctx: commands.Context, focused_slot: int = 1):
        
        player_id = ctx.author.id
        msg = await ctx.send(f"Buscando seu time... 🔍")

        try:
            # 1. Buscar time no Supabase
            response = self.supabase.table('player_pokemon').select('*') \
                .eq('player_id', player_id) \
                .not_.is_('party_position', 'null') \
                .order('party_position', desc=False).execute()

            if not response.data:
                await msg.edit(content="Você ainda não tem um time! Capture um Pokémon.")
                return

            full_team_data_db = response.data
            max_slot = len(full_team_data_db)
            
            if not 1 <= focused_slot <= max_slot:
                focused_slot = 1 # Garante que o slot seja válido
            
            focused_db_data = full_team_data_db[focused_slot - 1] # Pega pela posição na lista ordenada

            # 2. Buscar dados da PokeAPI e XP (usando o helper)
            await msg.edit(content="Carregando dados da Pokédex... 📖")
            
            focused_pokemon = await self._get_focused_pokemon_details(focused_db_data)
            
            if not focused_pokemon:
                 await msg.edit(content="Erro ao buscar dados do Pokémon principal da PokeAPI.")
                 return
            
            # 3. Gerar a Imagem Inicial
            await msg.edit(content="Desenhando seu time... 🎨")
            image_buffer = await img_gen.create_team_image(focused_pokemon, full_team_data_db, focused_slot)
            
            if not image_buffer:
                await msg.edit(content="Erro ao gerar a imagem do time.")
                return

            # 4. Enviar a Imagem com Botões
            file = discord.File(image_buffer, filename=f"{ctx.author.name}_team.png")
            embed = discord.Embed(
                title=f"Time de {ctx.author.display_name}",
                description=f"Mostrando detalhes de **{focused_db_data['nickname'].capitalize()}** (Slot {focused_slot}).\nUse as setas para navegar.",
                color=discord.Color.blue()
            )
            embed.set_image(url=f"attachment://{file.filename}")
            
            # VVV MUDANÇA VVV
            # Passamos 'self' (o cog) para a View
            view = TeamNavigationView(self, player_id, focused_slot, max_slot, full_team_data_db)
            # ^^^ FIM DA MUDANÇA ^^^
            
            await msg.delete() 
            message = await ctx.send(embed=embed, file=file, view=view)
            view.message = message 

        except Exception as e:
            print(f"Erro no comando !team: {e}")
            await msg.edit(content=f"Ocorreu um erro inesperado. O admin foi notificado.")


async def setup(bot: commands.Bot):
    await bot.add_cog(TeamCog(bot))