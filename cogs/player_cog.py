import discord
import os
from discord.ext import commands
from discord import ui
from supabase import create_client, Client

# ========= CLASSES DE UI (BOTÕES E MODALS) - SEM ALTERAÇÕES AQUI =========
# (As classes StartJourneyView, TrainerNameModal, RegionSelectView, e ConfirmDeleteView continuam as mesmas)

class StartJourneyView(ui.View):
    """View inicial que aparece com o comando !start."""
    def __init__(self, supabase_client: Client):
        super().__init__(timeout=180)
        self.supabase = supabase_client

    @ui.button(label="Iniciar Jornada", style=discord.ButtonStyle.success, emoji="🎉")
    async def begin(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(TrainerNameModal(supabase_client=self.supabase))

class TrainerNameModal(ui.Modal, title="Crie seu Personagem"):
    def __init__(self, supabase_client: Client):
        super().__init__(timeout=300)
        self.supabase = supabase_client

    trainer_name_input = ui.TextInput(label="Qual será seu nome de treinador?", placeholder="Ex: Ash Ketchum", required=True, max_length=50)

    async def on_submit(self, interaction: discord.Interaction):
        trainer_name = self.trainer_name_input.value
        embed = discord.Embed(title="Escolha sua Região Inicial", description=f"Ótimo nome, **{trainer_name}**! Agora, escolha a região onde sua aventura vai começar.", color=discord.Color.blue())
        await interaction.response.send_message(embed=embed, view=RegionSelectView(trainer_name=trainer_name, supabase_client=self.supabase), ephemeral=True)

class RegionSelectView(ui.View):
    def __init__(self, trainer_name: str, supabase_client: Client):
        super().__init__(timeout=180)
        self.trainer_name = trainer_name
        self.supabase = supabase_client

    async def select_region(self, interaction: discord.Interaction, region: str):
        await interaction.response.defer()
        discord_id = interaction.user.id
        player_data = {'discord_id': discord_id, 'trainer_name': self.trainer_name, 'money': 1000, 'badges': 0, 'current_region': region, 'masterballs_owned': 0}
        try:
            self.supabase.table('players').insert(player_data).execute()
            await interaction.followup.send(f"🎉 Bem-vindo ao mundo Pokémon, Treinador(a) **{self.trainer_name}**! 🎉\nSua aventura começa agora na região de **{region}**. Boa sorte!", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro ao salvar seus dados: {e}", ephemeral=True)
        for item in self.children: item.disabled = True
        await interaction.edit_original_response(view=self)
        self.stop()

    @ui.button(label="Kanto", style=discord.ButtonStyle.primary, emoji="1️⃣")
    async def kanto(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Kanto")
    # ... (outros botões de região)

class ConfirmDeleteView(ui.View):
    def __init__(self, supabase_client: Client):
        super().__init__(timeout=60)
        self.supabase = supabase_client

    @ui.button(label="Sim, excluir tudo!", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        # ... (lógica do botão)
        pass
    @ui.button(label="Não, cancelar.", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        # ... (lógica do botão)
        pass

# ========= CLASSE DO COG =========

class PlayerCog(commands.Cog):
    """Cog para gerenciar todas as interações e comandos dos jogadores."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        url: str = os.environ.get("SUPABASE_URL")
        key: str = os.environ.get("SUPABASE_KEY")
        self.supabase: Client = create_client(url, key)
        print("PlayerCog carregado e conectado ao Supabase.")

    async def player_exists(self, discord_id: int) -> bool:
        # ... (código original sem alterações)
        pass

    @commands.command(name='start', help='Inicia sua aventura Pokémon.')
    async def start_adventure(self, ctx: commands.Context):
        # ... (código original sem alterações)
        pass

    @commands.command(name='profile', help='Mostra as informações do seu treinador.')
    async def profile(self, ctx: commands.Context):
        # ... (código original sem alterações)
        pass

    @commands.command(name='delete', help='Exclui permanentemente seu progresso para começar de novo.')
    async def delete_journey(self, ctx: commands.Context):
        # ... (código original sem alterações)
        pass

    # ==========================================================
    # =========== COMANDO DE AJUDA ATUALIZADO ==================
    # ==========================================================
    @commands.command(name='help', help='Mostra esta mensagem de ajuda.')
    async def custom_help(self, ctx: commands.Context, *, option: str = None):
        """Comando de ajuda customizado para o bot."""
        
        # Lógica para o !help simples
        if option is None:
            embed = discord.Embed(
                title="Ajuda do PokeAdventure",
                description="Aqui estão os comandos mais comuns para sua jornada.",
                color=discord.Color.orange()
            )
            embed.set_thumbnail(url="https://imgur.com/gallery/banner-banner-K9dL7")
            # Comandos do PlayerCog
            embed.add_field(name="`!start`", value="Inicia sua aventura e cria seu personagem.", inline=False)
            embed.add_field(name="`!profile`", value="Exibe seu perfil de treinador atual.", inline=False)
            # Novos comandos que estarão no EvolutionCog
            embed.add_field(name="`!shop`", value="Mostra a loja de itens evolutivos.", inline=False)
            embed.add_field(name="`!buy <item> <pokemon>`", value="Compra um item para evoluir um Pokémon.", inline=False)
            embed.add_field(name="`!delete`", value="Apaga seu progresso para começar uma nova jornada.", inline=False)
            embed.set_footer(text="Para ver a lista completa de comandos, digite `!help all`.")
            await ctx.send(embed=embed)
            
        # Lógica para o !help all
        elif option.lower() == 'all':
            embed = discord.Embed(
                title="Ajuda - Todos os Comandos",
                description="Lista completa de todos os comandos disponíveis.",
                color=discord.Color.dark_blue()
            )
            # Este loop encontra TODOS os comandos de TODOS os cogs carregados.
            # A condição 'if not command.hidden' é opcional, mas recomendada para
            # ocultar comandos de admin (como !givexp) da lista de ajuda.
            # Se quiser que os cheats apareçam, remova essa condição.
            for command in sorted(self.bot.commands, key=lambda c: c.name):
                if not command.hidden and command.name != 'help':
                    embed.add_field(
                        name=f"`!{command.name}`",
                        value=command.help or "Sem descrição disponível.",
                        inline=False
                    )
            await ctx.send(embed=embed)
        
        else:
            await ctx.send(f"Opção `{option}` inválida. Use `!help` ou `!help all`.")


async def setup(bot: commands.Bot):
    """Função de setup para carregar o Cog no bot principal."""
    await bot.add_cog(PlayerCog(bot))