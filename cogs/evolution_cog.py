# evolution_cog.py

import discord
import os
from discord.ext import commands
from discord import ui
from supabase import create_client, Client
# MUDANÇA: Importamos também get_pokemon_data para buscar a lista de ataques
from utils.pokeapi_service import get_pokemon_species_data, get_pokemon_data, get_data_from_url, get_total_xp_for_level, find_evolution_details

# --- CLASSE DE UI PARA ESCOLHA DE EVOLUÇÃO (Existente) ---
class EvolutionChoiceView(ui.View):
    # ... (seu código desta classe continua aqui, sem alterações)
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

# --- NOVA CLASSE DE UI PARA SUBSTITUIÇÃO DE ATAQUES ---
class MoveReplaceView(ui.View):
    def __init__(self, pokemon_id: str, new_move: str, current_moves: list, cog):
        super().__init__(timeout=180)
        self.pokemon_id = pokemon_id
        self.new_move = new_move
        self.cog = cog

        for i, move_name in enumerate(current_moves):
            button = ui.Button(label=move_name.capitalize(), custom_id=str(i), style=discord.ButtonStyle.secondary)
            button.callback = self.replace_move_callback
            self.add_item(button)

        cancel_button = ui.Button(label=f"Não aprender {new_move.capitalize()}", custom_id="cancel", style=discord.ButtonStyle.danger)
        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)

    async def replace_move_callback(self, interaction: discord.Interaction):
        index_to_replace = int(interaction.data['custom_id'])
        await self.cog._update_pokemon_moves(self.pokemon_id, self.new_move, index_to_replace)
        await interaction.response.edit_message(
            content=f"✅ **1, 2 e... pronto!** Seu Pokémon esqueceu o ataque antigo e aprendeu **{self.new_move.capitalize()}**!",
            view=None
        )
        self.stop()

    async def cancel_callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content=f"🤔 Decisão difícil! Você optou por não aprender **{self.new_move.capitalize()}** por enquanto.",
            view=None
        )
        self.stop()


# ========= CLASSE DO COG =========
class EvolutionCog(commands.Cog):
    """Cog para gerenciar XP, level up, evolução e ataques dos Pokémon."""

    def __init__(self, bot: commands.Bot):
        # ... (seu __init__ continua igual)
        self.bot = bot
        url: str = os.environ.get("SUPABASE_URL")
        key: str = os.environ.get("SUPABASE_KEY")
        self.supabase: Client = create_client(url, key)
        print("EvolutionCog carregado e conectado ao Supabase.")

    # --- NOVA FUNÇÃO AUXILIAR PARA ATUALIZAR ATAQUES NO DB ---
    async def _update_pokemon_moves(self, pokemon_id: str, new_move: str, slot: int):
        """Atualiza a lista de ataques de um Pokémon no banco de dados."""
        try:
            # 1. Pega a lista de ataques atual
            response = self.supabase.table('player_pokemon').select('moves').eq('id', pokemon_id).single().execute()
            if not response.data: return
            
            current_moves = response.data['moves']
            
            # 2. Substitui o ataque no slot especificado
            current_moves[slot] = new_move
            
            # 3. Envia a lista atualizada de volta para o Supabase
            self.supabase.table('player_pokemon').update({'moves': current_moves}).eq('id', pokemon_id).execute()
        except Exception as e:
            print(f"Erro ao atualizar ataques no DB: {e}")

    # --- FUNÇÃO PRINCIPAL DA LÓGICA DE APRENDER ATAQUES ---
    async def check_for_new_moves(self, pokemon: dict, new_level: int, channel):
        """Verifica se um Pokémon aprende um novo ataque no nível que acabou de atingir."""
        pokemon_api_data = await get_pokemon_data(pokemon['pokemon_api_name'])
        if not pokemon_api_data: return

        learned_move_name = None
        # Itera na lista de ataques da API
        for move_info in pokemon_api_data['moves']:
            for version_details in move_info['version_group_details']:
                # Procura por um ataque que seja aprendido por 'level-up' no nível atual
                if version_details['move_learn_method']['name'] == 'level-up' and version_details['level_learned_at'] == new_level:
                    learned_move_name = move_info['move']['name']
                    break
            if learned_move_name:
                break
        
        if learned_move_name:
            # Se um ataque foi encontrado, começa a lógica para adicioná-lo
            response = self.supabase.table('player_pokemon').select('moves').eq('id', pokemon['id']).single().execute()
            if not response.data: return
            
            current_moves = response.data['moves']

            # Cenário 1: O Pokémon tem um slot de ataque vazio (null)
            if None in current_moves:
                empty_slot_index = current_moves.index(None)
                await self._update_pokemon_moves(pokemon['id'], learned_move_name, empty_slot_index)
                await channel.send(f"💡 **{pokemon['nickname']}** aprendeu um novo ataque: **{learned_move_name.capitalize()}**!")
            
            # Cenário 2: O Pokémon já sabe 4 ataques
            else:
                embed = discord.Embed(
                    title=f"❓ Substituir Ataque?",
                    description=f"**{pokemon['nickname']}** quer aprender **{learned_move_name.capitalize()}**, mas já conhece 4 ataques.\n\nEscolha um ataque para esquecer:",
                    color=discord.Color.orange()
                )
                view = MoveReplaceView(pokemon['id'], learned_move_name, current_moves, self)
                await channel.send(embed=embed, view=view)

    # --- ATUALIZAÇÃO NA FUNÇÃO check_for_level_up ---
    async def check_for_level_up(self, pokemon: dict, channel):
        """Verifica se um Pokémon tem XP suficiente para subir de nível."""
        species_data = await get_pokemon_species_data(pokemon['pokemon_api_name'])
        if not species_data: return

        growth_rate_url = species_data['growth_rate']['url']
        next_level = pokemon['current_level'] + 1
        xp_needed = await get_total_xp_for_level(growth_rate_url, next_level)

        while pokemon['current_xp'] >= xp_needed:
            new_level = pokemon['current_level'] + 1
            try:
                self.supabase.table('player_pokemon').update({'current_level': new_level}).eq('id', pokemon['id']).execute()
                await channel.send(f"✨ **{pokemon['nickname']}** subiu para o **nível {new_level}**!")
                pokemon['current_level'] = new_level
                
                # MUDANÇA: Adicionamos a verificação de novos ataques logo após subir de nível
                await self.check_for_new_moves(pokemon, new_level, channel)
                
                await self.check_evolution(pokemon, channel)
                
                xp_needed = await get_total_xp_for_level(growth_rate_url, new_level + 1)
            except Exception as e:
                print(f"Erro ao atualizar nível no DB: {e}")
                break
    
    # ... O RESTO DO SEU CÓDIGO (check_evolution, give_xp, team, etc.) CONTINUA AQUI SEM ALTERAÇÕES ...
    # (Copie o resto das suas funções para cá)
    async def evolve_pokemon(self, discord_id: int, pokemon_db_id: str, new_pokemon_api_name: str, channel):
        """Atualiza o nome do Pokémon no banco de dados para a sua nova forma."""
        try:
            response = self.supabase.table('player_pokemon').update({
                'pokemon_api_name': new_pokemon_api_name, 'nickname': new_pokemon_api_name.capitalize()
            }).eq('id', pokemon_db_id).execute()

            if response.data:
                await channel.send(f"🎉 <@{discord_id}>, seu Pokémon evoluiu para **{new_pokemon_api_name.capitalize()}**! 🎉")
        except Exception as e:
            print(f"Erro ao evoluir Pokémon: {e}")

    async def check_evolution(self, pokemon: dict, channel):
        """Verifica as condições de evolução para um Pokémon após um level up."""
        species_data = await get_pokemon_species_data(pokemon['pokemon_api_name'])
        if not species_data or not species_data.get('evolution_chain'): return

        evo_chain_url = species_data['evolution_chain']['url']
        evo_chain_data = await get_data_from_url(evo_chain_url)
        if not evo_chain_data: return

        possible_evolutions = find_evolution_details(evo_chain_data['chain'], pokemon['pokemon_api_name'])
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
        
        if trigger == 'level-up':
            min_level = evo_details.get('min_level')
            if min_level is not None and pokemon['current_level'] >= min_level:
                await self.evolve_pokemon(pokemon['player_id'], pokemon['id'], new_form, channel)
    
    @commands.command(name='givexp', help='(Admin) Dá XP para um dos seus Pokémon.')
    @commands.is_owner()
    async def give_xp(self, ctx: commands.Context, amount: int, *, pokemon_nickname: str):
        """Dá uma quantidade de XP para um Pokémon específico do jogador."""
        try:
            response = self.supabase.table('player_pokemon').select('*').eq('player_id', ctx.author.id).ilike('nickname', pokemon_nickname).execute()

            if not response.data:
                await ctx.send(f"Não encontrei nenhum Pokémon com o nome `{pokemon_nickname}`.")
                return
            if len(response.data) > 1:
                await ctx.send(f"Encontrei vários Pokémon com o nome `{pokemon_nickname}`. Por favor, use um apelido único.")
                return

            pokemon = response.data[0]
            
            new_xp = pokemon['current_xp'] + amount
            self.supabase.table('player_pokemon').update({'current_xp': new_xp}).eq('id', pokemon['id']).execute()
            
            await ctx.send(f"Você deu {amount} XP para **{pokemon['nickname']}**. XP Total agora: {new_xp}.")
            
            pokemon['current_xp'] = new_xp
            await self.check_for_level_up(pokemon, ctx.channel)
        except Exception as e:
            await ctx.send(f"Ocorreu um erro inesperado ao dar XP.")
            print(f"Erro no comando !givexp: {e}")

    @commands.command(name='team', help='Mostra todos os seus Pokémon.')
    async def team(self, ctx: commands.Context):
        """Exibe a lista de Pokémon que o jogador possui."""
        try:
            response = self.supabase.table('player_pokemon').select('*').eq('player_id', ctx.author.id).order('current_level', desc=True).execute()
            if not response.data:
                await ctx.send("Você ainda não capturou nenhum Pokémon!")
                return

            embed = discord.Embed(title=f"Equipe de {ctx.author.display_name}", color=discord.Color.teal())
            embed.set_thumbnail(url=ctx.author.avatar.url)
            for pokemon in response.data:
                field_name = f"**{pokemon['nickname']}** ({pokemon['pokemon_api_name'].capitalize()})"
                # MUDANÇA: Exibe os ataques do Pokémon no !team
                moves_list = [move.capitalize() for move in pokemon.get('moves', []) if move]
                moves_display = ', '.join(moves_list) if moves_list else 'Nenhum'
                field_value = (f"**Nível:** {pokemon['current_level']} | **XP:** {pokemon['current_xp']}\n"
                               f"**HP:** {pokemon['current_hp']}/{pokemon['max_hp']}\n"
                               f"**Ataques:** {moves_display}")
                embed.add_field(name=field_name, value=field_value, inline=False)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"Ocorreu um erro ao buscar sua equipe.")
            print(f"Erro no comando !team: {e}")

    # ... (shop e buy continuam iguais) ...
    @commands.command(name='shop', help='Mostra a loja de itens evolutivos.')
    async def shop(self, ctx: commands.Context):
        """Mostra uma loja 'hardcoded' com itens evolutivos."""
        embed = discord.Embed(title="🛒 Loja de Itens Evolutivos 🛒", color=discord.Color.blue())
        embed.description = "Use o comando `!buy \"Nome do Item\" <Nome do Pokémon>`."
        items = [
            {"name": "Fire Stone", "price": 5000}, {"name": "Water Stone", "price": 5000},
            {"name": "Thunder Stone", "price": 5000}, {"name": "Leaf Stone", "price": 5000},
        ]
        for item in items:
            embed.add_field(name=f"{item['name']} - `${item['price']:,}`", value="\u200b", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='buy', help='Compra um item evolutivo para um Pokémon.')
    async def buy(self, ctx: commands.Context, item_name: str, *, pokemon_name: str):
        """Simula a compra e o uso imediato de um item para evolução."""
        try:
            pokemon_response = self.supabase.table('player_pokemon').select('*').eq('player_id', ctx.author.id).ilike('nickname', pokemon_name.strip()).execute()

            if not pokemon_response.data:
                await ctx.send(f"Não encontrei um Pokémon chamado `{pokemon_name}` na sua equipe.")
                return
            if len(pokemon_response.data) > 1:
                await ctx.send(f"Encontrei vários Pokémon com o nome `{pokemon_name}`. Por favor, seja mais específico.")
                return

            pokemon = pokemon_response.data[0]
            
            species_data = await get_pokemon_species_data(pokemon['pokemon_api_name'])
            if not species_data or not species_data.get('evolution_chain'):
                await ctx.send(f"**{pokemon_name}** não parece poder evoluir com itens.")
                return

            evo_chain_url = species_data['evolution_chain']['url']
            evo_chain_data = await get_data_from_url(evo_chain_url)
            possible_evolutions = find_evolution_details(evo_chain_data['chain'], pokemon['pokemon_api_name'])
            
            found_match = False
            for evo in possible_evolutions:
                details = evo['evolution_details'][0]
                if details['trigger']['name'] == 'use-item' and details.get('item') and details['item']['name'] == item_name.lower().replace(' ', '-'):
                    new_form = evo['species']['name']
                    await self.evolve_pokemon(ctx.author.id, pokemon['id'], new_form, ctx.channel)
                    found_match = True
                    break
            
            if not found_match:
                await ctx.send(f"O item **{item_name}** não parece ter efeito em **{pokemon_name}**.")
        except Exception as e:
            await ctx.send(f"Ocorreu um erro inesperado no comando !buy.")
            print(f"Erro no comando !buy: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(EvolutionCog(bot))