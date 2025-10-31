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
import utils.image_generator as img_gen

class TeamNavigationView(ui.View):
    def __init__(self, bot: commands.Bot, player_id: int, current_slot: int, max_slot: int, full_team_data_db: list):
        super().__init__(timeout=600) # Timeout de 10 minutos
        self.bot = bot
        self.player_id = player_id
        self.current_slot = current_slot
        self.max_slot = max_slot
        self.full_team_data_db = full_team_data_db # Lista completa de dados do DB
        
        # Conecta ao Supabase para uso nos botões
        url: str = os.environ.get("SUPABASE_URL")
        key: str = os.environ.get("SUPABASE_KEY")
        self.supabase: Client = create_client(url, key)

        self._update_buttons()

    def _update_buttons(self):
        # Desabilita "Anterior" se estiver no primeiro slot
        self.children[0].disabled = self.current_slot == 1 # children[0] é o botão "Anterior"
        # Desabilita "Próximo" se estiver no último slot
        self.children[1].disabled = self.current_slot == self.max_slot # children[1] é o botão "Próximo"


    async def _send_updated_team_image(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False, thinking=True) # Avisa que está processando

        try:
            # Encontra os dados do Pokémon focado na lista completa do DB
            focused_db_data = next((p for p in self.full_team_data_db if p['party_position'] == self.current_slot), None)
            
            if not focused_db_data:
                await interaction.followup.send("Erro: Pokémon selecionado não encontrado.", ephemeral=True)
                return

            # Buscar dados da PokeAPI (focado)
            f_api_data = await pokeapi.get_pokemon_data(focused_db_data['pokemon_api_name'])
            f_species_data = await pokeapi.get_pokemon_species_data(focused_db_data['pokemon_api_name'])
            
            if not f_api_data or not f_species_data:
                 await interaction.followup.send("Erro ao buscar dados do Pokémon principal na PokeAPI.", ephemeral=True)
                 return
            
            focused_pokemon = {
                'db_data': focused_db_data,
                'api_data': f_api_data,
                'species_data': f_species_data
            }
            
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
            
            # Edita a mensagem original com a nova imagem e os botões atualizados
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
            self._update_buttons() # Atualiza estado dos botões
            await self._send_updated_team_image(interaction)


    @ui.button(label="Próximo", style=discord.ButtonStyle.blurple, emoji="➡️")
    async def next_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("Este não é o seu time!", ephemeral=True)
            return

        if self.current_slot < self.max_slot:
            self.current_slot += 1
            self._update_buttons() # Atualiza estado dos botões
            await self._send_updated_team_image(interaction)

    async def on_timeout(self):
        # Desabilita os botões quando a view expira
        for item in self.children:
            item.disabled = True
        try:
            # Edita a mensagem para desabilitar os botões
            await self.message.edit(view=self)
        except discord.NotFound:
            pass # A mensagem pode ter sido deletada

class TeamCog(commands.Cog):
    """Cog para gerenciar o time do jogador e exibir a nova imagem."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        url: str = os.environ.get("SUPABASE_URL")
        key: str = os.environ.get("SUPABASE_KEY")
        self.supabase: Client = create_client(url, key)
        print("TeamCog carregado.")

    @commands.command(name='team', help='Mostra seu time Pokémon. Use !team [1-6] para focar.')
    async def team(self, ctx: commands.Context, focused_slot: int = 1):
        """
        Exibe o time do jogador.
        Por padrão, foca no Pokémon da posição 1.
        Use !team 2 para focar no Pokémon da posição 2, e assim por diante.
        """
        if not 1 <= focused_slot <= 6:
            await ctx.send("Posição inválida. Escolha um número de 1 a 6.")
            return

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
            max_slot = len(full_team_data_db) # Número total de Pokémon no time
            
            # Ajusta focused_slot se for maior que o número de Pokémon
            if focused_slot > max_slot:
                focused_slot = 1 # Volta para o primeiro se o slot pedido não existir
            
            # Encontra o Pokémon focado
            focused_db_data = next((p for p in full_team_data_db if p['party_position'] == focused_slot), None)
            
            # Se ainda assim não encontrar (erro na lógica ou dados), pega o primeiro
            if not focused_db_data:
                focused_db_data = full_team_data_db[0]
                focused_slot = focused_db_data['party_position']

            # 2. Buscar dados da PokeAPI (focado)
            await msg.edit(content="Carregando dados da Pokédex... 📖")
            
            f_api_data = await pokeapi.get_pokemon_data(focused_db_data['pokemon_api_name'])
            f_species_data = await pokeapi.get_pokemon_species_data(focused_db_data['pokemon_api_name'])
            
            if not f_api_data or not f_species_data:
                 await msg.edit(content="Erro ao buscar dados do Pokémon principal da PokeAPI.")
                 return
            
            focused_pokemon = {
                'db_data': focused_db_data,
                'api_data': f_api_data,
                'species_data': f_species_data
            }
            
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
            
            view = TeamNavigationView(self.bot, player_id, focused_slot, max_slot, full_team_data_db)
            
            await msg.delete() # Deleta a mensagem de "carregando"
            message = await ctx.send(embed=embed, file=file, view=view)
            view.message = message # Armazena a mensagem para poder editá-la depois

        except Exception as e:
            print(f"Erro no comando !team: {e}")
            await msg.edit(content=f"Ocorreu um erro inesperado. O admin foi notificado.")


async def setup(bot: commands.Bot):
    await bot.add_cog(TeamCog(bot))