# cogs/team_cog.py

import discord
from discord.ext import commands
from discord import ui
import os
import aiohttp
from supabase import create_client, Client

# --- Funções Auxiliares (Copiadas de outros cogs para modularidade) ---

def get_supabase_client():
    """Cria e retorna um cliente Supabase."""
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY")
    return create_client(url, key)

async def fetch_pokemon_data(pokemon_name: str):
    """Busca dados de um Pokémon da PokeAPI."""
    url = f"https://pokeapi.co/api/v2/pokemon/{pokemon_name.lower()}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.json()
            return None

# --- Classes de UI (A nova View paginada) ---

class TeamView(ui.View):
    """
    Uma View paginada para exibir os Pokémon da equipe de um jogador.
    Mostra um Pokémon por página.
    """
    
    def __init__(self, author_id: int, pokemon_list: list, supabase_client: Client):
        super().__init__(timeout=120.0) # Timeout de 2 minutos
        self.author_id = author_id
        self.pokemon_list = pokemon_list
        self.supabase = supabase_client
        self.current_index = 0
        self.message: discord.Message = None # Armazena a mensagem para editar no timeout
        
        # Atualiza o estado dos botões (desativa o 'anterior' no início)
        self.update_buttons()

    async def generate_embed(self) -> discord.Embed:
        """Cria o Embed para o Pokémon atual."""
        
        # Pega o Pokémon da lista com base no índice atual
        pokemon = self.pokemon_list[self.current_index]
        
        # Busca dados da API para pegar o sprite
        api_data = await fetch_pokemon_data(pokemon['pokemon_api_name'])
        
        # Define o sprite (shiny ou padrão)
        is_shiny = pokemon.get('is_shiny', False)
        sprite_url = None
        if api_data and api_data['sprites']:
            sprite_url = api_data['sprites']['front_shiny'] if is_shiny else api_data['sprites']['front_default']

        # Formata o apelido e o nome
        nickname = pokemon['nickname']
        species = pokemon['pokemon_api_name'].capitalize()
        
        title = f"✨ {nickname} ✨ (Shiny)" if is_shiny else f"{nickname}"
        if nickname.lower() != species.lower():
            title += f" ({species})" # Ex: "Sparky (Pikachu)"

        embed = discord.Embed(title=title, color=discord.Color.blue())
        
        if sprite_url:
            embed.set_thumbnail(url=sprite_url)

        # Adiciona Stats (Exemplo com os stats que temos certeza que existem no DB)
        embed.add_field(name="Nível", value=str(pokemon['current_level']), inline=True)
        embed.add_field(name="HP", value=f"{pokemon.get('current_hp', 0)} / {pokemon.get('max_hp', 0)}", inline=True)
        embed.add_field(name="XP", value=f"{pokemon['current_xp']}", inline=True)
        
        # Adiciona Posição
        embed.add_field(name="Posição no Time", value=f"Slot {pokemon.get('party_position', 'N/A')}", inline=False)

        # Formata a lista de ataques
        moves_list = [move.capitalize() for move in pokemon.get('moves', []) if move]
        moves_display = ', '.join(moves_list) if moves_list else 'Nenhum ataque aprendido.'
        embed.add_field(name="Ataques", value=moves_display, inline=False)
        
        embed.set_footer(text=f"Pokémon {self.current_index + 1} / {len(self.pokemon_list)}")
        
        return embed

    def update_buttons(self):
        """Ativa/Desativa botões de navegação."""
        # Botão 'Anterior'
        self.children[0].disabled = self.current_index == 0
        # Botão 'Próximo'
        self.children[1].disabled = self.current_index == (len(self.pokemon_list) - 1)

    @ui.button(label="⬅️ Anterior", style=discord.ButtonStyle.secondary, custom_id="prev")
    async def previous_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Este não é o seu time!", ephemeral=True)
            return
            
        self.current_index -= 1
        self.update_buttons()
        
        new_embed = await self.generate_embed()
        await interaction.response.edit_message(embed=new_embed, view=self)

    @ui.button(label="Próximo ➡️", style=discord.ButtonStyle.secondary, custom_id="next")
    async def next_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Este não é o seu time!", ephemeral=True)
            return
            
        self.current_index += 1
        self.update_buttons()
        
        new_embed = await self.generate_embed()
        await interaction.response.edit_message(embed=new_embed, view=self)

    async def on_timeout(self):
        """Desativa os botões quando a View expira."""
        for item in self.children:
            item.disabled = True
        
        # Edita a mensagem original se ela ainda existir
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.NotFound:
                pass # A mensagem pode ter sido excluída

# --- Cog Class ---

class TeamCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.supabase: Client = get_supabase_client()

    @commands.command(name='team', help='Mostra sua equipe de Pokémon em uma interface paginada.')
    async def team(self, ctx: commands.Context):
        """Exibe a lista de Pokémon que o jogador possui, paginada."""
        try:
            # Busca os Pokémon ordenados pela posição no time
            response = self.supabase.table('player_pokemon').select('*') \
                .eq('player_id', ctx.author.id) \
                .order('party_position', desc=False) \
                .execute()

            if not response.data:
                await ctx.send("Você ainda não capturou nenhum Pokémon! Use `!start` para começar.")
                return

            # Cria a View
            view = TeamView(author_id=ctx.author.id, pokemon_list=response.data, supabase_client=self.supabase)
            
            # Gera o primeiro embed (página 1)
            initial_embed = await view.generate_embed()
            
            # Envia a mensagem e armazena a referência
            msg = await ctx.send(embed=initial_embed, view=view)
            view.message = msg

        except Exception as e:
            await ctx.send(f"Ocorreu um erro ao buscar sua equipe.")
            print(f"Erro no comando !team (TeamCog): {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(TeamCog(bot))