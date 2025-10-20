# player_cog.py

import discord
import os
import random
from discord.ext import commands
from discord import ui
from supabase import create_client, Client
from utils.pokeapi_service import get_pokemon_data, calculate_stats_for_level, get_initial_moves

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

# ========= CLASSES DE UI (Refatoradas para um fluxo lógico) =========

class StarterSelectView(ui.View):
    """View final para o jogador escolher seu Pokémon inicial e completar o registro."""
    def __init__(self, region: str, trainer_name: str, supabase_client: Client, player_cog_instance):
        super().__init__(timeout=300)
        self.region = region
        self.trainer_name = trainer_name
        self.supabase = supabase_client
        self.player_cog = player_cog_instance
        
        starters = STARTERS_BY_REGION.get(region, [])
        for starter in starters:
            button = ui.Button(label=starter.title(), custom_id=starter, style=discord.ButtonStyle.primary)
            button.callback = self.button_callback
            self.add_item(button)

    async def button_callback(self, interaction: discord.Interaction):
        # Desabilita os botões para evitar cliques múltiplos
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        chosen_starter = interaction.data['custom_id']
        is_shiny = random.randint(1, 100) == 1  # 1% de chance de ser shiny

        try:
            # ETAPA 1: Agora sim, registra o jogador no banco de dados.
            await self.supabase.table('players').insert({
                'discord_id': interaction.user.id,
                'trainer_name': self.trainer_name
            }).execute()

            # ETAPA 2: Adiciona o Pokémon inicial ao jogador recém-criado.
            await self.player_cog.add_pokemon_to_player(interaction.user.id, chosen_starter, is_shiny, level=5)
            
            shiny_text = "✨ **SHINY!** ✨" if is_shiny else ""
            # Envia uma mensagem pública de boas-vindas
            await interaction.response.send_message(
                f"🎉 Parabéns, Treinador(a) **{self.trainer_name}**! Você escolheu **{chosen_starter.title()}** como seu parceiro inicial! {shiny_text}\n"
                "Sua aventura Pokémon começa agora! Use `!team` para ver seu novo companheiro."
            )
        except Exception as e:
            print(f"Erro ao criar jogador e starter: {e}")
            await interaction.response.send_message("Ocorreu um erro ao finalizar seu registro. Se o problema persistir, contate um administrador.", ephemeral=True)


class RegionSelectView(ui.View):
    """View para o jogador escolher a região inicial."""
    def __init__(self, trainer_name: str, supabase_client: Client, player_cog_instance):
        super().__init__(timeout=180)
        self.trainer_name = trainer_name
        self.supabase = supabase_client
        self.player_cog = player_cog_instance

        regions = ["Kanto", "Johto", "Hoenn", "Sinnoh", "Unova", "Kalos", "Alola", "Galar", "Paldea"]
        for region_name in regions:
            button = ui.Button(label=region_name, style=discord.ButtonStyle.secondary, custom_id=region_name)
            button.callback = self.region_button_callback
            self.add_item(button)

    async def region_button_callback(self, interaction: discord.Interaction):
        chosen_region = interaction.data['custom_id']
        
        # Simplesmente avança para a próxima etapa (escolha do inicial)
        await interaction.response.edit_message(
            content=f"Ótima escolha! Você selecionou a região de **{chosen_region}**. Agora, escolha seu parceiro inicial!",
            view=StarterSelectView(chosen_region, self.trainer_name, self.supabase, self.player_cog)
        )
        self.stop()


class TrainerNameModal(ui.Modal, title="Crie seu Personagem"):
    """Modal para o jogador inserir o nome do treinador."""
    def __init__(self, supabase_client: Client, player_cog_instance):
        super().__init__(timeout=300)
        self.supabase = supabase_client
        self.player_cog = player_cog_instance

    trainer_name_input = ui.TextInput(label="Qual será seu nome de treinador?", placeholder="Ex: Ash Ketchum", required=True, max_length=50)

    async def on_submit(self, interaction: discord.Interaction):
        trainer_name = self.trainer_name_input.value
        
        # Apenas passa o nome para a próxima etapa (escolha de região)
        await interaction.response.send_message(
            f"Bem-vindo(a), Treinador(a) **{trainer_name}**! Para começar sua jornada, escolha sua região inicial.",
            view=RegionSelectView(trainer_name, self.supabase, self.player_cog),
            ephemeral=True
        )


class StartJourneyView(ui.View):
    """View inicial com o botão 'Iniciar Jornada'."""
    def __init__(self, supabase_client: Client, player_cog_instance):
        super().__init__(timeout=180)
        self.supabase = supabase_client
        self.player_cog = player_cog_instance

    @ui.button(label="Iniciar Jornada", style=discord.ButtonStyle.success, emoji="🎉")
    async def begin(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(TrainerNameModal(self.supabase, self.player_cog))


# ========= CLASSE PRINCIPAL DO COG =========

class PlayerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.supabase_key = os.getenv("SUPABASE_KEY")
        self.supabase: Client = create_client(self.supabase_url, self.supabase_key)

    # ========= FUNÇÃO CENTRALIZADA DE LÓGICA =========

    async def add_pokemon_to_player(self, user_id: int, pokemon_name: str, is_shiny: bool, level: int = 5):
        """Função centralizada para adicionar um novo Pokémon a um jogador."""
        pokemon_name_clean = pokemon_name.strip().lower()
        api_data = await get_pokemon_data(pokemon_name_clean)
        if not api_data:
            raise ValueError(f"Não foi possível encontrar dados para {pokemon_name} na API.")

        calculated_stats = calculate_stats_for_level(api_data['stats'], level)
        initial_moves = get_initial_moves(api_data, level)

        pokemon_to_insert = {
            'player_id': user_id,
            'pokemon_api_name': pokemon_name_clean,
            'nickname': pokemon_name_clean.title(),
            'is_shiny': is_shiny,
            'current_level': level,
            'current_xp': 0,
            'current_hp': calculated_stats.get('max_hp', 10),
            'moves': initial_moves,
            **calculated_stats
        }
        
        await self.supabase.table('player_pokemon').insert(pokemon_to_insert).execute()

    # ========= COMANDOS DO JOGADOR =========

    @commands.command(name='start', help='Inicia sua jornada como um treinador Pokémon.')
    async def start(self, ctx):
        response = await self.supabase.table('players').select('discord_id').eq('discord_id', ctx.author.id).execute()
        if response.data:
            await ctx.send("Você já iniciou sua jornada! Use `!team` para ver seus Pokémon.")
            return

        view = StartJourneyView(self.supabase, self)
        await ctx.send(
            "Bem-vindo ao mundo Pokémon! Clique no botão abaixo para iniciar sua jornada e se tornar um Mestre Pokémon!",
            view=view
        )

    @commands.command(name='delete', help='Apaga todo o seu progresso para recomeçar.')
    async def delete_progress(self, ctx):
        """Apaga todos os dados de um jogador para que ele possa recomeçar."""
        
        class ConfirmDeleteView(ui.View):
            def __init__(self, supabase_client: Client):
                super().__init__(timeout=60)
                self.supabase = supabase_client

            @ui.button(label="Sim, apagar tudo!", style=discord.ButtonStyle.danger)
            async def confirm(self, interaction: discord.Interaction, button: ui.Button):
                if interaction.user.id != ctx.author.id:
                    await interaction.response.send_message("Você não pode confirmar esta ação.", ephemeral=True)
                    return

                try:
                    # A deleção em cascata no Supabase apaga os pokémons automaticamente.
                    await self.supabase.table('players').delete().eq('discord_id', ctx.author.id).execute()
                    self.stop()
                    # CORREÇÃO: A mensagem de sucesso agora é pública.
                    await interaction.response.edit_message(content="Seu progresso foi apagado com sucesso. Use `!start` para começar uma nova aventura.", view=None)
                except Exception as e:
                    await interaction.response.edit_message(content=f"Ocorreu um erro ao apagar seus dados: {e}", view=None)

            @ui.button(label="Não, cancelar.", style=discord.ButtonStyle.secondary)
            async def cancel(self, interaction: discord.Interaction, button: ui.Button):
                if interaction.user.id != ctx.author.id:
                    await interaction.response.send_message("Você não pode cancelar esta ação.", ephemeral=True)
                    return
                self.stop()
                await interaction.response.edit_message(content="Ação cancelada.", view=None)

        view = ConfirmDeleteView(self.supabase)
        await ctx.send(
            f"{ctx.author.mention}, você tem certeza que quer apagar **TODO** o seu progresso? "
            "Isso é irreversível e removerá seus Pokémon, itens e dinheiro.",
            view=view
        )

    @commands.command(name='help')
    async def help_command(self, ctx, option: str = 'default'):
        """Mostra uma mensagem de ajuda com os comandos disponíveis."""
        if option.lower() == 'default':
            embed = discord.Embed(title="Ajuda - PokeAdventure", description="Bem-vindo ao bot de aventura Pokémon!", color=discord.Color.orange())
            embed.add_field(name="`!start`", value="Inicia sua jornada como um treinador Pokémon.", inline=False)
            embed.add_field(name="`!team`", value="Mostra todos os seus Pokémon capturados.", inline=False)
            embed.add_field(name="`!shop`", value="Mostra a loja de itens evolutivos.", inline=False)
            embed.add_field(name="`!buy <item> <pokemon>`", value="Compra um item para evoluir um Pokémon.", inline=False)
            embed.add_field(name="`!delete`", value="Apaga seu progresso para começar uma nova jornada.", inline=False)
            embed.set_footer(text="Para ver a lista completa de comandos, digite `!help all`.")
            await ctx.send(embed=embed)

        elif option.lower() == 'all':
            embed = discord.Embed(title="Ajuda - Todos os Comandos", description="Lista completa de todos os comandos disponíveis.", color=discord.Color.dark_blue())
            
            command_list = sorted(self.bot.commands, key=lambda c: c.name)
            for command in command_list:
                if command.name != 'help' and not command.hidden:
                    embed.add_field(
                        name=f"`!{command.name}`",
                        value=command.help or "Sem descrição disponível.",
                        inline=False
                    )
            await ctx.send(embed=embed)

        else:
            await ctx.send(f"Opção `{option}` inválida. Use `!help` ou `!help all`.")


async def setup(bot: commands.Bot):
    await bot.add_cog(PlayerCog(bot))