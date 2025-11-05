# cogs/move_relearner_cog.py

import discord
from discord.ext import commands
from discord import ui
import os
import aiohttp
from supabase import create_client, Client

# --- Funções Auxiliares (Copiadas para modularidade) ---

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

# --- Classes de UI ---

class MoveReplaceView(ui.View):
    """
    (Copiado do evolution_cog.py)
    View para o jogador substituir um ataque quando a lista de 4 ataques está cheia.
    """
    def __init__(self, pokemon_id: str, new_move: str, current_moves: list, cog):
        super().__init__(timeout=180)
        self.pokemon_id = pokemon_id
        self.new_move = new_move
        self.cog = cog # Espera uma instância do cog que tenha a função _update_pokemon_moves
        self.interaction_user_id = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Verifica se o usuário que interagiu é o autor."""
        if self.interaction_user_id is None:
            self.interaction_user_id = interaction.user.id
        
        if interaction.user.id != self.interaction_user_id:
            await interaction.response.send_message("Você não pode tomar essa decisão.", ephemeral=True)
            return False
        return True

    def create_buttons(self, current_moves: list):
        """Cria os botões de substituição e o de cancelamento."""
        for i, move_name in enumerate(current_moves):
            button = ui.Button(label=move_name.capitalize(), custom_id=str(i), style=discord.ButtonStyle.secondary)
            button.callback = self.replace_move_callback
            self.add_item(button)

        cancel_button = ui.Button(label=f"Não aprender {self.new_move.capitalize()}", custom_id="cancel", style=discord.ButtonStyle.danger, row=2)
        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)

    async def replace_move_callback(self, interaction: discord.Interaction):
        index_to_replace = int(interaction.data['custom_id'])
        
        # Chama a função _update_pokemon_moves do cog pai
        await self.cog._update_pokemon_moves(self.pokemon_id, self.new_move, index_to_replace)
        
        await interaction.response.edit_message(
            content=f"✅ **1, 2 e... pronto!** Seu Pokémon esqueceu o ataque antigo e aprendeu **{self.new_move.capitalize()}**!",
            view=None
        )
        self.stop()

    async def cancel_callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content=f"🤔 Decisão difícil! Você optou por não aprender **{self.new_move.capitalize()}** por enquanto. (A Heart Scale foi consumida pelo serviço.)",
            view=None
        )
        self.stop()

class MoveRelearnerSelectView(ui.View):
    """View para o jogador escolher qual ataque reaprender."""
    def __init__(self, author_id: int, pokemon: dict, all_moves: list, cog):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.pokemon = pokemon
        self.cog = cog # Instância do MoveRelearnerCog
        self.message = None

        options = []
        current_moves_set = set(m for m in pokemon['moves'] if m)
        
        # Filtra movimentos que o Pokémon já conhece
        for move_name in all_moves:
            if move_name not in current_moves_set:
                options.append(discord.SelectOption(label=move_name.capitalize(), value=move_name))

        if not options:
            # Caso não haja movimentos novos para aprender
             self.add_item(ui.Button(label="Este Pokémon não tem outros golpes para reaprender.", disabled=True))
             return

        # Limita a 25 opções (limite do Discord)
        select_options = options[:25]
        
        move_select = ui.Select(
            placeholder="Escolha um ataque para reaprender...",
            options=select_options
        )
        move_select.callback = self.select_callback
        self.add_item(move_select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Você não pode fazer essa escolha.", ephemeral=True)
            return False
        return True

    # --- LÓGICA DE CONSUMO MOVIDA PARA CÁ ---
    async def select_callback(self, interaction: discord.Interaction):
        """Chamado quando o jogador seleciona o ataque que quer reaprender."""
        new_move = interaction.data['values'][0]
        
        # Desativa o select
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(content=f"Você escolheu **{new_move.capitalize()}**. Verificando e consumindo 1x Heart Scale...", view=self)
        
        # --- ALTERADO: Tenta consumir o item AGORA ---
        consumed = await self.cog.check_and_consume_heart_scale(self.author_id)
        
        if not consumed:
            # Se a escama "sumiu" da bolsa (ex: vendida em outra sessão)
            await interaction.edit_original_response(
                content="❌ Ops! Parece que você não tem mais a Heart Scale na sua bolsa. Ação cancelada.",
                view=None
            )
            self.stop()
            return
        # --- FIM DA ALTERAÇÃO ---

        # Se o item foi consumido com sucesso, chama a lógica principal
        await self.cog.process_move_learning(interaction, self.pokemon, new_move)
        self.stop()

    async def on_timeout(self):
        if self.message:
            for item in self.children: item.disabled = True
            try:
                # --- ALTERADO: Mensagem de timeout (item não foi consumido) ---
                await self.message.edit(content="A sessão do Move Relearner expirou. (Nenhum item foi gasto).", view=self)
            except discord.NotFound:
                pass


class TeamSelectView(ui.View):
    """View para o jogador escolher qual Pokémon usará o Move Relearner."""
    def __init__(self, author_id: int, team: list, cog):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.cog = cog # Instância do MoveRelearnerCog
        self.message = None

        options = []
        for pokemon in team:
            label = f"{pokemon['nickname']} (Lvl {pokemon['current_level']})"
            options.append(discord.SelectOption(label=label, value=str(pokemon['id']))) # Usa o ID do DB como valor

        team_select = ui.Select(
            placeholder="Escolha um Pokémon...",
            options=options
        )
        team_select.callback = self.select_callback
        self.add_item(team_select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Você não pode escolher por outro jogador.", ephemeral=True)
            return False
        return True

    async def select_callback(self, interaction: discord.Interaction):
        """Chamado quando o jogador seleciona o Pokémon."""
        pokemon_db_id = interaction.data['values'][0]
        
        # Desativa o select
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(content="Buscando lista de movimentos...", view=self)
        
        # Chama a lógica principal do cog
        await self.cog.show_move_list(interaction, pokemon_db_id)
        self.stop()

    async def on_timeout(self):
        if self.message:
            for item in self.children: item.disabled = True
            try:
                # --- ALTERADO: Mensagem de timeout (item não foi consumido) ---
                await self.message.edit(content="A sessão do Move Relearner expirou. (Nenhum item foi gasto).", view=self)
            except discord.NotFound:
                pass

# --- Cog Class ---

class MoveRelearnerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.supabase: Client = get_supabase_client()
        self.heart_scale_id = None # Cache do ID da Heart Scale

    async def get_heart_scale_id(self) -> int | None:
        """Busca e armazena em cache o ID do item 'Heart Scale'."""
        if self.heart_scale_id:
            return self.heart_scale_id
        
        try:
            res = self.supabase.table('items').select('id').ilike('name', 'Heart Scale').single().execute()
            if res.data:
                self.heart_scale_id = res.data['id']
                return self.heart_scale_id
            return None
        except Exception as e:
            print(f"Erro ao buscar ID da Heart Scale: {e}")
            return None

    # --- NOVO: Função que APENAS CHECA, sem consumir ---
    async def _check_has_heart_scale(self, player_id: int) -> bool:
        """Verifica se o jogador tem uma Heart Scale, SEM a consumir."""
        item_id = await self.get_heart_scale_id()
        if not item_id:
            print("Erro Crítico: ID da Heart Scale não encontrado no DB.")
            return False
            
        try:
            # 1. Verificar se tem o item
            res = self.supabase.table('player_inventory') \
                .select('quantity') \
                .eq('player_id', player_id) \
                .eq('item_id', item_id) \
                .single().execute()
            
            if not res.data or res.data['quantity'] <= 0:
                return False # Não tem o item
            
            return True # Tem o item!
        except Exception as e:
            print(f"Erro ao checar Heart Scale: {e}")
            return False

    async def check_and_consume_heart_scale(self, player_id: int) -> bool:
        """Verifica se o jogador tem uma Heart Scale e a consome."""
        item_id = await self.get_heart_scale_id()
        if not item_id:
            print("Erro Crítico: ID da Heart Scale não encontrado no DB.")
            return False
            
        try:
            # 1. Verificar se tem o item
            res = self.supabase.table('player_inventory') \
                .select('quantity') \
                .eq('player_id', player_id) \
                .eq('item_id', item_id) \
                .single().execute()
            
            if not res.data or res.data['quantity'] <= 0:
                return False # Não tem o item

            new_quantity = res.data['quantity'] - 1
            
            # 2. Consumir o item
            if new_quantity == 0:
                # Deleta o registro se acabou
                self.supabase.table('player_inventory') \
                    .delete() \
                    .eq('player_id', player_id) \
                    .eq('item_id', item_id) \
                    .execute()
            else:
                # Apenas atualiza a quantidade
                self.supabase.table('player_inventory') \
                    .update({'quantity': new_quantity}) \
                    .eq('player_id', player_id) \
                    .eq('item_id', item_id) \
                    .execute()
            
            return True # Consumido com sucesso
        except Exception as e:
            print(f"Erro ao consumir Heart Scale: {e}")
            return False

    async def _update_pokemon_moves(self, pokemon_id: str, new_move: str, slot: int):
        """(Copiado do evolution_cog.py) Atualiza a lista de ataques no DB."""
        try:
            response = self.supabase.table('player_pokemon').select('moves').eq('id', pokemon_id).single().execute()
            if not response.data: return
            
            current_moves = response.data['moves']
            current_moves[slot] = new_move
            
            self.supabase.table('player_pokemon').update({'moves': current_moves}).eq('id', pokemon_id).execute()
        except Exception as e:
            print(f"Erro ao atualizar ataques no DB (MoveRelearner): {e}")

    async def get_all_learnable_moves(self, pokemon_api_name: str) -> list:
        """Busca na PokeAPI todos os movimentos que um Pokémon aprende por 'level-up'."""
        api_data = await fetch_pokemon_data(pokemon_api_name)
        if not api_data:
            return []
            
        learnable_moves = set()
        for move_info in api_data['moves']:
            for version_details in move_info['version_group_details']:
                if version_details['move_learn_method']['name'] == 'level-up':
                    learnable_moves.add(move_info['move']['name'])
                    break # Só precisa checar uma vez por movimento
        
        # Ordena alfabeticamente
        return sorted(list(learnable_moves))

    # --- Lógica do Comando !relearn (dividida em etapas) ---

    @commands.command(name='relearn', help='Usa uma Heart Scale para reaprender um golpe.')
    async def relearn(self, ctx: commands.Context):
        """Inicia o processo de reaprendizagem de movimentos."""
        
        # --- ALTERADO: Apenas checa o item, NÃO consome ---
        # 1. Verifica se o jogador tem o item
        has_item = await self._check_has_heart_scale(ctx.author.id)
        if not has_item:
            await ctx.send(f"Você precisa de uma **Heart Scale** para usar este serviço. Você pode comprá-la na `!shop`.")
            return
        
        # 2. Busca o time do jogador
        try:
            team_res = self.supabase.table('player_pokemon') \
                .select('id, nickname, current_level') \
                .eq('player_id', ctx.author.id) \
                .order('party_position') \
                .execute()
            
            if not team_res.data:
                await ctx.send("Você não tem Pokémon para ensinar.")
                # --- ALTERADO: Não precisa devolver o item, pois não foi pego ---
                return

            # 3. Mostra a View para escolher o Pokémon
            view = TeamSelectView(ctx.author.id, team_res.data, self)
            # --- ALTERADO: Mensagem não diz mais que o item foi entregue ---
            msg = await ctx.send("Qual Pokémon deve reaprender um movimento? (Requer 1x Heart Scale)", view=view)
            view.message = msg

        except Exception as e:
            await ctx.send(f"Ocorreu um erro ao buscar seu time: {e}")
            # --- ALTERADO: Não precisa devolver o item ---


    async def show_move_list(self, interaction: discord.Interaction, pokemon_db_id: str):
        """Etapa 2: O Pokémon foi escolhido, agora mostra os movimentos."""
        try:
            # Busca o Pokémon completo
            pkmn_res = self.supabase.table('player_pokemon').select('*').eq('id', pokemon_db_id).single().execute()
            if not pkmn_res.data:
                await interaction.edit_original_response(content="Erro: Pokémon não encontrado.", view=None)
                return
            
            pokemon = pkmn_res.data
            
            # Busca todos os movimentos de level-up da API
            all_moves = await self.get_all_learnable_moves(pokemon['pokemon_api_name'])
            
            if not all_moves:
                await interaction.edit_original_response(content=f"{pokemon['nickname']} não tem movimentos de level-up para reaprender.", view=None)
                return

            # Mostra a View para escolher o movimento
            view = MoveRelearnerSelectView(interaction.user.id, pokemon, all_moves, self)
            msg = await interaction.edit_original_response(content=f"Escolha um movimento para **{pokemon['nickname']}** reaprender:", view=view)
            view.message = msg

        except Exception as e:
            await interaction.edit_original_response(content=f"Ocorreu um erro ao buscar os movimentos: {e}", view=None)

    async def process_move_learning(self, interaction: discord.Interaction, pokemon: dict, new_move: str):
        """
        Etapa 3: O movimento foi escolhido, tenta aprendê-lo.
        (Esta função agora só é chamada APÓS o item ser consumido)
        """
        
        current_moves = pokemon['moves']
        
        # Verifica se há um slot vazio (None)
        if None in current_moves:
            empty_slot_index = current_moves.index(None)
            await self._update_pokemon_moves(pokemon['id'], new_move, empty_slot_index)
            # --- ALTERADO: Edita a resposta original da INTERAÇÃO ---
            await interaction.edit_original_response(
                content=f"💡 **{pokemon['nickname']}** reaprendeu **{new_move.capitalize()}**!",
                view=None
            )
        else:
            # Se os 4 slots estão cheios, mostra a View de substituição
            view = MoveReplaceView(pokemon['id'], new_move, current_moves, self)
            view.create_buttons(current_moves) # Passa os movimentos para criar os botões
            
            embed = discord.Embed(
                title="❓ Substituir Ataque?",
                description=f"**{pokemon['nickname']}** quer aprender **{new_move.capitalize()}**, mas já conhece 4 ataques.\n\nEscolha um ataque para esquecer:",
                color=discord.Color.orange()
            )
            # --- ALTERADO: Edita a resposta original da INTERAÇÃO ---
            await interaction.edit_original_response(content=None, embed=embed, view=view)
            # A Heart Scale já foi consumida. Se o usuário cancelar aqui,
            # o item foi gasto pelo serviço (como no jogo).


async def setup(bot: commands.Bot):
    await bot.add_cog(MoveRelearnerCog(bot))