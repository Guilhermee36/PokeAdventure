# cogs/evolution_cog.py

import discord
import os
from typing import Tuple
from discord.ext import commands
from discord import ui
from supabase import create_client, Client
import asyncio # Importado para o helper de contexto

# Importa os utilitários corretos
import utils.pokeapi_service as pokeapi
import utils.evolution_utils as evolution_utils

# --- CLASSES DE UI (MoveReplaceView) ---
# (O código MoveReplaceView permanece o mesmo...)
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
        await interaction.response.edit_message(content=f"✅ **1, 2 e... pronto!** Seu Pokémon esqueceu o ataque antigo e aprendeu **{self.new_move.capitalize()}**!", view=None)
        self.stop()
    async def cancel_callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content=f"🤔 Decisão difícil! Você optou por não aprender **{self.new_move.capitalize()}** por enquanto.", view=None)
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
        try:
            response = self.supabase.table('player_pokemon').select('moves').eq('id', pokemon_id).single().execute()
            if not response.data: return
            current_moves = response.data['moves']
            current_moves[slot] = new_move
            self.supabase.table('player_pokemon').update({'moves': current_moves}).eq('id', pokemon_id).execute()
        except Exception as e:
            print(f"Erro ao atualizar ataques no DB: {e}")

    # =================================================================
    # <<< ✅ FUNÇÕES DE MOVIMENTO REATORADAS (DIVIDIDAS EM 2) ✅ >>>
    # =================================================================

    async def _get_new_moves_for_level(self, pokemon_api_name: str, new_level: int) -> list:
        """(Helper) Apenas busca na API os novos movimentos para um nível, sem atualizar o DB."""
        pokemon_api_data = await pokeapi.get_pokemon_data(pokemon_api_name)
        if not pokemon_api_data: 
            return []

        newly_learned_moves = []
        for move_info in pokemon_api_data['moves']:
            move_name = move_info['move']['name']
            for version_details in move_info['version_group_details']:
                if (version_details['move_learn_method']['name'] == 'level-up' and
                    version_details['level_learned_at'] == new_level and
                    move_name not in newly_learned_moves):
                    
                    newly_learned_moves.append(move_name)
                    break 
        return newly_learned_moves

    async def learn_moves_silently(self, pokemon_id: str, nickname: str, new_moves: list, channel) -> Tuple[list, list]:
        """
        (Etapa 1) Tenta aprender novos movimentos se houver slots vazios (None).
        Não bloqueia. Retorna os movimentos que precisam de substituição.
        """
        try:
            response = self.supabase.table('player_pokemon').select('moves').eq('id', pokemon_id).single().execute()
            if not response.data: 
                return new_moves # Retorna todos como 'não aprendidos'
            
            current_moves = response.data['moves']
            moves_that_need_replacement = []

            for move_name in new_moves:
                if move_name in current_moves:
                    continue # Já conhece

                if None in current_moves:
                    empty_slot_index = current_moves.index(None)
                    # Atualiza o DB
                    await self._update_pokemon_moves(pokemon_id, move_name, empty_slot_index)
                    # Atualiza a lista local para o próximo loop
                    current_moves[empty_slot_index] = move_name
                    await channel.send(f"💡 **{nickname}** aprendeu um novo ataque: **{move_name.capitalize()}**!")
                else:
                    # Não há espaço, adiciona à lista de pendentes
                    moves_that_need_replacement.append(move_name)

            return moves_that_need_replacement, current_moves
        except Exception as e:
            print(f"Erro ao aprender movimentos silenciosamente: {e}")
            return new_moves, []

    async def prompt_for_move_replacement(self, pokemon_id: str, nickname: str, moves_to_learn: list, current_moves: list, channel):
        """
        (Etapa 2) Agora sim, bloqueia o jogador para cada movimento que não coube.
        """
        if not moves_to_learn:
            return # Nada a fazer

        # Garante que 'current_moves' esteja atualizado se não foi pego na Etapa 1
        if not current_moves:
             response = self.supabase.table('player_pokemon').select('moves').eq('id', pokemon_id).single().execute()
             if not response.data: return
             current_moves = response.data['moves']

        for move_name in moves_to_learn:
            embed = discord.Embed(
                title="❓ Substituir Ataque?",
                description=f"**{nickname}** quer aprender **{move_name.capitalize()}**, mas já conhece 4 ataques.\n\nEscolha um ataque para esquecer:",
                color=discord.Color.orange()
            )
            # Precisamos buscar os movimentos atualizados do DB *a cada loop*
            # pois o 'current_moves' local pode estar desatualizado após a primeira substituição
            db_response = self.supabase.table('player_pokemon').select('moves').eq('id', pokemon_id).single().execute()
            if not db_response.data: continue
            updated_moves = db_response.data['moves']

            view = MoveReplaceView(pokemon_id, move_name, updated_moves, self)
            msg = await channel.send(embed=embed, view=view)
            await view.wait() # Este é o bloqueio (await)
            try:
                await msg.edit(view=None) # Limpa os botões após a interação
            except discord.NotFound:
                pass

    # =VÉIA FUNÇÃO check_for_new_moves (Não usada mais no level up) V=
    # (Pode ser mantida para uso futuro, mas a lógica de level up usará as novas funções)

    # =================================================================
    # <<< ✅ FUNÇÃO _get_game_context CORRIGIDA (LÊ O DB) ✅ >>>
    # =================================================================
    async def _get_game_context(self, player_id: int, pokemon_to_exclude_id: str) -> dict:
        """
        (CORRIGIDO)
        Busca dados complexos do jogo (tipos da party, localização, hora)
        para passar ao verificador de evolução.
        """
        party_types = set()
        location_name = None
        time_of_day = "day" # Padrão
        
        try:
            # 1. Busca localização E HORA do jogador
            # Isso lê a coluna 'game_time_of_day' da tabela 'players'
            player_res = self.supabase.table('players').select('current_location_name, game_time_of_day').eq('discord_id', player_id).single().execute()
            
            if player_res.data:
                location_name = player_res.data.get('current_location_name')
                time_of_day = player_res.data.get('game_time_of_day', 'day') # Usa o dado do DB

            # 2. Busca o restante da party
            party_res = self.supabase.table('player_pokemon') \
                .select('pokemon_api_name') \
                .eq('player_id', player_id) \
                .neq('id', pokemon_to_exclude_id) \
                .execute()

            # 3. Coleta os tipos
            if party_res.data:
                api_tasks = [pokeapi.get_pokemon_data(pkmn['pokemon_api_name']) for pkmn in party_res.data]
                results = await asyncio.gather(*api_tasks)
                for api_data in results:
                    if api_data and 'types' in api_data:
                        for type_info in api_data['types']:
                            party_types.add(type_info['type']['name'])
        except Exception as e:
            print(f"Erro ao montar contexto de evolução: {e}")
            
        return {
            "time_of_day": time_of_day, # ✅ Agora contém "day" ou "night" do DB
            "party_types": list(party_types),
            "current_location_name": location_name
        }


    # =================================================================
    # <<< ✅ FUNÇÃO check_for_level_up CORRIGIDA (ORDEM NOVA) ✅ >>>
    # =================================================================
    async def check_for_level_up(self, pokemon: dict, channel):
        """Verifica se um Pokémon tem XP suficiente para subir de nível e atualiza stats."""
        species_data = await pokeapi.get_pokemon_species_data(pokemon['pokemon_api_name'])
        if not species_data: return

        growth_rate_url = species_data['growth_rate']['url']
        next_level = pokemon['current_level'] + 1
        xp_needed = await pokeapi.get_total_xp_for_level(growth_rate_url, next_level)
        if xp_needed == float('inf'):
             return 

        while pokemon['current_xp'] >= xp_needed:
            new_level = pokemon['current_level'] + 1
            try:
                # 1. ATUALIZA NÍVEL E STATS NO DB
                pokemon_api_data = await pokeapi.get_pokemon_data(pokemon['pokemon_api_name'])
                if not pokemon_api_data: break
                recalculated_stats = pokeapi.calculate_stats_for_level(pokemon_api_data['stats'], new_level)
                update_payload = {'current_level': new_level, **recalculated_stats}
                if 'max_hp' in recalculated_stats:
                    update_payload['current_hp'] = recalculated_stats['max_hp']

                response = self.supabase.table('player_pokemon').update(update_payload).eq('id', pokemon['id']).execute()
                if not response.data: break 
                
                await channel.send(f"✨ **{pokemon['nickname']}** subiu para o **nível {new_level}**! Seus stats aumentaram!")
                
                # Atualiza o dict local para o próximo loop
                pokemon['current_level'] = new_level
                pokemon.update(recalculated_stats)
                
                # 2. BUSCA NOVOS MOVIMENTOS (API)
                # (Ex: Piloswine aprende "ancient-power")
                new_moves_list = await self._get_new_moves_for_level(pokemon['pokemon_api_name'], new_level)
                
                # 3. APRENDE MOVIMENTOS (NÃO-BLOQUEANTE)
                # (Salva "ancient-power" no DB se houver espaço)
                moves_that_need_replacement, current_moves = await self.learn_moves_silently(
                    pokemon['id'], pokemon['nickname'], new_moves_list, channel
                )

                # 4. CHECA EVOLUÇÃO (AGORA!)
                # (O DB é re-buscado DENTRO de check_evolution,
                # então ele verá a felicidade e o "ancient-power")
                game_context = await self._get_game_context(pokemon['player_id'], pokemon['id'])
                evo_result = await evolution_utils.check_evolution(
                    supabase=self.supabase,
                    pokemon_db_id=pokemon['id'],
                    trigger_event="level_up",
                    context=game_context
                )
                
                did_evolve = False
                if evo_result:
                    await self.evolve_pokemon(pokemon['player_id'], pokemon['id'], evo_result['new_name'], channel)
                    pokemon['pokemon_api_name'] = evo_result['new_name'] # Atualiza nome local
                    did_evolve = True
                
                # 5. LIDAR COM SUBSTITUIÇÃO (BLOQUEANTE)
                # (Só roda se não evoluiu, ou depois de evoluir)
                # (Se evoluiu, 'pokemon' tem o novo nome, ex: Mamoswine)
                if did_evolve:
                    # Se evoluiu (ex: Mamoswine), verifica se a NOVA forma aprende
                    # movimentos neste nível e lida com substituições.
                    new_form_moves = await self._get_new_moves_for_level(pokemon['pokemon_api_name'], new_level)
                    # (Assume que a nova forma tem espaço para os moves)
                    moves_to_replace_new, current_moves_new = await self.learn_moves_silently(
                         pokemon['id'], pokemon['nickname'], new_form_moves, channel
                    )
                    await self.prompt_for_move_replacement(
                         pokemon['id'], pokemon['nickname'], moves_to_replace_new, current_moves_new, channel
                    )
                else:
                    # Se não evoluiu, apenas lida com os movimentos pendentes
                    await self.prompt_for_move_replacement(
                        pokemon['id'], pokemon['nickname'], moves_that_need_replacement, current_moves, channel
                    )

                # Se evoluiu, para o loop de level-up
                if did_evolve:
                    break 
                # ====================================================

                # Se não evoluiu, pega a XP para o próximo loop
                xp_needed = await pokeapi.get_total_xp_for_level(growth_rate_url, new_level + 1)
                if xp_needed == float('inf'):
                    break 

            except Exception as e:
                print(f"Erro ao atualizar nível e stats no DB: {e}")
                break

    # ... (O restante do arquivo: evolve_pokemon, give_xp, give_happiness, setup) ...
    # (permanece o mesmo)
    async def evolve_pokemon(self, discord_id: int, pokemon_db_id: str, new_pokemon_api_name: str, channel):
        try:
            response = self.supabase.table('player_pokemon').select('current_level, nickname, pokemon_api_name').eq('id', pokemon_db_id).single().execute()
            if not response.data: return
            level = response.data['current_level']
            old_name = response.data['pokemon_api_name']
            nickname = response.data['nickname']
            await channel.send(f"O que? **{nickname}** está evoluindo!")
            new_pokemon_api_data = await pokeapi.get_pokemon_data(new_pokemon_api_name)
            if not new_pokemon_api_data: return
            new_api_id = new_pokemon_api_data['id'] 
            recalculated_stats = pokeapi.calculate_stats_for_level(new_pokemon_api_data['stats'], level)
            update_payload = {
                'pokemon_api_name': new_pokemon_api_name,
                'pokemon_pokedex_id': new_api_id,
                **recalculated_stats
            }
            if 'max_hp' in recalculated_stats:
                update_payload['current_hp'] = recalculated_stats['max_hp']
            if nickname.lower() == old_name.lower():
                update_payload['nickname'] = new_pokemon_api_name.capitalize()
            self.supabase.table('player_pokemon').update(update_payload).eq('id', pokemon_db_id).execute()
            await channel.send(f"🎉 <@{discord_id}>, seu **{nickname}** evoluiu para **{new_pokemon_api_name.capitalize()}**! 🎉")
        except Exception as e:
            print(f"Erro ao evoluir Pokémon: {e}")
            await channel.send(f"Ocorreu um erro crítico durante a evolução.")
    
    @commands.command(name='givexp', help='(Admin) Dá XP para um dos seus Pokémon.')
    @commands.is_owner()
    async def give_xp(self, ctx: commands.Context, amount: int, *, pokemon_nickname: str):
        try:
            response = self.supabase.table('player_pokemon').select('*').eq('player_id', ctx.author.id).ilike('nickname', pokemon_nickname.strip()).execute()
            if not response.data:
                await ctx.send(f"Não encontrei nenhum Pokémon com o nome `{pokemon_nickname}`.")
                return
            if len(response.data) > 1:
                await ctx.send(f"Você tem mais de um Pokémon com o nome `{pokemon_nickname}`. Use o apelido único.")
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

    @commands.command(name='givehappiness', help='(Admin) Dá felicidade para um dos seus Pokémon.')
    @commands.is_owner()
    async def give_happiness(self, ctx: commands.Context, amount: int, *, pokemon_nickname: str):
        try:
            response = self.supabase.table('player_pokemon').select('id, nickname, happiness').eq('player_id', ctx.author.id).ilike('nickname', pokemon_nickname.strip()).execute()
            if not response.data:
                await ctx.send(f"Não encontrei nenhum Pokémon com o nome `{pokemon_nickname}`.")
                return
            if len(response.data) > 1:
                await ctx.send(f"Você tem mais de um Pokémon com o nome `{pokemon_nickname}`. Use o apelido único.")
                return
            pokemon = response.data[0]
            current_happiness = pokemon.get('happiness', 70)
            new_happiness = current_happiness + amount
            new_happiness = max(0, min(255, new_happiness)) 
            self.supabase.table('player_pokemon').update({'happiness': new_happiness}).eq('id', pokemon['id']).execute()
            await ctx.send(f"Você alterou a felicidade de **{pokemon['nickname']}** em {amount}. Felicidade Total agora: **{new_happiness}/255**.")
        except Exception as e:
            await ctx.send(f"Ocorreu um erro inesperado ao dar felicidade.")
            print(f"Erro no comando !givehappiness: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(EvolutionCog(bot))