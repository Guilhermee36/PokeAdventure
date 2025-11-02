# cogs/evolution_cog.py

import discord
import os
from discord.ext import commands
from discord import ui
from supabase import create_client, Client
import asyncio # Importado para o helper de contexto

# Importa os utilitários corretos
import utils.pokeapi_service as pokeapi
import utils.evolution_utils as evolution_utils # NOVO

# --- CLASSES DE UI (MoveReplaceView) ---
# (A View EvolutionChoiceView foi removida daqui, pois a lógica de level-up
# agora é tratada inteiramente pelo evolution_utils, que retorna apenas UMA
# evolução válida por vez, se houver).

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
        # (Esta função contém as correções da sua versão original e está mantida)
        pokemon_api_data = await pokeapi.get_pokemon_data(pokemon['pokemon_api_name'])
        if not pokemon_api_data: return

        newly_learned_moves = []
        for move_info in pokemon_api_data['moves']:
            move_name = move_info['move']['name']
            for version_details in move_info['version_group_details']:
                if (version_details['move_learn_method']['name'] == 'level-up' and
                    version_details['level_learned_at'] == new_level and
                    move_name not in newly_learned_moves):
                    
                    newly_learned_moves.append(move_name)
                    break 
        
        if not newly_learned_moves:
            return

        for move_name in newly_learned_moves:
            try:
                response = self.supabase.table('player_pokemon').select('moves').eq('id', pokemon['id']).single().execute()
                if not response.data: continue
                current_moves = response.data['moves']
            except Exception as e:
                print(f"Erro ao buscar moves atualizados em check_for_new_moves: {e}")
                continue 

            if move_name in current_moves:
                continue

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
                msg = await channel.send(embed=embed, view=view)
                await view.wait()
                try:
                    await msg.edit(view=None) # Limpa os botões após a interação
                except discord.NotFound:
                    pass # Mensagem pode ter sido deletada

    async def _get_game_context(self, player_id: int, pokemon_to_exclude_id: str) -> dict:
        """
        Busca dados complexos do jogo (tipos da party, localização, hora)
        para passar ao verificador de evolução.
        """
        party_types = set()
        location_name = None
        time_of_day = "day" # TODO: Implementar um sistema de hora do jogo
        
        try:
            # 1. Busca localização do jogador
            player_res = self.supabase.table('players').select('current_location_name').eq('discord_id', player_id).single().execute()
            if player_res.data:
                location_name = player_res.data.get('current_location_name')

            # 2. Busca o restante da party
            party_res = self.supabase.table('player_pokemon') \
                .select('pokemon_api_name') \
                .eq('player_id', player_id) \
                .neq('id', pokemon_to_exclude_id) \
                .execute()

            # 3. Coleta os tipos (isso pode ser lento, mas o cache do pokeapi ajuda)
            if party_res.data:
                api_tasks = []
                for pkmn in party_res.data:
                    api_tasks.append(pokeapi.get_pokemon_data(pkmn['pokemon_api_name']))
                
                results = await asyncio.gather(*api_tasks)
                
                for api_data in results:
                    if api_data and 'types' in api_data:
                        for type_info in api_data['types']:
                            party_types.add(type_info['type']['name'])

        except Exception as e:
            print(f"Erro ao montar contexto de evolução: {e}")
            
        return {
            "time_of_day": time_of_day,
            "party_types": list(party_types),
            "current_location_name": location_name
        }


    async def check_for_level_up(self, pokemon: dict, channel):
        """Verifica se um Pokémon tem XP suficiente para subir de nível e atualiza stats."""
        species_data = await pokeapi.get_pokemon_species_data(pokemon['pokemon_api_name'])
        if not species_data: return

        growth_rate_url = species_data['growth_rate']['url']
        next_level = pokemon['current_level'] + 1
        xp_needed = await pokeapi.get_total_xp_for_level(growth_rate_url, next_level)
        if xp_needed == float('inf'): # Já está no nível máximo
             return 

        while pokemon['current_xp'] >= xp_needed:
            new_level = pokemon['current_level'] + 1
            try:
                pokemon_api_data = await pokeapi.get_pokemon_data(pokemon['pokemon_api_name'])
                if not pokemon_api_data: break

                recalculated_stats = pokeapi.calculate_stats_for_level(pokemon_api_data['stats'], new_level)
                
                update_payload = {
                    'current_level': new_level,
                    **recalculated_stats
                }
                if 'max_hp' in recalculated_stats:
                    update_payload['current_hp'] = recalculated_stats['max_hp']

                # Atualiza o DB ANTES de enviar a mensagem
                response = self.supabase.table('player_pokemon').update(update_payload).eq('id', pokemon['id']).execute()
                if not response.data:
                    break # Falha ao atualizar, interrompe o loop
                
                await channel.send(f"✨ **{pokemon['nickname']}** subiu para o **nível {new_level}**! Seus stats aumentaram!")
                
                # Atualiza o dict local para o próximo loop
                pokemon['current_level'] = new_level
                pokemon.update(recalculated_stats)
                
                await self.check_for_new_moves(pokemon, new_level, channel)
                
                # ========================================================
                # <<< LÓGICA DE EVOLUÇÃO REFATORADA >>>
                # ========================================================
                
                # 1. Monta o contexto complexo
                game_context = await self._get_game_context(pokemon['player_id'], pokemon['id'])
                
                # 2. Chama o "Cérebro" Central
                evo_result = await evolution_utils.check_evolution(
                    supabase=self.supabase,
                    pokemon_db_id=pokemon['id'],
                    trigger_event="level_up",
                    context=game_context
                )
                
                if evo_result:
                    # 3. Aplica a evolução
                    await self.evolve_pokemon(pokemon['player_id'], pokemon['id'], evo_result['new_name'], channel)
                    
                    # 4. Interrompe o loop de level-up
                    # A nova forma pode ter uma taxa de crescimento de XP diferente.
                    # O check_for_level_up será chamado novamente na próxima vez que ganhar XP.
                    break 
                # ========================================================
                # <<< FIM DA REFATORAÇÃO >>>
                # ========================================================

                # Busca o XP para o *próximo* nível
                xp_needed = await pokeapi.get_total_xp_for_level(growth_rate_url, new_level + 1)
                if xp_needed == float('inf'):
                    break # Atingiu o nível máximo

            except Exception as e:
                print(f"Erro ao atualizar nível e stats no DB: {e}")
                break

    # =================================================================
    # FUNÇÃO CENTRALIZADA PARA *APLICAR* A EVOLUÇÃO
    # =================================================================
    async def evolve_pokemon(self, discord_id: int, pokemon_db_id: str, new_pokemon_api_name: str, channel):
        """
        Atualiza os dados de um Pokémon no DB após evoluir.
        Esta é a função central usada por todos os cogs.
        """
        try:
            # 1. Pega o nível e apelido atuais
            response = self.supabase.table('player_pokemon').select('current_level, nickname, pokemon_api_name').eq('id', pokemon_db_id).single().execute()
            if not response.data: return
            
            level = response.data['current_level']
            old_name = response.data['pokemon_api_name']
            nickname = response.data['nickname']
            
            await channel.send(f"O que? **{nickname}** está evoluindo!")

            # 2. Pega os dados da API da nova forma
            new_pokemon_api_data = await pokeapi.get_pokemon_data(new_pokemon_api_name)
            if not new_pokemon_api_data: return
            
            new_api_id = new_pokemon_api_data['id'] # Pega o ID da Pokédex

            # 3. Recalcula os stats para a nova forma no mesmo nível
            recalculated_stats = pokeapi.calculate_stats_for_level(new_pokemon_api_data['stats'], level)

            # 4. Monta o payload (resetando o HP e atualizando stats)
            update_payload = {
                'pokemon_api_name': new_pokemon_api_name,
                'pokemon_pokedex_id': new_api_id,
                **recalculated_stats
            }
            if 'max_hp' in recalculated_stats:
                update_payload['current_hp'] = recalculated_stats['max_hp']
            
            # 5. Se o apelido era o nome antigo, atualiza o apelido
            if nickname.lower() == old_name.lower():
                update_payload['nickname'] = new_pokemon_api_name.capitalize()

            # 6. Atualiza o DB
            self.supabase.table('player_pokemon').update(update_payload).eq('id', pokemon_db_id).execute()

            await channel.send(f"🎉 <@{discord_id}>, seu **{nickname}** evoluiu para **{new_pokemon_api_name.capitalize()}**! 🎉")
        except Exception as e:
            print(f"Erro ao evoluir Pokémon: {e}")
            await channel.send(f"Ocorreu um erro crítico durante a evolução.")
    
    # =================================================================
    # <<< A FUNÇÃO check_evolution() FOI REMOVIDA DESTE ARQUIVO >>>
    # =================================================================
    
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
            
            # Passa o dict atualizado para o checker
            pokemon['current_xp'] = new_xp
            await self.check_for_level_up(pokemon, ctx.channel)
        except Exception as e:
            await ctx.send(f"Ocorreu um erro inesperado ao dar XP.")
            print(f"Erro no comando !givexp: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(EvolutionCog(bot))