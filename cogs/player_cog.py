import discord
import os
from discord.ext import commands
from discord import ui # Importamos a UI para usar Modals e Views
from supabase import create_client, Client

# ========= CLASSES DE UI (BOTÕES E MODALS) =========

# --- UI para o comando !start ---
class StartJourneyView(ui.View):
    """View inicial que aparece com o comando !start."""
    def __init__(self, supabase_client: Client):
        super().__init__(timeout=180) # A view expira em 3 minutos
        self.supabase = supabase_client

    @ui.button(label="Iniciar Jornada", style=discord.ButtonStyle.success, emoji="🎉")
    async def begin(self, interaction: discord.Interaction, button: ui.Button):
        """Este botão abre um formulário (Modal) para o jogador inserir o nome."""
        await interaction.response.send_modal(TrainerNameModal(supabase_client=self.supabase))

class TrainerNameModal(ui.Modal, title="Crie seu Personagem"):
    """Modal para o jogador inserir o nome do treinador."""
    def __init__(self, supabase_client: Client):
        super().__init__(timeout=300)
        self.supabase = supabase_client

    trainer_name_input = ui.TextInput(
        label="Qual será seu nome de treinador?",
        placeholder="Ex: Ash Ketchum",
        required=True,
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        """Após o envio do nome, oferece a escolha da região inicial."""
        trainer_name = self.trainer_name_input.value
        embed = discord.Embed(
            title="Escolha sua Região Inicial",
            description=f"Ótimo nome, **{trainer_name}**! Agora, escolha a região onde sua aventura vai começar.",
            color=discord.Color.blue()
        )
        # Responde à interação do Modal com a próxima etapa (escolha de região)
        await interaction.response.send_message(
            embed=embed,
            view=RegionSelectView(trainer_name=trainer_name, supabase_client=self.supabase),
            ephemeral=True # A mensagem só será visível para o usuário que interagiu
        )

class RegionSelectView(ui.View):
    """View com botões para selecionar a região inicial."""
    def __init__(self, trainer_name: str, supabase_client: Client):
        super().__init__(timeout=180)
        self.trainer_name = trainer_name
        self.supabase = supabase_client

    # A função decoradora 'select_region' será chamada quando qualquer botão for pressionado.
    async def select_region(self, interaction: discord.Interaction, region: str):
        """Lógica para registrar o jogador no banco de dados com a região escolhida."""
        await interaction.response.defer() # Confirma o recebimento da interação

        discord_id = interaction.user.id
        player_data = {
            'discord_id': discord_id,
            'trainer_name': self.trainer_name,
            'money': 1000,
            'badges': 0,
            'current_region': region, # Usa a região do botão clicado
            'masterballs_owned': 0
        }

        try:
            self.supabase.table('players').insert(player_data).execute()
            await interaction.followup.send(
                f"🎉 Bem-vindo ao mundo Pokémon, Treinador(a) **{self.trainer_name}**! 🎉\n"
                f"Sua aventura começa agora na região de **{region}**. Boa sorte!",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro ao salvar seus dados: {e}", ephemeral=True)
        
        # Desativa todos os botões após a escolha
        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(view=self)
        self.stop()

    @ui.button(label="Kanto", style=discord.ButtonStyle.primary, emoji="🟥")
    async def kanto(self, interaction: discord.Interaction, button: ui.Button):
        await self.select_region(interaction, "Kanto")

    @ui.button(label="Johto", style=discord.ButtonStyle.primary, emoji="🟨")
    async def johto(self, interaction: discord.Interaction, button: ui.Button):
        await self.select_region(interaction, "Johto")

    @ui.button(label="Hoenn", style=discord.ButtonStyle.primary, emoji="🟩")
    async def hoenn(self, interaction: discord.Interaction, button: ui.Button):
        await self.select_region(interaction, "Hoenn")

# --- UI para o comando !delete ---
class ConfirmDeleteView(ui.View):
    """Pede confirmação antes de uma ação destrutiva como deletar o save."""
    def __init__(self, supabase_client: Client):
        super().__init__(timeout=60)
        self.supabase = supabase_client

    @ui.button(label="Sim, excluir tudo!", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        discord_id = interaction.user.id
        try:
            # A mágica do 'ON DELETE CASCADE' no seu SQL deletará os dados relacionados
            # em outras tabelas (player_pokemon, player_inventory, etc.) automaticamente.
            self.supabase.table('players').delete().eq('discord_id', discord_id).execute()
            await interaction.response.send_message("Sua jornada foi reiniciada. Todo o progresso foi excluído. Use `!start` para começar de novo.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Ocorreu um erro ao excluir seus dados: {e}", ephemeral=True)
        
        # Desativa os botões
        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(view=self)
        self.stop()

    @ui.button(label="Não, cancelar.", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("Ação cancelada. Sua jornada continua!", ephemeral=True)
        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(view=self)
        self.stop()


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
        """Função auxiliar para verificar se um jogador já existe no banco."""
        try:
            response = self.supabase.table('players').select('discord_id').eq('discord_id', discord_id).execute()
            return bool(response.data)
        except Exception as e:
            print(f"Erro ao verificar jogador: {e}")
            return False

    @commands.command(name='start', help='Mostra a tela inicial para começar sua aventura.')
    async def start_adventure(self, ctx: commands.Context):
        """
        1. Dá as boas-vindas e oferece um botão para iniciar a jornada.
        """
        if await self.player_exists(ctx.author.id):
            await ctx.send(f"Olá novamente, {ctx.author.mention}! Você já tem uma jornada em andamento. Use `!profile` para ver seus dados ou `!delete` para começar de novo.")
            return

        embed = discord.Embed(
            title="Bem-vindo ao PokeAdventure!",
            description="Prepare-se para explorar um mundo vasto, capturar e treinar Pokémon e se tornar um Mestre!\n\nClique no botão abaixo para criar seu personagem e dar o primeiro passo.",
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url="https://i.imgur.com/p1z3iH7.png") # URL de uma Pokébola
        
        await ctx.send(embed=embed, view=StartJourneyView(supabase_client=self.supabase))

    @commands.command(name='profile', help='Mostra as informações do seu treinador.')
    async def profile(self, ctx: commands.Context):
        """
        4. Retorna os campos do treinador que executou o comando.
        """
        discord_id = ctx.author.id
        try:
            response = self.supabase.table('players').select('*').eq('discord_id', discord_id).single().execute()
            
            if not response.data:
                await ctx.send(f"Você ainda não começou sua jornada, {ctx.author.mention}. Use `!start` para iniciar!")
                return
            
            player = response.data
            
            # Cria um Embed para exibir os dados de forma organizada
            embed = discord.Embed(
                title=f"Perfil de Treinador: {player['trainer_name']}",
                color=discord.Color.green()
            )
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url)
            embed.add_field(name="<:pokemoney:12345> Dinheiro", value=f"${player['money']:,}", inline=True)
            embed.add_field(name="🏅 Insígnias", value=str(player['badges']), inline=True)
            embed.add_field(name="📍 Localização Atual", value=player['current_region'], inline=False)
            embed.add_field(name="<:masterball:12345> Master Balls", value=str(player['masterballs_owned']), inline=True)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"Ocorreu um erro ao buscar seu perfil: {e}")

    @commands.command(name='delete', help='Exclui permanentemente seu progresso para começar de novo.')
    async def delete_journey(self, ctx: commands.Context):
        """
        2. Oferece a opção de excluir a jornada atual.
        """
        if not await self.player_exists(ctx.author.id):
            await ctx.send(f"Você não tem uma jornada para excluir, {ctx.author.mention}. Use `!start` para começar uma!")
            return

        embed = discord.Embed(
            title="⚠️ Atenção: Excluir Jornada ⚠️",
            description="Você tem certeza que deseja excluir **todo** o seu progresso? Esta ação é **irreversível** e todos os seus Pokémon, itens e dados serão perdidos.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, view=ConfirmDeleteView(supabase_client=self.supabase), ephemeral=True)


async def setup(bot: commands.Bot):
    """Função de setup para carregar o Cog no bot principal."""
    await bot.add_cog(PlayerCog(bot))