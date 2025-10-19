import discord
import os
from discord.ext import commands
from discord import ui
from supabase import create_client, Client

# ========= CLASSES DE UI (BOTÕES E MODALS) =========

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
    
    @ui.button(label="Johto", style=discord.ButtonStyle.primary, emoji="2️⃣")
    async def johto(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Johto")
    
    @ui.button(label="Hoenn", style=discord.ButtonStyle.primary, emoji="3️⃣")
    async def hoenn(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Hoenn")
    
    @ui.button(label="Sinnoh", style=discord.ButtonStyle.primary, emoji="4️⃣")
    async def sinnoh(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Sinnoh")
    
    @ui.button(label="Unova", style=discord.ButtonStyle.primary, emoji="5️⃣")
    async def unova(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Unova")
    
    @ui.button(label="Kalos", style=discord.ButtonStyle.primary, emoji="6️⃣")
    async def kalos(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Kalos")
    
    @ui.button(label="Alola", style=discord.ButtonStyle.primary, emoji="7️⃣")
    async def alola(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Alola")
    
    @ui.button(label="Galar", style=discord.ButtonStyle.primary, emoji="8️⃣")
    async def galar(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Galar")
    
    @ui.button(label="Paldea", style=discord.ButtonStyle.primary, emoji="9️⃣")
    async def paldea(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Paldea")

class ConfirmDeleteView(ui.View):
    def __init__(self, supabase_client: Client):
        super().__init__(timeout=60)
        self.supabase = supabase_client

    @ui.button(label="Sim, excluir tudo!", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        discord_id = interaction.user.id
        try:
            self.supabase.table('players').delete().eq('discord_id', discord_id).execute()
            # Idealmente, também deletaria os pokémons e inventário associados
            await interaction.response.send_message("Sua jornada foi reiniciada. Todo o progresso foi excluído. Use `!start` para começar de novo.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Ocorreu um erro ao excluir seus dados: {e}", ephemeral=True)
        for item in self.children: item.disabled = True
        await interaction.edit_original_response(view=self)
        self.stop()

    @ui.button(label="Não, cancelar.", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("Ação cancelada. Sua jornada continua!", ephemeral=True)
        for item in self.children: item.disabled = True
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
        try:
            response = self.supabase.table('players').select('discord_id').eq('discord_id', discord_id).execute()
            return bool(response.data)
        except Exception as e:
            print(f"Erro ao verificar jogador: {e}")
            return False

    @commands.command(name='start', help='Inicia sua aventura Pokémon.')
    async def start_adventure(self, ctx: commands.Context):
        if await self.player_exists(ctx.author.id):
            await ctx.send(f"Olá novamente, {ctx.author.mention}! Você já tem uma jornada em andamento. Use `!profile` para ver seus dados ou `!delete` para começar de novo.")
            return
        embed = discord.Embed(title="Bem-vindo ao PokeAdventure!", description="Prepare-se para explorar um mundo vasto, capturar e treinar Pokémon e se tornar um Mestre!\n\nClique no botão abaixo para criar seu personagem e dar o primeiro passo.", color=discord.Color.gold())
        embed.set_thumbnail(url="https://i.imgur.com/p1z3iH7.png")
        await ctx.send(embed=embed, view=StartJourneyView(supabase_client=self.supabase))

    @commands.command(name='profile', help='Mostra as informações do seu treinador.')
    async def profile(self, ctx: commands.Context):
        discord_id = ctx.author.id
        try:
            response = self.supabase.table('players').select('*').eq('discord_id', discord_id).single().execute()
            player = response.data
            
            embed = discord.Embed(title=f"Perfil de Treinador: {player['trainer_name']}", color=discord.Color.green())
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url)
            embed.add_field(name="💰 Dinheiro", value=f"${player['money']:,}", inline=True)
            embed.add_field(name="🏅 Insígnias", value=str(player['badges']), inline=True)
            embed.add_field(name="📍 Localização Atual", value=player['current_region'], inline=False)
            await ctx.send(embed=embed)
        except Exception:
            await ctx.send(f"Você ainda não começou sua jornada, {ctx.author.mention}. Use `!start` para iniciar!")

    @commands.command(name='delete', help='Exclui permanentemente seu progresso para começar de novo.')
    async def delete_journey(self, ctx: commands.Context):
        if not await self.player_exists(ctx.author.id):
            await ctx.send(f"Você não tem uma jornada para excluir, {ctx.author.mention}. Use `!start` para começar uma!")
            return
        embed = discord.Embed(title="⚠️ Atenção: Excluir Jornada ⚠️", description="Você tem certeza que deseja excluir **todo** o seu progresso? Esta ação é **irreversível**.", color=discord.Color.red())
        await ctx.send(embed=embed, view=ConfirmDeleteView(supabase_client=self.supabase), ephemeral=True)

    @commands.command(name='help', help='Mostra esta mensagem de ajuda.')
    async def custom_help(self, ctx: commands.Context, *, option: str = None):
        """Comando de ajuda customizado para o bot."""
        if option is None:
            embed = discord.Embed(title="Ajuda do PokeAdventure", description="Aqui estão os comandos mais comuns para sua jornada.", color=discord.Color.orange())
            embed.set_thumbnail(url="https://i.imgur.com/p1z3iH7.png")
            embed.add_field(name="`!start`", value="Inicia sua aventura e cria seu personagem.", inline=False)
            embed.add_field(name="`!profile`", value="Exibe seu perfil de treinador atual.", inline=False)
            embed.add_field(name="`!team`", value="Mostra todos os seus Pokémon capturados.", inline=False)
            embed.add_field(name="`!shop`", value="Mostra a loja de itens evolutivos.", inline=False)
            embed.add_field(name="`!buy <item> <pokemon>`", value="Compra um item para evoluir um Pokémon.", inline=False)
            embed.add_field(name="`!delete`", value="Apaga seu progresso para começar uma nova jornada.", inline=False)
            embed.set_footer(text="Para ver a lista completa de comandos, digite `!help all`.")
            await ctx.send(embed=embed)
            
        elif option.lower() == 'all':
            embed = discord.Embed(title="Ajuda - Todos os Comandos", description="Lista completa de todos os comandos disponíveis.", color=discord.Color.dark_blue())
            
            # Este loop encontra TODOS os comandos de TODOS os cogs.
            for command in sorted(self.bot.commands, key=lambda c: c.name):
                # Se você quiser esconder os cheats de admin, adicione `hidden=True` neles
                # e descomente a linha abaixo.
                # if not command.hidden and command.name != 'help':
                if command.name != 'help':
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