# cogs/shop_cog.py

import discord
from discord.ext import commands
from discord import ui
import os
import aiohttp
import asyncio
from supabase import create_client, Client
from postgrest import APIResponse

# IMPORTA O "CÉREBRO" DE EVOLUÇÃO
import utils.evolution_utils as evolution_utils

# --- Funções Auxiliares (Apenas Supabase) ---

def get_supabase_client():
    """Cria e retorna um cliente Supabase."""
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY")
    return create_client(url, key)

# =================================================================
# <<< FUNÇÕES DE API (get_species, get_data, find_details) REMOVIDAS >>>
# Elas não são mais necessárias aqui.
# =================================================================

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
        await asyncio.sleep(1) 
        
        evolution_cog = self.bot.get_cog("EvolutionCog")
        if evolution_cog:
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

    async def add_item_to_inventory(self, player_id: int, item_id: int, quantity: int = 1):
        """Adiciona um item ao inventário do jogador (upsert)."""
        # (Mantendo sua lógica de upsert corrigida)
        try:
            current_response = self.supabase.table('player_inventory') \
                .select('quantity') \
                .eq('player_id', player_id) \
                .eq('item_id', item_id) \
                .execute()

            if current_response.data:
                current_quantity = current_response.data[0]['quantity']
                new_quantity = current_quantity + quantity
                
                self.supabase.table('player_inventory') \
                    .update({'quantity': new_quantity}) \
                    .eq('player_id', player_id) \
                    .eq('item_id', item_id) \
                    .execute()
            else:
                self.supabase.table('player_inventory') \
                    .insert({'player_id': player_id, 'item_id': item_id, 'quantity': quantity}) \
                    .execute()
            return True
        except Exception as e:
            print(f"Erro ao adicionar item ao inventário: {e}")
            return False

    @commands.command(name='shop', help='Mostra a loja de itens.')
    async def shop(self, ctx: commands.Context):
        # ... (Código do !shop sem alterações) ...
        try:
            response = self.supabase.table('items').select('*').in_('type', ['evolution', 'utility']).execute()
            if not response.data:
                await ctx.send("A loja está vazia no momento.")
                return

            embed = discord.Embed(title="🛒 Loja Pokémon 🛒", color=discord.Color.blue())
            embed.description = "Use `!buy \"Nome do Item\" [Nome do Pokémon]`."
            
            for item in response.data:
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
        # ... (Código do !bag sem alterações) ...
        try:
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

                # ========================================================
                # <<< LÓGICA DE EVOLUÇÃO REFATORADA >>>
                # ========================================================
                
                # 1. Encontra o Pokémon
                pokemon_res = self.supabase.table('player_pokemon').select('id').eq('player_id', ctx.author.id).ilike('nickname', pokemon_name.strip()).single().execute()
                if not pokemon_res.data:
                    await ctx.send(f"Não encontrei um Pokémon chamado `{pokemon_name}` na sua equipe.")
                    return

                pokemon_db_id = pokemon_res.data['id']

                # 2. Monta o contexto (normaliza o nome do item)
                item_api_name = item['name'].lower().replace(' ', '-')
                context = {"item_name": item_api_name}
                
                # 3. Chama o "Cérebro" Central
                evo_result = await evolution_utils.check_evolution(
                    supabase=self.supabase,
                    pokemon_db_id=pokemon_db_id,
                    trigger_event="item_use",
                    context=context
                )

                if evo_result:
                    # 4. Pagamento e Evolução
                    await self.update_player_money(ctx.author.id, current_money - item_price)
                    await self.evolve_pokemon_func(ctx.author.id, pokemon_db_id, evo_result['new_name'], ctx.channel)
                    await ctx.send(f"Você gastou ${item_price:,} no item **{item['name']}**.")
                else:
                    await ctx.send(f"O item **{item_name}** não parece ter efeito em **{pokemon_name}**.")
                
                # ========================================================
                # <<< FIM DA REFATORAÇÃO >>>
                # ========================================================

            # --- TIPO 2: Item Armazenável (Guarda no inventário) ---
            elif item_type == 'STORABLE':
                # ... (Código de item armazenável sem alterações) ...
                success_money = await self.update_player_money(ctx.author.id, current_money - item_price)
                if not success_money:
                    await ctx.send("Ocorreu um erro ao processar seu pagamento.")
                    return
                
                success_item = await self.add_item_to_inventory(ctx.author.id, item_id, 1)
                if not success_item:
                    await self.update_player_money(ctx.author.id, current_money)
                    await ctx.send("Ocorreu um erro ao guardar o item no seu inventário. Seu dinheiro foi devolvido.")
                    return
                
                await ctx.send(f"Você comprou 1x **{item_name}** por ${item_price:,}! Ele foi guardado na sua mochila (`!bag`).")
            
            else:
                await ctx.send(f"O item `{item_name}` não pode ser comprado (tipo indefinido).")

        except Exception as e:
            await ctx.send(f"Ocorreu um erro inesperado no comando !buy.")
            print(f"Erro no comando !buy (ShopCog): {e}")

    @commands.command(name='givemoney', help='(Admin) Adiciona dinheiro ao seu perfil.')
    @commands.is_owner()
    async def give_money(self, ctx: commands.Context, amount: int):
        # ... (Código do !givemoney sem alterações) ...
        if amount <= 0:
            await ctx.send("A quantia deve ser um número positivo.")
            return
        try:
            current_money = await self.get_player_money(ctx.author.id)
            new_amount = current_money + amount
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