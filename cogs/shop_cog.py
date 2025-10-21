# cogs/shop_cog.py

import discord
from discord.ext import commands
from discord import ui
import os
import aiohttp
import asyncio # Importado para o listener on_ready
from supabase import create_client, Client
from postgrest import APIResponse

# --- Funções Auxiliares (Copiadas para modularidade) ---

def get_supabase_client():
    """Cria e retorna um cliente Supabase."""
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY")
    return create_client(url, key)

async def get_pokemon_species_data(pokemon_name: str):
    """Busca dados da ESPÉCIE de um Pokémon da PokeAPI."""
    url = f"https://pokeapi.co/api/v2/pokemon-species/{pokemon_name.lower()}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.json()
            return None

async def get_data_from_url(url: str):
    """Busca dados de uma URL específica (ex: evolution_chain)."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.json()
            return None

def find_evolution_details(chain_link: dict, current_species_name: str) -> list:
    """Função auxiliar de pokeapi_service.py (copiada para modularidade)"""
    if chain_link['species']['name'] == current_species_name:
        return chain_link['evolves_to']
    
    for evolution in chain_link['evolves_to']:
        found = find_evolution_details(evolution, current_species_name)
        if found:
            return found
    return []

# --- Cog Class ---

class ShopCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.supabase: Client = get_supabase_client()
        # Armazena a função de evoluir (do evolution_cog) para o !buy
        self.evolve_pokemon_func = None 

    @commands.Cog.listener()
    async def on_ready(self):
        """Espera o bot estar pronto e busca o cog de evolução."""
        # Damos um pequeno tempo para todos os cogs carregarem
        await asyncio.sleep(1) 
        
        evolution_cog = self.bot.get_cog("EvolutionCog")
        if evolution_cog:
            # Armazena a referência da função evolve_pokemon
            self.evolve_pokemon_func = evolution_cog.evolve_pokemon
            print("ShopCog conectado ao EvolutionCog com sucesso.")
        else:
            print("ERRO: ShopCog não conseguiu encontrar EvolutionCog.")

    async def get_player_money(self, player_id: int) -> int:
        """Busca o dinheiro do jogador."""
        try:
            res = self.supabase.table('players').select('money').eq('discord_id', player_id).single().execute()
            return res.data.get('money', 0) if res.data else 0
        except Exception:
            return 0

    async def update_player_money(self, player_id: int, new_amount: int) -> bool:
        """Atualiza o dinheiro do jogador."""
        try:
            self.supabase.table('players').update({'money': new_amount}).eq('discord_id', player_id).execute()
            return True
        except Exception as e:
            print(f"Erro ao atualizar dinheiro: {e}")
            return False

    # =================================================================
    # <<< CORREÇÃO APLICADA AQUI >>>
    # =================================================================
    async def add_item_to_inventory(self, player_id: int, item_id: int, quantity: int = 1):
        """Adiciona um item ao inventário do jogador (upsert)."""
        try:
            # 1. Tenta buscar o item (SEM .single())
            current_response = self.supabase.table('player_inventory') \
                .select('quantity') \
                .eq('player_id', player_id) \
                .eq('item_id', item_id) \
                .execute()

            # current_response.data agora será [] (vazio) se o item não existe,
            # ou [{'quantity': 5}] se ele existe.

            if current_response.data:
                # Se a lista NÃO está vazia, o item existe.
                current_quantity = current_response.data[0]['quantity']
                new_quantity = current_quantity + quantity
                
                self.supabase.table('player_inventory') \
                    .update({'quantity': new_quantity}) \
                    .eq('player_id', player_id) \
                    .eq('item_id', item_id) \
                    .execute()
            else:
                # Se a lista ESTÁ vazia, o item não existe. Insere um novo.
                self.supabase.table('player_inventory') \
                    .insert({'player_id': player_id, 'item_id': item_id, 'quantity': quantity}) \
                    .execute()
            
            return True # Sucesso em ambos os casos
            
        except Exception as e:
            print(f"Erro ao adicionar item ao inventário: {e}")
            return False
    # =================================================================
    # <<< FIM DA CORREÇÃO >>>
    # =================================================================

    @commands.command(name='shop', help='Mostra a loja de itens.')
    async def shop(self, ctx: commands.Context):
        """Mostra uma loja com itens do banco de dados."""
        try:
            response = self.supabase.table('items').select('*').in_('type', ['evolution', 'utility']).execute()
            if not response.data:
                await ctx.send("A loja está vazia no momento.")
                return

            embed = discord.Embed(title="🛒 Loja Pokémon 🛒", color=discord.Color.blue())
            embed.description = "Use `!buy \"Nome do Item\" [Nome do Pokémon]`."
            
            for item in response.data:
                # O effect_tag agora armazena o preço
                try:
                    price = int(item['effect_tag'].split(':')[-1])
                    price_str = f"${price:,}"
                except (ValueError, TypeError, IndexError):
                    price_str = "Preço Indefinido"
                
                embed.add_field(name=f"{item['name']} - {price_str}", value=item['description'], inline=False)
                
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"Ocorreu um erro ao carregar a loja: {e}")

    @commands.command(name='bag', help='Mostra seu inventário.')
    async def bag(self, ctx: commands.Context):
        """Exibe o inventário do jogador."""
        try:
            # Faz um JOIN para pegar os nomes dos itens
            response = self.supabase.table('player_inventory') \
                .select('quantity, items(name, description)') \
                .eq('player_id', ctx.author.id) \
                .execute()

            if not response.data:
                await ctx.send("Seu inventário está vazio.")
                return

            embed = discord.Embed(title=f"🎒 Inventário de {ctx.author.display_name}", color=discord.Color.orange())
            
            description = []
            for item_entry in response.data:
                item = item_entry['items']
                quantity = item_entry['quantity']
                description.append(f"**{item['name']}** (x{quantity})\n_{item['description']}_")
            
            embed.description = "\n\n".join(description)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"Ocorreu um erro ao abrir sua mochila: {e}")

    @commands.command(name='buy', help='Compra um item da loja.')
    async def buy(self, ctx: commands.Context, item_name: str, *, pokemon_name: str = None):
        """Compra um item da loja. Requer o nome do Pokémon para itens de evolução."""
        try:
            # 1. Buscar o item na loja
            item_res = self.supabase.table('items').select('*').ilike('name', item_name).single().execute()
            if not item_res.data:
                await ctx.send(f"O item `{item_name}` não existe na loja.")
                return
            
            item = item_res.data
            item_id = item['id']
            tag_parts = item['effect_tag'].split(':')
            item_type = tag_parts[0]
            item_price = int(tag_parts[1])

            # 2. Verificar dinheiro do jogador
            current_money = await self.get_player_money(ctx.author.id)
            if current_money < item_price:
                await ctx.send(f"Você não tem dinheiro suficiente. Você tem ${current_money:,} e o item custa ${item_price:,}.")
                return

            # 3. Processar a compra com base no tipo
            
            # --- TIPO 1: Item de Evolução (Uso imediato) ---
            if item_type == 'EVO_ITEM':
                if not pokemon_name:
                    await ctx.send(f"O item `{item_name}` é um item de evolução. Você precisa especificar em qual Pokémon usá-lo.\nEx: `!buy \"{item_name}\" {ctx.author.display_name}`")
                    return
                
                if not self.evolve_pokemon_func:
                    await ctx.send("Erro: O sistema de evolução não está online. Tente novamente mais tarde.")
                    return

                # Lógica de evolução (baseada no evolution_cog.py)
                pokemon_res = self.supabase.table('player_pokemon').select('*').eq('player_id', ctx.author.id).ilike('nickname', pokemon_name.strip()).single().execute()
                if not pokemon_res.data:
                    await ctx.send(f"Não encontrei um Pokémon chamado `{pokemon_name}` na sua equipe.")
                    return

                pokemon = pokemon_res.data
                species_data = await get_pokemon_species_data(pokemon['pokemon_api_name'])
                if not species_data or not species_data.get('evolution_chain'):
                    await ctx.send(f"**{pokemon_name}** não parece poder evoluir.")
                    return

                evo_chain_url = species_data['evolution_chain']['url']
                evo_chain_data = await get_data_from_url(evo_chain_url)
                possible_evolutions = find_evolution_details(evo_chain_data['chain'], pokemon['pokemon_api_name'])
                
                found_match = False
                for evo in possible_evolutions:
                    details = evo['evolution_details'][0]
                    # Compara o nome do item da API com o nome do item no nosso DB
                    if details['trigger']['name'] == 'use-item' and details.get('item') and details['item']['name'] == item['name'].lower().replace(' ', '-'):
                        new_form = evo['species']['name']
                        
                        # Debita o dinheiro
                        await self.update_player_money(ctx.author.id, current_money - item_price)
                        # Evolui o Pokémon
                        await self.evolve_pokemon_func(ctx.author.id, pokemon['id'], new_form, ctx.channel)
                        
                        await ctx.send(f"Você gastou ${item_price:,} no item **{item_name}**.")
                        found_match = True
                        break
                
                if not found_match:
                    await ctx.send(f"O item **{item_name}** não parece ter efeito em **{pokemon_name}**.")

            # --- TIPO 2: Item Armazenável (Guarda no inventário) ---
            elif item_type == 'STORABLE':
                # Debita o dinheiro
                success_money = await self.update_player_money(ctx.author.id, current_money - item_price)
                if not success_money:
                    await ctx.send("Ocorreu um erro ao processar seu pagamento.")
                    return
                
                # Adiciona ao inventário
                success_item = await self.add_item_to_inventory(ctx.author.id, item_id, 1)
                if not success_item:
                    # Tenta devolver o dinheiro
                    await self.update_player_money(ctx.author.id, current_money)
                    await ctx.send("Ocorreu um erro ao guardar o item no seu inventário. Seu dinheiro foi devolvido.")
                    return
                
                await ctx.send(f"Você comprou 1x **{item_name}** por ${item_price:,}! Ele foi guardado na sua mochila (`!bag`).")
            
            else:
                await ctx.send(f"O item `{item_name}` não pode ser comprado (tipo indefinido).")

        except Exception as e:
            await ctx.send(f"Ocorreu um erro inesperado no comando !buy.")
            print(f"Erro no comando !buy (ShopCog): {e}")

    # =================================================================
    # <<< COMANDO GIVE MONEY (Permanece igual) >>>
    # =================================================================
    @commands.command(name='givemoney', help='(Admin) Adiciona dinheiro ao seu perfil.')
    @commands.is_owner()
    async def give_money(self, ctx: commands.Context, amount: int):
        """(Admin) Dá dinheiro para o jogador."""
        if amount <= 0:
            await ctx.send("A quantia deve ser um número positivo.")
            return

        try:
            # 1. Pega o dinheiro atual
            current_money = await self.get_player_money(ctx.author.id)
            
            # 2. Calcula o novo total
            new_amount = current_money + amount
            
            # 3. Atualiza no banco de dados
            success = await self.update_player_money(ctx.author.id, new_amount)
            
            if success:
                await ctx.send(f"💸 Você adicionou ${amount:,} à sua conta! Novo saldo: ${new_amount:,}.")
            else:
                await ctx.send("Falha ao atualizar o dinheiro no banco de dados.")
        
        except Exception as e:
            await ctx.send(f"Ocorreu um erro inesperado: {e}")
            print(f"Erro no !givemoney: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(ShopCog(bot))