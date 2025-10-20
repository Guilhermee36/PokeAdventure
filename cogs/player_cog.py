import discord
from discord.ext import commands
from discord import ui
import random
import aiohttp
from supabase import create_client, Client
import os

# =================================================================
# ALTERAÇÃO 1: Reimportando a função de buscar ataques
# Assumindo que este arquivo e a função existem no seu projeto.
# from utils.pokeapi_service import get_initial_moves 
# =================================================================

# --- Helper Functions ---

async def fetch_pokemon_data(pokemon_name: str):
    """Busca dados de um Pokémon da PokeAPI."""
    url = f"https://pokeapi.co/api/v2/pokemon/{pokemon_name.lower()}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.json()
            return None

def get_supabase_client():
    """Cria e retorna um cliente Supabase."""
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY")
    return create_client(url, key)

# MOCKUP da função, caso você não tenha o arquivo utils pronto.
# Substitua isso pelo seu import real.
def get_initial_moves(pokemon_data, level):
    """Mockup: Pega os 4 primeiros ataques aprendidos até o nível 5."""
    moves = []
    for move_data in pokemon_data['moves']:
        for version_group in move_data['version_group_details']:
            if version_group['move_learn_method']['name'] == 'level-up' and version_group['level_learned_at'] <= level and version_group['level_learned_at'] > 0:
                moves.append(move_data['move']['name'])
                if len(moves) >= 4:
                    return list(set(moves)) # Remove duplicatas e retorna
    return list(set(moves)) if moves else ["tackle"] # Garante que tenha pelo menos um ataque

# =================================================================
# ALTERAÇÃO 2: Atualizando a função central para incluir os ataques
# =================================================================
async def add_pokemon_to_player(player_id: int, pokemon_api_name: str, level: int = 5, captured_at: str = "Início da Jornada") -> dict:
    """Função centralizada que agora também adiciona os ataques iniciais."""
    supabase = get_supabase_client()
    try:
        count_response = supabase.table("player_pokemon").select("id", count='exact').eq("player_id", player_id).execute()
        pokemon_count = count_response.count
    except Exception as e:
        return {'success': False, 'error': f"Erro ao contar Pokémon: {e}"}

    if pokemon_count >= 6:
        return {'success': False, 'error': "Seu time já está cheio! Você não pode carregar mais de 6 Pokémon."}
        
    poke_data = await fetch_pokemon_data(pokemon_api_name)
    if not poke_data:
        return {'success': False, 'error': f"Pokémon '{pokemon_api_name}' não encontrado na API."}
    
    # Lógica para HP, Shiny, Posição...
    base_hp = poke_data['stats'][0]['base_stat']
    current_hp = int((2 * base_hp * level) / 100) + level + 10
    is_shiny = random.randint(1, 100) == 1
    party_position = pokemon_count + 1
    
    # >>> BUSCA E ADICIONA OS ATAQUES AQUI <<<
    initial_moves = get_initial_moves(poke_data, level)

    new_pokemon_data = { 
        "player_id": player_id, 
        "pokemon_api_name": pokemon_api_name, 
        "captured_at_location": captured_at, 
        "is_shiny": is_shiny, 
        "party_position": party_position, 
        "current_level": level, 
        "current_hp": current_hp, 
        "current_xp": 0,
        "moves": initial_moves # Adiciona a lista de ataques ao registro
    }
    
    try:
        insert_response = supabase.table("player_pokemon").insert(new_pokemon_data).execute()
        if len(insert_response.data) > 0:
            return {'success': True, 'message': f"Pokémon adicionado com sucesso na posição {party_position}!", 'data': insert_response.data[0]}
        else:
            return {'success': False, 'error': "Falha ao inserir o Pokémon no banco de dados."}
    except Exception as e:
        return {'success': False, 'error': f"Erro no banco de dados: {e}"}

# --- Classes de UI (O restante do código permanece o mesmo) ---

class StartJourneyView(ui.View):
    def __init__(self, supabase_client: Client):
        super().__init__(timeout=None)
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

class StarterSelectView(ui.View):
    def __init__(self, region: str):
        super().__init__(timeout=180)
        self.region = region
        starters = {
            "Kanto": ["bulbasaur", "charmander", "squirtle"], "Johto": ["chikorita", "cyndaquil", "totodile"],
            "Hoenn": ["treecko", "torchic", "mudkip"], "Sinnoh": ["turtwig", "chimchar", "piplup"],
            "Unova": ["snivy", "tepig", "oshawott"], "Kalos": ["chespin", "fennekin", "froakie"],
            "Alola": ["rowlet", "litten", "popplio"], "Galar": ["grookey", "scorbunny", "sobble"],
            "Paldea": ["sprigatito", "fuecoco", "quaxly"]
        }
        for starter in starters.get(region, []):
            button = ui.Button(label=starter.capitalize(), style=discord.ButtonStyle.primary, custom_id=starter)
            button.callback = self.select_starter
            self.add_item(button)

    async def select_starter(self, interaction: discord.Interaction):
        starter_name = interaction.data['custom_id']
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(view=self)
        result = await add_pokemon_to_player(player_id=interaction.user.id, pokemon_api_name=starter_name, level=5, captured_at=f"Recebido em {self.region}")
        if result['success']:
            pokemon_data = result['data']
            is_shiny = pokemon_data.get('is_shiny', False)
            shiny_text = "\n\n✨ **UAU, ELE É SHINY! QUE SORTE!** ✨" if is_shiny else ""
            public_embed = discord.Embed(title="Uma Nova Jornada Começa!", description=f"{interaction.user.mention} iniciou sua aventura e escolheu **{starter_name.capitalize()}** como seu primeiro parceiro!{shiny_text}", color=discord.Color.green())
            poke_api_data = await fetch_pokemon_data(starter_name)
            if poke_api_data:
                sprite_url = poke_api_data['sprites']['front_shiny'] if is_shiny else poke_api_data['sprites']['front_default']
                public_embed.set_thumbnail(url=sprite_url)
            await interaction.followup.send(embed=public_embed)
        else:
            await interaction.followup.send(f"Ocorreu um erro ao adicionar seu Pokémon: {result['error']}", ephemeral=True)
        self.stop()

class RegionSelectView(ui.View):
    def __init__(self, trainer_name: str, supabase_client: Client):
        super().__init__(timeout=180)
        self.trainer_name = trainer_name
        self.supabase = supabase_client

    async def select_region(self, interaction: discord.Interaction, region: str):
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(view=self)
        discord_id = interaction.user.id
        player_data = {'discord_id': discord_id, 'trainer_name': self.trainer_name, 'current_region': region}
        try:
            self.supabase.table('players').insert(player_data).execute()
            starter_embed = discord.Embed(title=f"Bem-vindo(a) a {region}!", description="Agora, a escolha mais importante: quem será seu parceiro inicial?", color=discord.Color.blue())
            await interaction.followup.send(embed=starter_embed, view=StarterSelectView(region=region), ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro ao salvar seus dados: {e}", ephemeral=True)
        self.stop()

    @ui.button(label="Kanto", style=discord.ButtonStyle.primary, emoji="1️⃣", row=0)
    async def kanto(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Kanto")
    @ui.button(label="Johto", style=discord.ButtonStyle.primary, emoji="2️⃣", row=0)
    async def johto(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Johto")
    @ui.button(label="Hoenn", style=discord.ButtonStyle.primary, emoji="3️⃣", row=0)
    async def hoenn(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Hoenn")
    @ui.button(label="Sinnoh", style=discord.ButtonStyle.primary, emoji="4️⃣", row=1)
    async def sinnoh(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Sinnoh")
    @ui.button(label="Unova", style=discord.ButtonStyle.primary, emoji="5️⃣", row=1)
    async def unova(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Unova")
    @ui.button(label="Kalos", style=discord.ButtonStyle.primary, emoji="6️⃣", row=1)
    async def kalos(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Kalos")
    @ui.button(label="Alola", style=discord.ButtonStyle.primary, emoji="7️⃣", row=2)
    async def alola(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Alola")
    @ui.button(label="Galar", style=discord.ButtonStyle.primary, emoji="8️⃣", row=2)
    async def galar(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Galar")
    @ui.button(label="Paldea", style=discord.ButtonStyle.primary, emoji="9️⃣", row=2)
    async def paldea(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Paldea")

class ConfirmDeleteView(ui.View):
    def __init__(self, supabase_client: Client):
        super().__init__(timeout=60)
        self.supabase = supabase_client

    @ui.button(label="Sim, excluir tudo!", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(view=self)
        try:
            self.supabase.table('players').delete().eq('discord_id', interaction.user.id).execute()
            await interaction.followup.send("Sua jornada foi reiniciada. Todo o progresso foi excluído. Use `!start` para começar de novo.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro ao excluir seus dados: {e}", ephemeral=True)
        self.stop()

    @ui.button(label="Não, cancelar.", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send("Ação cancelada. Sua jornada continua!", ephemeral=True)
        self.stop()

# --- Cog Class ---

class PlayerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.supabase: Client = get_supabase_client()

    async def player_exists(self, discord_id: int) -> bool:
        response = self.supabase.table('players').select('discord_id').eq('discord_id', discord_id).execute()
        return bool(response.data)

    @commands.command(name='start')
    async def start_adventure(self, ctx: commands.Context):
        if await self.player_exists(ctx.author.id):
            await ctx.send(f"Olá novamente, {ctx.author.mention}! Você já tem uma jornada em andamento.")
            return
        embed = discord.Embed(title="Bem-vindo ao PokeAdventure!", description="Clique no botão abaixo para criar seu personagem e dar o primeiro passo.", color=discord.Color.gold())
        await ctx.send(embed=embed, view=StartJourneyView(supabase_client=self.supabase))

    @commands.command(name='profile')
    async def profile(self, ctx: commands.Context):
        try:
            player = self.supabase.table('players').select('*').eq('discord_id', ctx.author.id).single().execute().data
            if not player:
                await ctx.send(f"Você ainda não começou sua jornada, {ctx.author.mention}. Use `!start` para iniciar!")
                return
            embed = discord.Embed(title=f"Perfil de: {player['trainer_name']}", color=discord.Color.green())
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url)
            embed.add_field(name="💰 Dinheiro", value=f"${player.get('money', 0):,}", inline=True)
            embed.add_field(name="🏅 Insígnias", value=str(player.get('badges', 0)), inline=True)
            embed.add_field(name="📍 Localização", value=player.get('current_region', 'Desconhecida'), inline=False)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"Ocorreu um erro ao buscar seu perfil: {e}")

    @commands.command(name='addpokemon')
    @commands.is_owner()
    async def add_pokemon(self, ctx: commands.Context, pokemon_name: str, level: int = 5):
        if not await self.player_exists(ctx.author.id):
            await ctx.send(f"Você precisa iniciar sua jornada primeiro! Use `!start`.")
            return
        result = await add_pokemon_to_player(player_id=ctx.author.id, pokemon_api_name=pokemon_name, level=level, captured_at="Comando de Admin")
        if result['success']:
            await ctx.send(f"✅ {pokemon_name.capitalize()} foi adicionado ao seu time! {result['message']}")
        else:
            await ctx.send(f"❌ Erro: {result['error']}")

    @commands.command(name='delete')
    async def delete_journey(self, ctx: commands.Context):
        if not await self.player_exists(ctx.author.id):
            await ctx.send(f"Você não tem uma jornada para excluir, {ctx.author.mention}.")
            return
        embed = discord.Embed(title="⚠️ Atenção: Excluir Jornada ⚠️", description="Você tem certeza que deseja excluir **todo** o seu progresso? Esta ação é **irreversível**.", color=discord.Color.red())
        await ctx.send(embed=embed, view=ConfirmDeleteView(supabase_client=self.supabase), ephemeral=True)

    @commands.command(name='help')
    async def custom_help(self, ctx: commands.Context):
        embed = discord.Embed(title="Ajuda do PokeAdventure", description="Comandos para sua jornada.", color=discord.Color.orange())
        embed.add_field(name="`!start`", value="Inicia sua aventura e cria seu personagem.", inline=False)
        embed.add_field(name="`!profile`", value="Exibe seu perfil de treinador.", inline=False)
        embed.add_field(name="`!team`", value="Mostra sua equipe de Pokémon.", inline=False)
        embed.add_field(name="`!delete`", value="Apaga seu progresso para começar de novo.", inline=False)
        if await self.bot.is_owner(ctx.author):
            embed.add_field(name="--- Comandos de Administrador ---", value="`!addpokemon <nome> [level]`", inline=False)
        await ctx.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(PlayerCog(bot))