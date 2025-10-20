import discord
from discord.ext import commands
from discord import app_commands
import random
import aiohttp
from supabase import create_client, Client
import os

# --- Helper Functions (Sem alterações) ---

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

# --- Core Pokémon Logic (Sem alterações) ---

async def add_pokemon_to_player(player_id: int, pokemon_api_name: str, level: int = 5, captured_at: str = "Início da Jornada") -> dict:
    """
    Função centralizada para adicionar um Pokémon a um jogador.
    Verifica o limite do time, calcula a próxima posição e insere no DB.
    Retorna um dicionário com 'success' e 'message' ou 'error'.
    """
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
    
    base_hp = poke_data['stats'][0]['base_stat']
    current_hp = int((2 * base_hp * level) / 100) + level + 10

    is_shiny = random.randint(1, 100) == 1
    party_position = pokemon_count + 1

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

# =================================================================
# ALTERAÇÃO 1: Dicionário de starters expandido para 9 gerações
# =================================================================
class StarterSelectView(discord.ui.View):
    def __init__(self, region: str):
        super().__init__(timeout=180)
        self.region = region
        starters = {
            "Kanto": ["bulbasaur", "charmander", "squirtle"],
            "Johto": ["chikorita", "cyndaquil", "totodile"],
            "Hoenn": ["treecko", "torchic", "mudkip"],
            "Sinnoh": ["turtwig", "chimchar", "piplup"],
            "Unova": ["snivy", "tepig", "oshawott"],
            "Kalos": ["chespin", "fennekin", "froakie"],
            "Alola": ["rowlet", "litten", "popplio"],
            "Galar": ["grookey", "scorbunny", "sobble"],
            "Paldea": ["sprigatito", "fuecoco", "quaxly"]
        }
        
        for starter in starters.get(region, []):
            button = discord.ui.Button(label=starter.capitalize(), style=discord.ButtonStyle.primary, custom_id=starter)
            button.callback = self.select_starter
            self.add_item(button)

    async def select_starter(self, interaction: discord.Interaction):
        starter_name = interaction.data['custom_id']
        await interaction.response.defer(ephemeral=True) 

        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(view=self)

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
            poke_data = await fetch_pokemon_data(starter_name)
            if poke_data:
                sprite_url = poke_data['sprites']['front_default']
                if is_shiny:
                    sprite_url = poke_data['sprites']['front_shiny']
                embed.set_thumbnail(url=sprite_url)

            await interaction.followup.send(embed=embed, ephemeral=False)
        else:
            await interaction.followup.send(f"Ocorreu um erro: {result['error']}", ephemeral=True)

# =================================================================
# ALTERAÇÃO 2: RegionSelectView agora usa um menu dropdown (Select)
# =================================================================
class RegionSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.select(
        placeholder="Escolha sua região inicial...",
        options=[
            discord.SelectOption(label="Kanto", description="Geração 1 - Bulbasaur, Charmander, Squirtle"),
            discord.SelectOption(label="Johto", description="Geração 2 - Chikorita, Cyndaquil, Totodile"),
            discord.SelectOption(label="Hoenn", description="Geração 3 - Treecko, Torchic, Mudkip"),
            discord.SelectOption(label="Sinnoh", description="Geração 4 - Turtwig, Chimchar, Piplup"),
            discord.SelectOption(label="Unova", description="Geração 5 - Snivy, Tepig, Oshawott"),
            discord.SelectOption(label="Kalos", description="Geração 6 - Chespin, Fennekin, Froakie"),
            discord.SelectOption(label="Alola", description="Geração 7 - Rowlet, Litten, Popplio"),
            discord.SelectOption(label="Galar", description="Geração 8 - Grookey, Scorbunny, Sobble"),
            discord.SelectOption(label="Paldea", description="Geração 9 - Sprigatito, Fuecoco, Quaxly"),
        ]
    )
    async def select_region_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        selected_region = select.values[0]

        # Desativa o menu para evitar que o usuário clique de novo
        select.disabled = True
        await interaction.message.edit(view=self)
        
        # Envia a próxima View com os starters da região escolhida
        view = StarterSelectView(region=selected_region)
        await interaction.response.send_message(f"Você escolheu **{selected_region}**! Agora, escolha seu parceiro de jornada:", view=view, ephemeral=True)


class StartJourneyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Iniciar Jornada", style=discord.ButtonStyle.primary, custom_id="start_journey_button")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        supabase = get_supabase_client()
        player_id = interaction.user.id
        
        result = supabase.table("players").select("discord_id").eq("discord_id", player_id).execute()
        if result.data:
            await interaction.response.send_message("Você já iniciou sua jornada!", ephemeral=True)
        else:
            await interaction.response.send_modal(TrainerNameModal())


# --- Cog Class (Sem alterações) ---

class PlayerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="start")
    async def start(self, ctx: commands.Context):
        view = StartJourneyView()
        embed = discord.Embed(
            title="Bem-vindo ao Mundo Pokémon!",
            description="Clique no botão abaixo para dar o primeiro passo na sua aventura e se tornar um Mestre Pokémon!",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed, view=view)

    @commands.command(name="help")
    async def help_command(self, ctx: commands.Context):
        embed = discord.Embed(
            title="Guia de Comandos - PokeAdventure",
            description="Aqui estão os comandos que você pode usar:",
            color=discord.Color.orange()
        )
        embed.add_field(name="`!start`", value="Inicia sua jornada como um novo treinador Pokémon.", inline=False)
        embed.add_field(name="`!team`", value="Mostra seu time atual de Pokémon (em breve com nova UI!).", inline=False)
        embed.add_field(name="`!help`", value="Exibe esta mensagem de ajuda.", inline=False)
        
        if await self.bot.is_owner(ctx.author):
            embed.add_field(
                name="--- Comandos de Administrador ---",
                value="Apenas o dono do bot pode usar estes comandos.",
                inline=False
            )
            embed.add_field(name="`!addpokemon <nome> [level]`", value="Adiciona um Pokémon ao seu time.", inline=False)
            embed.add_field(name="`!delete <@membro>`", value="APAGA TODOS os dados de um jogador para testes.", inline=False)

        await ctx.send(embed=embed)

    @commands.command(name="addpokemon")
    @commands.is_owner()
    async def add_pokemon(self, ctx: commands.Context, pokemon_name: str, level: int = 5):
        result = await add_pokemon_to_player(
            player_id=ctx.author.id,
            pokemon_api_name=pokemon_name,
            level=level,
            captured_at="Comando de Admin"
        )
        
        if result['success']:
            await ctx.send(f"✅ {pokemon_name.capitalize()} foi adicionado ao seu time! {result['message']}")
        else:
            await ctx.send(f"❌ Erro: {result['error']}")

    @commands.command(name="delete")
    @commands.is_owner()
    async def delete_player_data(self, ctx: commands.Context, member: discord.Member):
        supabase = get_supabase_client()
        player_id = member.id

        await ctx.send(f"⚠️ **Atenção!** Você está prestes a deletar **TODOS** os dados de `{member.display_name}`. Isso é irreversível.\nProcessando...")

        try:
            delete_response = supabase.table("players").delete().eq("discord_id", player_id).execute()

            if delete_response.data:
                await ctx.send(f"✅ Dados do jogador `{member.display_name}` foram apagados com sucesso.")
            else:
                await ctx.send(f"🔎 O jogador `{member.display_name}` não foi encontrado no banco de dados.")

        except Exception as e:
            await ctx.send(f"❌ Ocorreu um erro ao tentar deletar os dados: {e}")


async def setup(bot):
    await bot.add_cog(PlayerCog(bot))