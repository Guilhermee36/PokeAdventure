# cogs/team_cog.py
import discord
import os
from discord.ext import commands
from discord import ui
from supabase import create_client, Client
from io import BytesIO

# Importa nossos novos helpers
import utils.pokeapi_service as pokeapi
import utils.image_generator as img_gen

class TeamCog(commands.Cog):
    """Cog para gerenciar o time do jogador e exibir a nova imagem."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        url: str = os.environ.get("SUPABASE_URL")
        key: str = os.environ.get("SUPABASE_KEY")
        self.supabase: Client = create_client(url, key)
        print("TeamCog carregado.")

    @commands.command(name='team', help='Mostra seu time Pokémon. Use !team [1-6] para focar.')
    async def team(self, ctx: commands.Context, focused_slot: int = 1):
        """
        Exibe o time do jogador.
        Por padrão, foca no Pokémon da posição 1.
        Use !team 2 para focar no Pokémon da posição 2, e assim por diante.
        """
        if not 1 <= focused_slot <= 6:
            await ctx.send("Posição inválida. Escolha um número de 1 a 6.")
            return

        player_id = ctx.author.id
        msg = await ctx.send(f"Buscando seu time... 🔍")

        try:
            # 1. Buscar time no Supabase
            # !!! IMPORTANTE: Estou assumindo que sua tabela 'player_pokemon'
            # tem uma coluna chamada 'team_position' (com números de 1 a 6).
            response = self.supabase.table('player_pokemon').select('*') \
                .eq('player_id', player_id) \
                .not_.is_('team_position', 'null') \
                .order('team_position', desc=False).execute() # Ordena por 1, 2, 3...

            if not response.data:
                await msg.edit(content="Você ainda não tem um time! Capture um Pokémon.")
                return

            team_pokemon_db = response.data
            
            # 2. Separar o focado dos demais
            focused_db_data = next((p for p in team_pokemon_db if p['team_position'] == focused_slot), None)
            
            # Se o slot focado estiver vazio (ex: !team 6 mas só tem 3 pokémon),
            # apenas pega o primeiro do time como foco.
            if not focused_db_data:
                focused_db_data = team_pokemon_db[0]
                focused_slot = focused_db_data['team_position'] # Atualiza o slot real

            other_team_db = [p for p in team_pokemon_db if p['team_position'] != focused_slot]

            # 3. Buscar dados da PokeAPI (em paralelo)
            await msg.edit(content="Carregando dados da Pokédex... 📖")
            
            # Focado (precisamos de dados completos)
            f_api_data = await pokeapi.get_pokemon_data(focused_db_data['pokemon_api_name'])
            f_species_data = await pokeapi.get_pokemon_species_data(focused_db_data['pokemon_api_name'])
            
            if not f_api_data or not f_species_data:
                 await msg.edit(content="Erro ao buscar dados do Pokémon principal.")
                 return
            
            focused_pokemon = {
                'db_data': focused_db_data,
                'api_data': f_api_data,
                'species_data': f_species_data
            }
            
            # Outros (só precisamos do sprite)
            other_team_list = []
            for other_db in other_team_db:
                o_api_data = await pokeapi.get_pokemon_data(other_db['pokemon_api_name'])
                if o_api_data:
                    other_team_list.append({
                        'db_data': other_db,
                        'api_data': o_api_data
                    })

            # 4. Gerar a Imagem
            await msg.edit(content="Desenhando seu time... 🎨")
            image_buffer = await img_gen.create_team_image(focused_pokemon, other_team_list)
            
            if not image_buffer:
                await msg.edit(content="Erro ao gerar a imagem do time.")
                return

            # 5. Enviar a Imagem
            file = discord.File(image_buffer, filename=f"{ctx.author.name}_team.png")
            embed = discord.Embed(
                title=f"Time de {ctx.author.display_name}",
                description=f"Mostrando detalhes de **{focused_db_data['nickname'].capitalize()}** (Slot {focused_slot}).\nUse `!team [1-6]` para focar em outro.",
                color=discord.Color.blue()
            )
            embed.set_image(url=f"attachment://{file.filename}")
            
            await msg.delete() # Deleta a mensagem de "carregando"
            await ctx.send(embed=embed, file=file)

        except Exception as e:
            print(f"Erro no comando !team: {e}")
            await msg.edit(content=f"Ocorreu um erro inesperado. O admin foi notificado.")


async def setup(bot: commands.Bot):
    await bot.add_cog(TeamCog(bot))