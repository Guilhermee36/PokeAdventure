import discord
from discord.ext import commands
from discord import app_commands
import random
import aiohttp
from supabase import create_client, Client
import os

# --- Helper Functions (Idealmente, mova para um arquivo utils.py no futuro) ---

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

# --- Core Pokémon Logic ---

async def add_pokemon_to_player(player_id: int, pokemon_api_name: str, level: int = 5, captured_at: str = "Início da Jornada") -> dict:
    """
    Função centralizada para adicionar um Pokémon a um jogador.
    Verifica o limite do time, calcula a próxima posição e insere no DB.
    Retorna um dicionário com 'success' e 'message' ou 'error'.
    """
    supabase = get_supabase_client()
    
    # 1. Verificar a quantidade de Pokémon que o jogador já tem
    try:
        count_response = supabase.table("player_pokemon").select("id", count='exact').eq("player_id", player_id).execute()
        pokemon_count = count_response.count
    except Exception as e:
        return {'success': False, 'error': f"Erro ao contar Pokémon: {e}"}

    # 2. Impedir adição se o time estiver cheio (6 Pokémon)
    if pokemon_count >= 6:
        return {'success': False, 'error': "Seu time já está cheio! Você não pode carregar mais de 6 Pokémon."}
        
    # 3. Buscar dados da PokeAPI para o HP base
    poke_data = await fetch_pokemon_data(pokemon_api_name)
    if not poke_data:
        return {'success': False, 'error': f"Pokémon '{pokemon_api_name}' não encontrado na API."}
    
    base_hp = poke_data['stats'][0]['base_stat']
    # Fórmula simples para HP inicial, pode ser aprimorada depois
    current_hp = int((2 * base_hp * level) / 100) + level + 10

    # 4. Calcular chance de ser shiny (1 em 100, ou 1%)
    is_shiny = random.randint(1, 100) == 1
    
    # 5. Determinar a posição no time
    party_position = pokemon_count + 1

    # 6. Montar e inserir os dados no banco
    new_pokemon_data = {
        "player_id": player_id,
        "pokemon_api_name": pokemon_api_name,
        "captured_at_location": captured_at,
        "is_shiny": is_shiny,
        "party_position": party_position,
        "current_level": level,
        "current_hp": current_hp,
        "current_xp": 0
    }
    
    try:
        insert_response = supabase.table("player_pokemon").insert(new_pokemon_data).execute()
        if len(insert_response.data) > 0:
            return {'success': True, 'message': f"Pokémon adicionado com sucesso na posição {party_position}!", 'data': insert_response.data[0]}
        else:
            return {'success': False, 'error': "Falha ao inserir o Pokémon no banco de dados."}
    except Exception as e:
        return {'success': False, 'error': f"Erro no banco de dados: {e}"}


# --- Modals & Views ---

class TrainerNameModal(discord.ui.Modal, title="Nome de Treinador"):
    trainer_name = discord.ui.TextInput(
        label="Qual será seu nome de treinador?",
        placeholder="Ex: Ash Ketchum",
        required=True,
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        supabase = get_supabase_client()
        player_id = interaction.user.id
        
        # Cria o jogador na tabela 'players'
        try:
            supabase.table("players").insert({
                "discord_id": player_id,
                "trainer_name": self.trainer_name.value
            }).execute()
        except Exception as e:
            await interaction.response.send_message(f"Ocorreu um erro ao criar seu perfil: {e}", ephemeral=True)
            return

        view = RegionSelectView()
        await interaction.response.send_message(
            f"Bem-vindo, {self.trainer_name.value}! Agora, escolha sua região inicial.",
            view=view,
            ephemeral=True
        )

class StarterSelectView(discord.ui.View):
    def __init__(self, region: str):
        super().__init__(timeout=180)
        self.region = region
        starters = {
            "Kanto": ["bulbasaur", "charmander", "squirtle"],
            "Johto": ["chikorita", "cyndaquil", "totodile"],
            "Hoenn": ["treecko", "torchic", "mudkip"]
        }
        
        for starter in starters.get(region, []):
            button = discord.ui.Button(label=starter.capitalize(), style=discord.ButtonStyle.primary, custom_id=starter)
            button.callback = self.select_starter
            self.add_item(button)

    async def select_starter(self, interaction: discord.Interaction):
        starter_name = interaction.data['custom_id']
        await interaction.response.defer(ephemeral=True) # Confirma o recebimento da interação

        # Desativa todos os botões para impedir nova escolha
        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(view=self)

        # Chama a função central para adicionar o Pokémon
        result = await add_pokemon_to_player(
            player_id=interaction.user.id,
            pokemon_api_name=starter_name,
            level=5,
            captured_at=f"Recebido em {self.region}"
        )
        
        if result['success']:
            pokemon_data = result['data']
            is_shiny = pokemon_data.get('is_shiny', False)
            
            shiny_text = "✨ UAU, ELE É SHINY! ✨" if is_shiny else ""
            
            embed = discord.Embed(
                title="Pokémon Inicial Escolhido!",
                description=f"Parabéns! Você escolheu **{starter_name.capitalize()}** para iniciar sua jornada!\n{shiny_text}",
                color=discord.Color.green()
            )
            # Fetch sprite para o embed
            poke_data = await fetch_pokemon_data(starter_name)
            if poke_data:
                sprite_url = poke_data['sprites']['front_default']
                if is_shiny:
                    sprite_url = poke_data['sprites']['front_shiny']
                embed.set_thumbnail(url=sprite_url)

            await interaction.followup.send(embed=embed, ephemeral=False) # Envia para o canal
        else:
            await interaction.followup.send(f"Ocorreu um erro: {result['error']}", ephemeral=True)


class RegionSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="Kanto", style=discord.ButtonStyle.success)
    async def kanto_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = StarterSelectView(region="Kanto")
        await interaction.response.send_message("Você escolheu Kanto! Quem será seu parceiro?", view=view, ephemeral=True)

    @discord.ui.button(label="Johto", style=discord.ButtonStyle.danger)
    async def johto_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = StarterSelectView(region="Johto")
        await interaction.response.send_message("Você escolheu Johto! Quem será seu parceiro?", view=view, ephemeral=True)
        
    @discord.ui.button(label="Hoenn", style=discord.ButtonStyle.primary)
    async def hoenn_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = StarterSelectView(region="Hoenn")
        await interaction.response.send_message("Você escolheu Hoenn! Quem será seu parceiro?", view=view, ephemeral=True)

class StartJourneyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # Botão persistente se necessário

    @discord.ui.button(label="Iniciar Jornada", style=discord.ButtonStyle.primary, custom_id="start_journey_button")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        supabase = get_supabase_client()
        player_id = interaction.user.id
        
        # Verifica se o jogador já existe
        result = supabase.table("players").select("discord_id").eq("discord_id", player_id).execute()
        if result.data:
            await interaction.response.send_message("Você já iniciou sua jornada!", ephemeral=True)
        else:
            await interaction.response.send_modal(TrainerNameModal())

# --- Cog Class ---

class PlayerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="start")
    async def start(self, ctx: commands.Context):
        """Inicia a jornada de um novo treinador."""
        view = StartJourneyView()
        embed = discord.Embed(
            title="Bem-vindo ao Mundo Pokémon!",
            description="Clique no botão abaixo para dar o primeiro passo na sua aventura e se tornar um Mestre Pokémon!",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed, view=view)

    @commands.command(name="addpokemon")
    @commands.is_owner() # Comando apenas para o dono do bot
    async def add_pokemon(self, ctx: commands.Context, pokemon_name: str, level: int = 5):
        """(Admin) Adiciona um pokémon ao time do jogador com posição incremental."""
        player_id = ctx.author.id
        
        # Apenas chama a função central
        result = await add_pokemon_to_player(
            player_id=player_id,
            pokemon_api_name=pokemon_name,
            level=level,
            captured_at="Comando de Admin"
        )
        
        if result['success']:
            await ctx.send(f"✅ {pokemon_name.capitalize()} foi adicionado ao seu time! {result['message']}")
        else:
            await ctx.send(f"❌ Erro: {result['error']}")

async def setup(bot):
    await bot.add_cog(PlayerCog(bot))