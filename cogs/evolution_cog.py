# cogs/evolution_cog.py

import discord
import os
from discord.ext import commands
from discord import ui
from supabase import create_client, Client
# MUDANÇA: Importamos get_pokemon_data para buscar stats base e a lista de ataques ao subir de nível
from utils.pokeapi_service import get_pokemon_species_data, get_pokemon_data, get_data_from_url, get_total_xp_for_level, find_evolution_details, calculate_stats_for_level

# --- CLASSES DE UI ---

class EvolutionChoiceView(ui.View):
    """View para o jogador escolher uma evolução quando há múltiplas opções."""
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

class MoveReplaceView(ui.View):
    """View para o jogador substituir um ataque quando a lista de 4 ataques está cheia."""
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
    """Cog para gerenciar XP, level up, stats, evolução e ataques dos Pokémon."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        url: str = os.environ.get("SUPABASE_URL")
        key: str = os.environ.get("SUPABASE_KEY")
        self.supabase: Client = create_client(url, key)
        print("EvolutionCog carregado e conectado ao Supabase.")

    # --- FUNÇÕES DE LÓGICA INTERNA ---

    async def _update_pokemon_moves(self, pokemon_id: str, new_move: str, slot: int):
        """Função auxiliar para atualizar a lista de ataques de um Pokémon no DB."""
        try:
            response = self.supabase.table('player_pokemon').select('moves').eq('id', pokemon_id).single().execute()
            if not response.data: return
            
            current_moves = response.data['moves']
            current_moves[slot] = new_move
            
            self.supabase.table('player_pokemon').update({'moves': current_moves}).eq('id', pokemon_id).execute()
        except Exception as e:
            print(f"Erro ao atualizar ataques no DB: {e}")

    async def check_for_new_moves(self, pokemon: dict, new_level: int, channel):
        """Verifica e processa TODOS os novos ataques que um Pokémon aprende em um nível."""
        pokemon_api_data = await get_pokemon_data(pokemon['pokemon_api_name'])
        if not pokemon_api_data: return

        newly_learned_moves = []
        for move_info in pokemon_api_data['moves']:
            move_name = move_info['move']['name'] # Pegamos o nome aqui
            for version_details in move_info['version_group_details']:
                # CONDIÇÃO DE CORREÇÃO 1:
                # Verificamos se o método é level-up, se o nível bate
                # E (o mais importante) se o ataque JÁ NÃO ESTÁ na nossa lista
                if (version_details['move_learn_method']['name'] == 'level-up' and
                    version_details['level_learned_at'] == new_level and
                    move_name not in newly_learned_moves): # <-- Impede duplicatas
                    
                    newly_learned_moves.append(move_name)
                    break # Otimização: Já encontramos esse ataque, não precisa checar outras versões
        
        if not newly_learned_moves:
            return

        # CORREÇÃO 2:
        # Removemos a busca de 'moves' daqui de fora...

        for move_name in newly_learned_moves:
            # ...e colocamos ELA AQUI DENTRO.
            # Isso garante que a CADA novo ataque que tentamos aprender,
            # pegamos a lista mais ATUALIZADA do banco de dados.
            try:
                response = self.supabase.table('player_pokemon').select('moves').eq('id', pokemon['id']).single().execute()
                if not response.data: continue
                current_moves = response.data['moves']
            except Exception as e:
                print(f"Erro ao buscar moves atualizados em check_for_new_moves: {e}")
                continue # Pula este ataque se não conseguir verificar

            # Esta verificação agora usa a lista 'current_moves' fresca
            if move_name in current_moves:
                continue

            # Removemos a busca duplicada que existia aqui (linha 120 antiga)

            if None in current_moves:
                empty_slot_index = current_moves.index(None)
                await self._update_pokemon_moves(pokemon['id'], move_name, empty_slot_index)
                await channel.send(f"💡 **{pokemon['nickname']}** aprendeu um novo ataque: **{move_name.capitalize()}**!")
            else:
                embed = discord.Embed(
                    title="❓ Substituir Ataque?",
                    description=f"**{pokemon['nickname']}** quer aprender **{move_name.capitalize()}**, mas já conhece 4 ataques.\n\nEscolha um ataque para esquecer:",
                    color=discord.Color.orange()
                )
                view = MoveReplaceView(pokemon['id'], move_name, current_moves, self)
                await channel.send(embed=embed, view=view)
                await view.wait() # O loop vai pausar aqui e, ao continuar, vai buscar a lista de moves nova na próxima iteração.

    async def check_for_level_up(self, pokemon: dict, channel):
        """Verifica se um Pokémon tem XP suficiente para subir de nível e atualiza stats."""
        species_data = await get_pokemon_species_data(pokemon['pokemon_api_name'])
        if not species_data: return

        growth_rate_url = species_data['growth_rate']['url']
        next_level = pokemon['current_level'] + 1
        xp_needed = await get_total_xp_for_level(growth_rate_url, next_level)

        while pokemon['current_xp'] >= xp_needed:
            new_level = pokemon['current_level'] + 1
            try:
                pokemon_api_data = await get_pokemon_data(pokemon['pokemon_api_name'])
                if not pokemon_api_data: break

                recalculated_stats = calculate_stats_for_level(pokemon_api_data['stats'], new_level)
                
                update_payload = {
                    'current_level': new_level,
                    **recalculated_stats
                }

                # CORREÇÃO: Atualiza o current_hp para o novo max_hp, restaurando a vida.
                if 'max_hp' in recalculated_stats:
                    update_payload['current_hp'] = recalculated_stats['max_hp']

                self.supabase.table('player_pokemon').update(update_payload).eq('id', pokemon['id']).execute()
                
                await channel.send(f"✨ **{pokemon['nickname']}** subiu para o **nível {new_level}**! Seus stats aumentaram!")
                
                pokemon['current_level'] = new_level
                
                await self.check_for_new_moves(pokemon, new_level, channel)
                await self.check_evolution(pokemon, channel)
                
                xp_needed = await get_total_xp_for_level(growth_rate_url, new_level + 1)
            except Exception as e:
                print(f"Erro ao atualizar nível e stats no DB: {e}")
                break

    async def evolve_pokemon(self, discord_id: int, pokemon_db_id: str, new_pokemon_api_name: str, channel):
        """Atualiza os dados de um Pokémon no DB após evoluir."""
        # Esta função agora é chamada pelo ShopCog, por isso é importante
        try:
            # Pega o nível atual para recalcular os stats da nova forma
            response = self.supabase.table('player_pokemon').select('current_level').eq('id', pokemon_db_id).single().execute()
            if not response.data: return
            
            level = response.data['current_level']

            # Pega os dados da API da nova forma evoluída
            new_pokemon_api_data = await get_pokemon_data(new_pokemon_api_name)
            if not new_pokemon_api_data: return

            # Recalcula os stats para a nova forma no mesmo nível
            recalculated_stats = calculate_stats_for_level(new_pokemon_api_data['stats'], level)

            update_payload = {
                'pokemon_api_name': new_pokemon_api_name,
                'nickname': new_pokemon_api_name.capitalize(),
                **recalculated_stats
            }
            if 'max_hp' in recalculated_stats:
                update_payload['current_hp'] = recalculated_stats['max_hp']

            self.supabase.table('player_pokemon').update(update_payload).eq('id', pokemon_db_id).execute()

            await channel.send(f"🎉 <@{discord_id}>, seu Pokémon evoluiu para **{new_pokemon_api_name.capitalize()}**! 🎉")
        except Exception as e:
            print(f"Erro ao evoluir Pokémon: {e}")

    async def check_evolution(self, pokemon: dict, channel):
        """Verifica as condições de evolução para um Pokémon."""
        species_data = await get_pokemon_species_data(pokemon['pokemon_api_name'])
        if not species_data or not species_data.get('evolution_chain'): return

        evo_chain_url = species_data['evolution_chain']['url']
        evo_chain_data = await get_data_from_url(evo_chain_url)
        if not evo_chain_data: return

        possible_evolutions = find_evolution_details(evo_chain_data['chain'], pokemon['pokemon_api_name'])
        if not possible_evolutions: return

        # Filtra evoluções por item (agora tratadas no !buy)
        valid_evolutions = []
        for evo in possible_evolutions:
            trigger = evo['evolution_details'][0]['trigger']['name']
            if trigger != 'use-item':
                valid_evolutions.append(evo)
        
        if not valid_evolutions:
            return # Nenhuma evolução válida (ex: Eevee só evolui por item)

        if len(valid_evolutions) > 1:
            view = EvolutionChoiceView(pokemon['id'], valid_evolutions, self)
            await channel.send(f"Seu **{pokemon['nickname']}** está pronto para evoluir! Escolha seu caminho:", view=view)
            return

        next_evo = valid_evolutions[0]
        evo_details = next_evo['evolution_details'][0]
        trigger = evo_details['trigger']['name']
        
        if trigger == 'level-up':
            min_level = evo_details.get('min_level')
            if min_level is not None and pokemon['current_level'] >= min_level:
                new_form = next_evo['species']['name']
                await self.evolve_pokemon(pokemon['player_id'], pokemon['id'], new_form, channel)
    
    # --- COMANDOS DO JOGADOR ---

    @commands.command(name='givexp', help='(Admin) Dá XP para um dos seus Pokémon.')
    @commands.is_owner()
    async def give_xp(self, ctx: commands.Context, amount: int, *, pokemon_nickname: str):
        """Dá uma quantidade de XP para um Pokémon específico do jogador."""
        try:
            response = self.supabase.table('player_pokemon').select('*').eq('player_id', ctx.author.id).ilike('nickname', pokemon_nickname).single().execute()

            if not response.data:
                await ctx.send(f"Não encontrei nenhum Pokémon com o nome `{pokemon_nickname}`.")
                return

            pokemon = response.data
            
            new_xp = pokemon['current_xp'] + amount
            self.supabase.table('player_pokemon').update({'current_xp': new_xp}).eq('id', pokemon['id']).execute()
            
            await ctx.send(f"Você deu {amount} XP para **{pokemon['nickname']}**. XP Total agora: {new_xp}.")
            
            pokemon['current_xp'] = new_xp
            await self.check_for_level_up(pokemon, ctx.channel)
        except Exception as e:
            await ctx.send(f"Ocorreu um erro inesperado ao dar XP.")
            print(f"Erro no comando !givexp: {e}")

    # <<< !!! COMANDOS !SHOP E !BUY REMOVIDOS DESTE ARQUIVO !!! >>>
    # A funcionalidade agora existe em cogs/shop_cog.py

async def setup(bot: commands.Bot):
    await bot.add_cog(EvolutionCog(bot))