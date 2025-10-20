# player_cog.py

import discord
import os
import random  # Importado para a lógica shiny
from discord.ext import commands
from discord import ui
from supabase import create_client, Client
from utils.pokeapi_service import get_pokemon_data, calculate_stats_for_level

# Dicionário de Pokémon iniciais por região
STARTERS_BY_REGION = {
    'Kanto': ['bulbasaur', 'charmander', 'squirtle'],
    'Johto': ['chikorita', 'cyndaquil', 'totodile'],
    'Hoenn': ['treecko', 'torchic', 'mudkip'],
    'Sinnoh': ['turtwig', 'chimchar', 'piplup'],
    'Unova': ['snivy', 'tepig', 'oshawott'],
    'Kalos': ['chespin', 'fennekin', 'froakie'],
    'Alola': ['rowlet', 'litten', 'popplio'],
    'Galar': ['grookey', 'scorbunny', 'sobble'],
    'Paldea': ['sprigatito', 'fuecoco', 'quaxly']
}

# ========= CLASSES DE UI (BOTÕES E MODALS) =========

class StarterSelectView(ui.View):
    """View para o jogador escolher seu Pokémon inicial."""
    def __init__(self, region: str, supabase_client: Client, player_cog_instance):
        super().__init__(timeout=300)
        self.region = region
        self.supabase = supabase_client
        self.player_cog = player_cog_instance
        
        starters = STARTERS_BY_REGION.get(region, [])
        for starter in starters:
            button = ui.Button(label=starter.title(), custom_id=starter, style=discord.ButtonStyle.primary)
            button.callback = self.button_callback
            self.add_item(button)

    async def button_callback(self, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        chosen_starter = interaction.data['custom_id']
        is_shiny = random.randint(1, 100) == 1

        try:
            # Chama a função centralizada para criar o Pokémon
            await self.player_cog.add_pokemon_to_player(interaction.user.id, chosen_starter, is_shiny, level=5)
            
            shiny_text = "✨ **SHINY!** ✨" if is_shiny else ""
            await interaction.response.send_message(
                f"Parabéns, {interaction.user.mention}! Você escolheu **{chosen_starter.title()}**! {shiny_text}\n"
                "Sua aventura Pokémon começa agora! Use `!team` para ver seu novo companheiro."
            )
        except Exception as e:
            print(f"Erro ao criar starter: {e}")
            await interaction.response.send_message("Ocorreu um erro ao registrar seu Pokémon inicial. Por favor, contate um administrador.", ephemeral=True)


class RegionSelectView(ui.View):
    """View para o jogador escolher sua região inicial."""
    def __init__(self, supabase_client: Client, player_cog_instance):
        super().__init__(timeout=300)
        self.supabase = supabase_client
        self.player_cog = player_cog_instance

    # Função auxiliar para evitar repetição de código
    async def show_starters(self, interaction: discord.Interaction, region: str):
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)
        
        starter_view = StarterSelectView(region, self.supabase, self.player_cog)
        await interaction.response.send_message(f"Você escolheu a região de **{region}**! Agora, escolha seu parceiro inicial:", view=starter_view, ephemeral=True)

    @ui.button(label="Kanto", style=discord.ButtonStyle.secondary, emoji="🌿")
    async def kanto_button(self, interaction: discord.Interaction, button: ui.Button):
        await self.show_starters(interaction, "Kanto")

    @ui.button(label="Johto", style=discord.ButtonStyle.secondary, emoji="🌊")
    async def johto_button(self, interaction: discord.Interaction, button: ui.Button):
        await self.show_starters(interaction, "Johto")
        
    @ui.button(label="Hoenn", style=discord.ButtonStyle.secondary, emoji="🌋")
    async def hoenn_button(self, interaction: discord.Interaction, button: ui.Button):
        await self.show_starters(interaction, "Hoenn")


class TrainerNameModal(ui.Modal, title="Crie seu Personagem"):
    def __init__(self, supabase_client: Client, player_cog_instance):
        super().__init__(timeout=300)
        self.supabase = supabase_client
        self.player_cog = player_cog_instance

    trainer_name_input = ui.TextInput(label="Qual será seu nome de treinador?", placeholder="Ex: Ash Ketchum", required=True, max_length=50)

    async def on_submit(self, interaction: discord.Interaction):
        trainer_name = self.trainer_name_input.value
        user_id = interaction.user.id

        try:
            await self.supabase.table('players').insert({'discord_id': user_id, 'trainer_name': trainer_name}).execute()

            await interaction.response.send_message(
                f"Bem-vindo(a), Treinador(a) **{trainer_name}**! Para começar sua jornada, escolha sua região inicial.",
                view=RegionSelectView(self.supabase, self.player_cog),
                ephemeral=True
            )
        except Exception as e:
            if 'duplicate key value violates unique constraint "players_pkey"' in str(e):
                await interaction.response.send_message("Você já iniciou uma jornada! Use `!team` para ver seus Pokémon.", ephemeral=True)
            else:
                print(f"Erro no on_submit do TrainerNameModal: {e}")
                await interaction.response.send_message("Ocorreu um erro ao criar seu treinador.", ephemeral=True)


class StartJourneyView(ui.View):
    def __init__(self, supabase_client: Client, player_cog_instance):
        super().__init__(timeout=180)
        self.supabase = supabase_client
        self.player_cog = player_cog_instance

    @ui.button(label="Iniciar Jornada", style=discord.ButtonStyle.success, emoji="🎉")
    async def begin(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(TrainerNameModal(supabase_client=self.supabase, player_cog_instance=self.player_cog))


# ========= CLASSE PRINCIPAL DO COG =========

class PlayerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.supabase_key = os.getenv("SUPABASE_KEY")
        self.supabase: Client = create_client(self.supabase_url, self.supabase_key)

    async def add_pokemon_to_player(self, user_id: int, pokemon_name: str, is_shiny: bool, level: int = 5):
        """
        Função centralizada para adicionar um novo Pokémon a um jogador,
        calculando a posição correta no time.
        """
        # 1. Contar quantos Pokémon o jogador já tem para definir a party_position
        count_response = await self.supabase.table('player_pokemon').select('id', count='exact').eq('player_id', user_id).execute()
        current_pokemon_count = count_response.count
        
        if current_pokemon_count >= 6:
            raise Exception("O time do jogador já está cheio.")
            
        party_position = current_pokemon_count + 1

        # 2. Buscar dados da API
        api_data = await get_pokemon_data(pokemon_name)
        if not api_data:
            raise ValueError(f"Não foi possível encontrar dados para {pokemon_name} na API.")

        # 3. Calcular os stats
        base_stats = {stat['stat']['name']: stat['base_stat'] for stat in api_data['stats']}
        calculated_stats = calculate_stats_for_level(base_stats, level)
        initial_hp = calculated_stats['hp']
        
        # 4. Inserir o Pokémon no Supabase
        pokemon_to_insert = {
            'player_id': user_id,
            'pokemon_api_name': pokemon_name.lower(),
            'nickname': pokemon_name.title(),
            'is_shiny': is_shiny,
            'current_level': level,
            'current_xp': 0,
            'current_hp': initial_hp,
            'party_position': party_position
        }
        
        await self.supabase.table('player_pokemon').insert(pokemon_to_insert).execute()

    @commands.command(name='start', help='Inicia sua jornada como um treinador Pokémon.')
    async def start(self, ctx):
        response = await self.supabase.table('players').select('discord_id').eq('discord_id', ctx.author.id).execute()
        if response.data:
            await ctx.send("Você já iniciou sua jornada! Use `!team` para ver seus Pokémon.")
            return

        view = StartJourneyView(supabase_client=self.supabase, player_cog_instance=self)
        await ctx.send(
            "Bem-vindo ao mundo Pokémon! Clique no botão abaixo para iniciar sua jornada e se tornar um Mestre Pokémon!",
            view=view
        )

    @commands.command(name='addpokemon', help='(Admin) Adiciona um Pokémon a um jogador.')
    @commands.is_owner()
    async def add_pokemon(self, ctx, pokemon_name: str, level: int = 5):
        try:
            await self.add_pokemon_to_player(ctx.author.id, pokemon_name, is_shiny=False, level=level)
            await ctx.send(f"**{pokemon_name.title()}** nível {level} foi adicionado ao seu time!")
        except Exception as e:
            if "O time do jogador já está cheio" in str(e):
                await ctx.send("Seu time está cheio! Você não pode adicionar mais Pokémon.")
            else:
                await ctx.send(f"Ocorreu um erro ao adicionar o Pokémon: {e}")
                print(f"Erro no !addpokemon: {e}")

    # Outros comandos como !help, !delete etc. continuam aqui...
    @commands.command(name='delete', help='Apaga todo o seu progresso.')
    async def delete_progress(self, ctx):
        # Implemente a lógica de deleção aqui...
        pass

    @commands.command(name='help')
    async def help_command(self, ctx, option: str = 'default'):
        # Implemente a lógica de ajuda aqui...
        pass

async def setup(bot: commands.Bot):
    await bot.add_cog(PlayerCog(bot))