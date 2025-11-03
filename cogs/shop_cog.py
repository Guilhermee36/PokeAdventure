# cogs/shop_cog.py

import discord
from discord.ext import commands
import os
import asyncio
from supabase import create_client, Client
import utils.evolution_utils as evolution_utils

def get_supabase_client():
    # ... (código existente, sem alterações) ...
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY")
    return create_client(url, key)

class ShopCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        # ... (código existente, sem alterações) ...
        self.bot = bot
        self.supabase: Client = get_supabase_client()
        self.evolve_pokemon_func = None 

    @commands.Cog.listener()
    async def on_ready(self):
        # ... (código existente, sem alterações) ...
        await asyncio.sleep(1) 
        evolution_cog = self.bot.get_cog("EvolutionCog")
        if evolution_cog:
            self.evolve_pokemon_func = evolution_cog.evolve_pokemon
            print("ShopCog conectado ao EvolutionCog com sucesso.")
        else:
            print("ERRO: ShopCog não conseguiu encontrar EvolutionCog.")

    async def get_player_money(self, player_id: int) -> int:
        # ... (código existente, sem alterações) ...
        try:
            res = self.supabase.table('players').select('money').eq('discord_id', player_id).single().execute()
            return res.data.get('money', 0) if res.data else 0
        except Exception:
            return 0

    async def update_player_money(self, player_id: int, new_amount: int) -> bool:
        # ... (código existente, sem alterações) ...
        try:
            self.supabase.table('players').update({'money': new_amount}).eq('discord_id', player_id).execute()
            return True
        except Exception as e:
            print(f"Erro ao atualizar dinheiro: {e}")
            return False

    async def add_item_to_inventory(self, player_id: int, item_id: int, quantity: int = 1):
        # ... (código existente, sem alterações) ...
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
    async def shop(self, ctx: commands.Context, *, category: str = None):
        # ... (código existente, sem alterações) ...
        shop_map = {
            '1': 'common', 'comuns': 'common',
            '2': 'special', 'especiais': 'special',
            '3': 'evo_stone', 'pedras': 'evo_stone',
            '4.': 'evo_held', 'seguraveis': 'evo_held',
            '5': 'mechanics', 'mecanicas': 'mechanics'
        }
        title_map = {
            'common': '🛒 Loja: Itens Comuns 🛒',
            'special': '🛒 Loja: Itens Especiais 🛒',
            'evo_stone': '🛒 Loja: Pedras de Evolução 🛒',
            'evo_held': '🛒 Loja: Itens Evolutivos (Seguráveis) 🛒',
            'mechanics': '🛒 Loja: Mecânicas de Batalha 🛒'
        }
        db_filter_type = None
        if category:
            db_filter_type = shop_map.get(category.lower())
        if not db_filter_type:
            embed = discord.Embed(title="🛒 Loja Pokémon 🛒", color=discord.Color.blue())
            embed.description = "Bem-vindo! Use `!shop <categoria>` para ver os itens."
            embed.add_field(name="`!shop 1` ou `!shop comuns`", value="Itens de Batalha (Pokeballs, Potions...)", inline=False)
            embed.add_field(name="`!shop 2` ou `!shop especiais`", value="Itens Raros (Link Cable, Itens de Hisui...)", inline=False)
            embed.add_field(name="`!shop 3` ou `!shop pedras`", value="Pedras de Evolução (Fire Stone, Moon Stone...)", inline=False)
            embed.add_field(name="`!shop 4` ou `!shop seguraveis`", value="Itens Evolutivos Seguráveis (Metal Coat...)", inline=False)
            embed.add_field(name="`!shop 5` ou `!shop mecanicas`", value="Sistemas Futuros (Mega Evolução...)", inline=False)
            embed.set_footer(text="Para comprar, use !buy \"Nome do Item\"")
            await ctx.send(embed=embed)
            return
        try:
            response = self.supabase.table('items') \
                .select('*') \
                .eq('type', db_filter_type) \
                .lte('required_badges', 99) \
                .order('name', desc=False) \
                .execute()
            if not response.data:
                await ctx.send(f"A categoria '{db_filter_type}' está vazia no momento ou você ainda não tem insígnias suficientes.")
                return
            embed = discord.Embed(title=title_map.get(db_filter_type, "🛒 Loja 🛒"), color=discord.Color.blue())
            embed.description = f"Itens disponíveis. Use `!buy \"Nome do Item\"`."
            for item in response.data:
                try:
                    price = int(item['effect_tag'].split(':')[-1])
                    price_str = f"${price:,}"
                except (ValueError, TypeError, IndexError):
                    price_str = "Preço Indefinido"
                badge_req = item.get('required_badges', 0)
                badge_str = f" (Requer {badge_req} Insígnias)" if badge_req > 0 else ""
                embed.add_field(name=f"{item['name']} - {price_str}{badge_str}", value=item['description'], inline=False)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"Ocorreu um erro ao carregar a loja: {e}")

    @commands.command(name='bag', help='Mostra seu inventário.')
    async def bag(self, ctx: commands.Context):
        """Exibe o inventário do jogador, organizado por novas categorias."""
        try:
            response = self.supabase.table('player_inventory') \
                .select('quantity, items(name, description, type)') \
                .eq('player_id', ctx.author.id) \
                .execute()

            if not response.data:
                await ctx.send("Seu inventário está vazio.")
                return

            embed = discord.Embed(title=f"🎒 Inventário de {ctx.author.display_name}", color=discord.Color.orange())
            
            # Mapeamento de categorias da bolsa
            bag_items = {
                'common': [], 'special': [], 'evo_stone': [], 'evo_held': [], 'mechanics': [], 'other': []
            }
            
            for item_entry in response.data:
                item = item_entry['items']
                if not item: 
                    continue
                    
                quantity = item_entry['quantity']
                item_type = item.get('type', 'other')
                
                item_str = f"**{item['name']}** (x{quantity})\n"
                bag_items.get(item_type, bag_items['other']).append(item_str)
            
            # Exibe as categorias que não estão vazias
            if bag_items['common']:
                embed.add_field(name="Itens Comuns", value="".join(bag_items['common']), inline=False)
            if bag_items['special']:
                embed.add_field(name="Itens Especiais", value="".join(bag_items['special']), inline=False)
            
            # ✅ CORREÇÃO: 'bag_le' -> 'bag_items'
            if bag_items['evo_stone']:
                embed.add_field(name="Pedras de Evolução", value="".join(bag_items['evo_stone']), inline=False)
                
            if bag_items['evo_held']:
                embed.add_field(name="Itens Seguráveis", value="".join(bag_items['evo_held']), inline=False)
            if bag_items['mechanics']:
                embed.add_field(name="Itens-Chave (Mecânicas)", value="".join(bag_items['mechanics']), inline=False)
            if bag_items['other']:
                embed.add_field(name="Outros", value="".join(bag_items['other']), inline=False)

            await ctx.send(embed=embed)
        except Exception as e:
            # Esta é a provável fonte do seu erro 'NoneType' se o item fosse nulo
            print(f"Erro no comando !bag: {e}") 
            await ctx.send(f"Ocorreu um erro ao abrir sua mochila: {e}")

    @commands.command(name='buy', help='Compra um item da loja.')
    async def buy(self, ctx: commands.Context, item_name: str, *, pokemon_name: str = None):
        """Compra um item da loja. (A lógica permanece a mesma)"""
        try:
            # ✅ CORREÇÃO: Pega o 'api_name' também
            item_res = self.supabase.table('items').select('*, api_name').ilike('name', item_name).single().execute()
            if not item_res.data:
                await ctx.send(f"O item `{item_name}` não existe na loja. Verifique o nome e use aspas se necessário.")
                return
            
            item = item_res.data
            item_id = item['id']
            tag_parts = item['effect_tag'].split(':')
            item_type_tag = tag_parts[0]
            item_price = int(tag_parts[1])

            current_money = await self.get_player_money(ctx.author.id)
            if current_money < item_price:
                await ctx.send(f"Você não tem dinheiro suficiente. Você tem ${current_money:,} e o item custa ${item_price:,}.")
                return

            if item_type_tag == 'EVO_ITEM':
                if not pokemon_name:
                    await ctx.send(f"O item `{item_name}` é de uso imediato. Você precisa especificar em qual Pokémon usá-lo.\nEx: `!buy \"{item_name}\" Eevee`")
                    return
                if not self.evolve_pokemon_func:
                    await ctx.send("Erro: O sistema de evolução não está online.")
                    return

                pokemon_res = self.supabase.table('player_pokemon').select('id').eq('player_id', ctx.author.id).ilike('nickname', pokemon_name.strip()).single().execute()
                if not pokemon_res.data:
                    await ctx.send(f"Não encontrei um Pokémon chamado `{pokemon_name}` na sua equipe.")
                    return

                pokemon_db_id = pokemon_res.data['id']
                
                # ✅ CORREÇÃO: Usa o 'api_name' para o contexto
                item_api_name = item.get('api_name')
                if not item_api_name:
                     await ctx.send(f"Erro de Jogo: O item `{item['name']}` não tem um `api_name` e não pode ser usado.")
                     return

                context = {"item_name": item_api_name}
                
                evo_result = await evolution_utils.check_evolution(
                    supabase=self.supabase,
                    pokemon_db_id=pokemon_db_id,
                    trigger_event="item_use",
                    context=context
                )

                if evo_result:
                    await self.update_player_money(ctx.author.id, current_money - item_price)
                    await self.evolve_pokemon_func(ctx.author.id, pokemon_db_id, evo_result['new_name'], ctx.channel)
                    await ctx.send(f"Você gastou ${item_price:,} no item **{item['name']}**.")
                else:
                    await ctx.send(f"O item **{item_name}** não parece ter efeito em **{pokemon_name}** (verifique as condições, como hora do dia).")

            elif item_type_tag == 'STORABLE':
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
        # ... (código existente, sem alterações) ...
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