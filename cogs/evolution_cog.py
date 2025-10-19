# evolution_cog.py

import discord
import os
from discord.ext import commands
from discord import ui
from supabase import create_client, Client
import pokeapi_service # Importamos nosso serviço

# (A classe EvolutionChoiceView continua a mesma)
class EvolutionChoiceView(ui.View):
    def __init__(self, pokemon_id: str, evolutions: list, evolution_cog):
        super().__init__(timeout=300)
        self.pokemon_id = pokemon_id
        self.evolution_cog = evolution_cog
        for evo in evolutions:
            evo_name = evo['species']['name']
            button = ui.Button(label=evo_name.capitalize(), custom_id=evo_name, style=discord.ButtonStyle.primary)
            button.callback = self.button_callback
            self.add_item(button)
    async def button_callback(self, interaction: discord.Interaction):
        chosen_evolution = interaction.data['custom_id']
        await interaction.response.defer()
        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(view=self)
        await self.evolution_cog.evolve_pokemon(
            interaction.user.id, self.pokemon_id, chosen_evolution, interaction.channel
        )
        self.stop()

# ========= CLASSE DO COG =========

class EvolutionCog(commands.Cog):
    """Cog para gerenciar XP, level up, evolução e comandos de teste dos Pokémon."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        url: str = os.environ.get("SUPABASE_URL")
        key: str = os.environ.get("SUPABASE_KEY")
        self.supabase: Client = create_client(url, key)
        print("EvolutionCog carregado e conectado ao Supabase.")

    # --- (As funções de lógica interna como call_openai, evolve_pokemon, etc., continuam as mesmas) ---
    # ... (código das funções internas omitido por brevidade, ele não muda) ...
    async def evolve_pokemon(self, discord_id: int, pokemon_db_id: str, new_pokemon_api_name: str, channel):
        """Atualiza o nome do Pokémon no banco de dados para a sua nova forma."""
        try:
            response = self.supabase.table('player_pokemon').update({
                'pokemon_api_name': new_pokemon_api_name, 'nickname': new_pokemon_api_name.capitalize() # Atualiza o apelido também
            }).eq('id', pokemon_db_id).execute()

            if response.data:
                await channel.send(f"🎉 <@{discord_id}>, seu Pokémon evoluiu para **{new_pokemon_api_name.capitalize()}**! 🎉")
        except Exception as e:
            print(f"Erro ao evoluir Pokémon: {e}")

    async def check_for_level_up(self, pokemon: dict, channel):
        """Verifica se um Pokémon tem XP suficiente para subir de nível."""
        species_data = await pokeapi_service.get_pokemon_species_data(pokemon['pokemon_api_name'])
        if not species_data: return

        growth_rate_url = species_data['growth_rate']['url']
        next_level = pokemon['current_level'] + 1
        xp_needed = await pokeapi_service.get_total_xp_for_level(growth_rate_url, next_level)

        if pokemon['current_xp'] >= xp_needed:
            new_level = pokemon['current_level'] + 1
            try:
                self.supabase.table('player_pokemon').update({'current_level': new_level}).eq('id', pokemon['id']).execute()
                await channel.send(f"✨ **{pokemon['nickname']}** subiu para o **nível {new_level}**!")
                pokemon['current_level'] = new_level
                await self.check_evolution(pokemon, channel)
            except Exception as e:
                print(f"Erro ao atualizar nível no DB: {e}")

    async def check_evolution(self, pokemon: dict, channel):
        """Verifica as condições de evolução para um Pokémon após um level up."""
        species_data = await pokeapi_service.get_pokemon_species_data(pokemon['pokemon_api_name'])
        if not species_data or not species_data.get('evolution_chain'): return

        evo_chain_url = species_data['evolution_chain']['url']
        evo_chain_data = await pokeapi_service.get_data_from_url(evo_chain_url)
        if not evo_chain_data: return

        possible_evolutions = pokeapi_service.find_evolution_details(evo_chain_data['chain'], pokemon['pokemon_api_name'])
        if not possible_evolutions: return

        if len(possible_evolutions) > 1:
            embed = discord.Embed(
                title=f"Decisão para {pokemon['nickname']}!",
                description="Seu Pokémon está pronto para seguir um novo caminho. Escolha com sabedoria!",
                color=discord.Color.gold()
            )
            view = EvolutionChoiceView(pokemon['id'], possible_evolutions, self)
            await channel.send(embed=embed, view=view)
            return

        next_evo = possible_evolutions[0]
        evo_details = next_evo['evolution_details'][0]
        trigger = evo_details['trigger']['name']
        new_form = next_evo['species']['name']
        
        if trigger == 'level-up' and pokemon['current_level'] >= evo_details['min_level']:
            await self.evolve_pokemon(pokemon['player_id'], pokemon['id'], new_form, channel)
    # --- COMANDOS DE TESTE (CHEATS) ---

    @commands.command(name='addpokemon', help='(Admin) Adiciona um novo Pokémon para você.')
    @commands.is_owner()
    async def add_pokemon(self, ctx: commands.Context, api_name: str, level: int, *, nickname: str = None):
        """
        Adiciona um Pokémon diretamente à sua coleção para fins de teste.
        Ex: !addpokemon pikachu 25 Meu Trovão
        """
        if not nickname:
            nickname = api_name.capitalize()
        
        # O HP inicial deveria ser calculado com base nos stats da API, mas para um cheat, um valor fixo é suficiente.
        INITIAL_HP = 100 

        pokemon_data = {
            'player_id': ctx.author.id,
            'pokemon_api_name': api_name.lower(),
            'nickname': nickname,
            'current_level': level,
            'current_hp': INITIAL_HP,
            'current_xp': 0 # Começa com 0 XP no nível atual
        }

        try:
            response = self.supabase.table('player_pokemon').insert(pokemon_data).execute()
            new_pokemon = response.data[0]

            embed = discord.Embed(title="🌟 Pokémon Adicionado com Sucesso! 🌟", color=discord.Color.green())
            embed.add_field(name="Nome", value=new_pokemon['pokemon_api_name'].capitalize(), inline=True)
            embed.add_field(name="Apelido", value=new_pokemon['nickname'], inline=True)
            embed.add_field(name="Nível", value=new_pokemon['current_level'], inline=True)
            embed.add_field(name="HP", value=new_pokemon['current_hp'], inline=True)
            embed.add_field(name="XP", value=new_pokemon['current_xp'], inline=True)
            embed.set_footer(text=f"ID Único: {new_pokemon['id']}")
            
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"❌ Ocorreu um erro ao adicionar o Pokémon: {e}")

    @commands.command(name='givexp', help='(Admin) Dá XP para um dos seus Pokémon.')
    @commands.is_owner()
    async def give_xp(self, ctx: commands.Context, pokemon_nickname: str, amount: int):
        """Dá uma quantidade de XP para um Pokémon específico do jogador."""
        try:
            response = self.supabase.table('player_pokemon').select('*').eq('player_id', ctx.author.id).ilike('nickname', pokemon_nickname).single().execute()
            pokemon = response.data
            
            new_xp = pokemon['current_xp'] + amount
            self.supabase.table('player_pokemon').update({'current_xp': new_xp}).eq('id', pokemon['id']).execute()
            
            await ctx.send(f"Você deu {amount} XP para **{pokemon['nickname']}**. XP Total agora: {new_xp}.")
            
            pokemon['current_xp'] = new_xp
            await self.check_for_level_up(pokemon, ctx.channel)
        except Exception as e:
            await ctx.send(f"Ocorreu um erro. Verifique se o nome está correto e se você tem apenas um Pokémon com esse apelido. Detalhe: {e}")

    # --- COMANDOS DO JOGADOR ---

    @commands.command(name='shop', help='Mostra a loja de itens evolutivos.')
    async def shop(self, ctx: commands.Context):
        """
        Mostra uma loja 'hardcoded'. Os itens não vêm do banco de dados.
        Esta é uma abordagem simples e eficaz para um conjunto fixo de itens como pedras evolutivas.
        """
        embed = discord.Embed(title="🛒 Loja de Itens Evolutivos 🛒", color=discord.Color.blue())
        embed.description = "Aqui você pode comprar pedras para evoluir seus Pokémon instantaneamente!\nUse o comando `!buy \"Nome do Item\" <Nome do Pokémon>`."
        
        items = [
            {"name": "Fire Stone", "price": 5000},
            {"name": "Water Stone", "price": 5000},
            {"name": "Thunder Stone", "price": 5000},
            {"name": "Leaf Stone", "price": 5000},
        ]

        for item in items:
            embed.add_field(name=f"{item['name']} - `${item['price']}`", value="\u200b", inline=False)

        await ctx.send(embed=embed)

    @commands.command(name='buy', help='Compra um item evolutivo para um Pokémon.')
    async def buy(self, ctx: commands.Context, item_name: str, pokemon_name: str):
        """
        Simula a compra e o uso imediato de um item.
        A lógica não verifica o dinheiro do jogador nem um inventário, ela apenas checa
        se o item mencionado é o correto para evoluir o Pokémon alvo, segundo a PokéAPI.
        """
        try:
            pokemon_response = self.supabase.table('player_pokemon').select('*').eq('player_id', ctx.author.id).ilike('nickname', pokemon_name).single().execute()
            pokemon = pokemon_response.data

            species_data = await pokeapi_service.get_pokemon_species_data(pokemon['pokemon_api_name'])
            evo_chain_url = species_data['evolution_chain']['url']
            evo_chain_data = await pokeapi_service.get_data_from_url(evo_chain_url)
            possible_evolutions = pokeapi_service.find_evolution_details(evo_chain_data['chain'], pokemon['pokemon_api_name'])

            found_match = False
            for evo in possible_evolutions:
                details = evo['evolution_details'][0]
                # Compara o item do !buy com o item necessário na API
                if details['trigger']['name'] == 'use-item' and details['item']['name'] == item_name.lower().replace(' ', '-'):
                    new_form = evo['species']['name']
                    # Se for válido, evolui. Uma versão futura poderia checar o dinheiro do jogador aqui.
                    await self.evolve_pokemon(ctx.author.id, pokemon['id'], new_form, ctx.channel)
                    found_match = True
                    break
            
            if not found_match:
                await ctx.send(f"O item **{item_name}** não parece ter efeito em **{pokemon_name}**.")
        except Exception:
            await ctx.send(f"Não encontrei um Pokémon chamado '{pokemon_name}' na sua equipe.")

async def setup(bot: commands.Bot):
    await bot.add_cog(EvolutionCog(bot))