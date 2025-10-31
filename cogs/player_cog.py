import discord
from discord.ext import commands
from discord import ui
import random
import aiohttp
from supabase import create_client, Client
import os
import asyncio # Import necessário para o _get_player_team_count

# =================================================================
# Importando os serviços reais da pasta utils
# (Assumindo que pokeapi_service.py está em utils/)
# =================================================================
import utils.pokeapi_service as pokeapi 
# from utils.pokeapi_service import get_initial_moves # Esta função específica não existe no seu pokeapi_service.py, vamos recriá-la aqui.


# --- Helper Functions ---

async def fetch_pokemon_data(pokemon_name: str):
    """Busca dados de um Pokémon da PokeAPI. (Usando o helper)"""
    # Esta função está duplicada, o player_cog deveria idealmente
    # importar e usar as funções de 'utils.pokeapi_service'
    # mas vamos manter seu helper local por enquanto para evitar quebrar.
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

# =================================================================
# Função de ataques (Mockup do seu arquivo original)
# =================================================================
def get_initial_moves(pokemon_data, level):
    """Mockup: Pega até 4 ataques aprendidos até o nível 5."""
    
    # Esta é uma lógica SIMULADA. O ideal é usar o pokeapi_service.py
    # para buscar os moves reais por 'version-group' e 'level-learned-at'
    
    # Pega os 4 primeiros moves, independentemente do nível (para garantir)
    possible_moves = [move_info['move']['name'] for move_info in pokemon_data.get('moves', [])]
    
    # Preenche a lista de movimentos
    moves = [None, None, None, None]
    for i in range(min(len(possible_moves), 4)):
        moves[i] = possible_moves[i]
        
    return moves


# --- Views (Modal e Botões) ---

class PlayerNameModal(ui.Modal, title='Crie seu Treinador'):
    """Modal para inserção do nome do treinador."""
    player_name = ui.TextInput(
        label='Qual é o seu nome, Treinador?',
        placeholder='Ash Ketchum',
        style=discord.TextStyle.short,
        required=True,
        min_length=3,
        max_length=50
    )

    def __init__(self, supabase_client: Client, cog_ref: commands.Cog):
        super().__init__(timeout=300)
        self.supabase = supabase_client
        self.cog = cog_ref

    async def on_submit(self, interaction: discord.Interaction):
        player_id = interaction.user.id
        player_name = self.player_name.value
        
        await interaction.response.defer(thinking=True, ephemeral=True)
        
        try:
            # 1. Insere o jogador
            player_data = {
                "discord_id": player_id,
                "trainer_name": player_name,
                "current_region": "unova", # Região Padrão
                "current_location": "starter-town" # Localização Padrão
            }
            self.supabase.table("players").insert(player_data).execute()
            
            # 2. Cria o Pokémon inicial (Oshawott)
            # Usando a função helper do Cog
            starter_pokemon = await self.cog._create_starter_pokemon(player_id, "oshawott", 5)
            
            if not starter_pokemon:
                 await interaction.followup.send("Erro: Não foi possível criar seu Pokémon inicial. O registro do jogador foi revertido.", ephemeral=True)
                 # Rollback (Remove o jogador se o Pokémon falhar)
                 self.supabase.table("players").delete().eq("discord_id", player_id).execute()
                 return
            
            await interaction.followup.send(f"Parabéns, Treinador {player_name}! Você iniciou sua jornada com um Oshawott! Use `!team` para vê-lo.", ephemeral=True)

        except Exception as e:
            # Verifica se o erro é de violação de chave única (jogador já existe)
            if "duplicate key value violates unique constraint" in str(e):
                await interaction.followup.send("Você já tem uma jornada em andamento! Use `!profile` para ver.", ephemeral=True)
            else:
                print(f"Erro ao criar jogador: {e}")
                await interaction.followup.send("Ocorreu um erro inesperado ao criar seu personagem.", ephemeral=True)

class ConfirmDeleteView(ui.View):
    """Botões de confirmação para exclusão de jornada."""
    def __init__(self, supabase_client: Client):
        super().__init__(timeout=60)
        self.supabase = supabase_client

    @ui.button(label='Sim, excluir tudo!', style=discord.ButtonStyle.danger)
    async def confirm_delete(self, interaction: discord.Interaction, button: ui.Button):
        player_id = interaction.user.id
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Exclui em cascata (Supabase deve estar configurado para isso)
            # 1. Exclui Pokémon
            self.supabase.table("player_pokemon").delete().eq("player_id", player_id).execute()
            # 2. Exclui Itens (se houver)
            # self.supabase.table("player_inventory").delete().eq("player_id", player_id).execute()
            # 3. Exclui Quests (se houver)
            self.supabase.table("player_quests").delete().eq("player_id", player_id).execute()
            # 4. Exclui Jogador
            self.supabase.table("players").delete().eq("discord_id", player_id).execute()
            
            await interaction.followup.send("Sua jornada foi reiniciada. Use `!start` para começar uma nova.", ephemeral=True)
        except Exception as e:
            print(f"Erro ao excluir jornada: {e}")
            await interaction.followup.send("Ocorreu um erro ao tentar excluir sua jornada. Contate um administrador.", ephemeral=True)

    @ui.button(label='Não, cancelar.', style=discord.ButtonStyle.secondary)
    async def cancel_delete(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.edit_message(content="Exclusão cancelada.", embed=None, view=None)


# --- Cog Principal ---

class PlayerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.supabase: Client = get_supabase_client()

    async def player_exists(self, player_id: int) -> bool:
        """Verifica se um jogador já existe no banco."""
        try:
            response = self.supabase.table("players").select("discord_id").eq("discord_id", player_id).limit(1).execute()
            return bool(response.data)
        except Exception as e:
            print(f"Erro ao checar jogador: {e}")
            return False

    async def _get_player_team_count(self, player_id: int) -> int:
        """Conta quantos Pokémon o jogador tem no time (party_position não nulo)."""
        try:
            # Usamos a função count do supabase
            response = await asyncio.to_thread(
                self.supabase.table("player_pokemon")
                .select("id", head=False, count='exact') # 'head=False' é importante para 'count'
                .eq("player_id", player_id)
                .not_is("party_position", "null")
                .execute
            )
            return response.count
        except Exception as e:
            print(f"Erro ao contar time: {e}")
            return 0
            
    async def _get_player_data(self, player_id: int) -> dict | None:
        """Busca os dados do perfil do jogador."""
        try:
            response = self.supabase.table("players").select("*").eq("discord_id", player_id).limit(1).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Erro ao buscar dados do jogador: {e}")
            return None

    # =================================================================
    # CORREÇÃO APLICADA AQUI
    # =================================================================
    async def _create_starter_pokemon(self, player_id: int, pokemon_name: str, level: int = 5):
        """Cria e insere o Pokémon inicial no banco de dados."""
        pokemon_data = await fetch_pokemon_data(pokemon_name) # Usa o helper local
        if not pokemon_data:
            return None

        # Calcula stats (simples)
        stats = {s['stat']['name']: s['base_stat'] for s in pokemon_data['stats']}
        hp = stats.get('hp', 1) * 2 + 50 # Cálculo simulado
        
        # ALTERAÇÃO 4: Padronizando os 4 slots de moves
        initial_moves = get_initial_moves(pokemon_data, level) # Usa o helper local

        pokemon_insert_data = {
            "player_id": player_id,
            "pokemon_api_name": pokemon_name,
            "nickname": pokemon_name.capitalize(),
            "current_level": level,
            "current_xp": 0,
            "current_hp": hp, 
            "max_hp": hp,
            "attack": stats.get('attack', 1),
            "defense": stats.get('defense', 1),
            "special_attack": stats.get('special-attack', 1),
            "special_defense": stats.get('special-defense', 1),
            "speed": stats.get('speed', 1),
            "moves": initial_moves,
            # ==================================
            # !!! CORREÇÃO ADICIONADA AQUI !!!
            # ==================================
            "party_position": 1 
        }
        
        try:
            response = self.supabase.table("player_pokemon").insert(pokemon_insert_data).execute()
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Erro ao inserir starter no Supabase: {e}")
            return None

    # --- Comandos do Jogador ---

    @commands.command(name='start')
    async def start_journey(self, ctx: commands.Context):
        """Inicia a jornada do treinador."""
        if await self.player_exists(ctx.author.id):
            await ctx.send(f"Você já tem uma jornada em andamento, {ctx.author.mention}! Use `!profile` para ver.")
            return
        
        # Envia o Modal para o usuário
        modal = PlayerNameModal(supabase_client=self.supabase, cog_ref=self)
        await ctx.send_modal(modal)

    @commands.command(name='profile')
    async def profile(self, ctx: commands.Context):
        """Mostra o perfil do treinador."""
        player_id = ctx.author.id
        if not await self.player_exists(player_id):
            await ctx.send(f"Você ainda não começou sua jornada, {ctx.author.mention}. Use `!start`!")
            return

        data = await self._get_player_data(player_id)
        if not data:
            await ctx.send("Não consegui encontrar seus dados.")
            return

        team_count = await self._get_player_team_count(player_id)
        
        embed = discord.Embed(
            title=f"Perfil de {data['trainer_name']}",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        embed.add_field(name="Região Atual", value=data['current_region'].capitalize(), inline=True)
        embed.add_field(name="Localização", value=data['current_location'].capitalize(), inline=True)
        embed.add_field(name="Pokémon no Time", value=f"{team_count} / 6", inline=False)
        # embed.add_field(name="Insignias", value=len(data.get('badges', [])), inline=True)
        
        await ctx.send(embed=embed)


    @commands.command(name='delete')
    async def delete_journey(self, ctx: commands.Context):
        """Exclui a jornada do jogador para recomeçar."""
        if not await self.player_exists(ctx.author.id):
            await ctx.send(f"Você não tem uma jornada para excluir, {ctx.author.mention}.")
            return
        
        embed = discord.Embed(title="⚠️ Atenção: Excluir Jornada ⚠️", description="Você tem certeza que deseja excluir **todo** o seu progresso? Esta ação é **irreversível**.", color=discord.Color.red())
        # Envia a mensagem de forma efêmera (só o usuário vê)
        await ctx.send(embed=embed, view=ConfirmDeleteView(supabase_client=self.supabase), ephemeral=True)

    @commands.command(name='help')
    async def custom_help(self, ctx: commands.Context):
        """Mostra os comandos principais."""
        embed = discord.Embed(title="Ajuda do PokeAdventure", description="Comandos para sua jornada.", color=discord.Color.orange())
        embed.add_field(name="`!start`", value="Inicia sua aventura e cria seu personagem.", inline=False)
        embed.add_field(name="`!profile`", value="Exibe seu perfil de treinador.", inline=False)
        embed.add_field(name="`!team`", value="Mostra sua equipe de Pokémon.", inline=False)
        embed.add_field(name="`!delete`", value="Apaga seu progresso para começar de novo.", inline=False)
        
        if await self.bot.is_owner(ctx.author):
            embed.add_field(name="--- Comandos de Administrador ---", value="`!cog reload player_cog` - Recarrega este módulo.", inline=False)
            
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    """Registra o Cog no bot."""
    await bot.add_cog(PlayerCog(bot))