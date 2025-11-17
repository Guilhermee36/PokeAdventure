# cogs/shop_cog.py

import discord
from discord.ext import commands
from discord import ui
import os
import aiohttp
import asyncio
import random
from supabase import create_client, Client
from postgrest import APIResponse

import utils.evolution_utils as evolution_utils

def get_supabase_client():
    """Cria e retorna um cliente Supabase."""
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY")
    return create_client(url, key)


class ShopCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.supabase: Client = get_supabase_client()
        # Armazena a função de evoluir (do evolution_cog) para o !buy
        self.evolve_pokemon_func = None

        # Cache opcional para futuras lojas de Pokémon
        self.pokeshop_cache: dict[int, list[dict]] = {}

    # ------------------------------------------------------------------
    # Helpers de DB (sem .single())
    # ------------------------------------------------------------------
    async def get_player_money(self, player_id: int) -> int:
        """Busca o dinheiro do jogador (safe, sem .single())."""
        try:
            res = (
                self.supabase.table("players")
                .select("money")
                .eq("discord_id", player_id)
                .limit(1)
                .execute()
            )
            data = res.data[0] if res.data else None
            return int(data.get("money", 0)) if data else 0
        except Exception as e:
            print(f"[DB][Shop][get_player_money] erro: {e}")
            return 0

    async def update_player_money(self, player_id: int, new_amount: int) -> bool:
        """Atualiza o dinheiro do jogador."""
        try:
            self.supabase.table("players").update({"money": new_amount}).eq(
                "discord_id", player_id
            ).execute()
            return True
        except Exception as e:
            print(f"[DB][Shop][update_player_money] erro: {e}")
            return False

    async def add_item_to_inventory(
        self, player_id: int, item_id: int, quantity: int = 1
    ) -> bool:
        """Adiciona um item ao inventário do jogador (upsert) em quantidade."""
        if quantity <= 0:
            return True

        try:
            current_response = (
                self.supabase.table("player_inventory")
                .select("quantity")
                .eq("player_id", player_id)
                .eq("item_id", item_id)
                .execute()
            )

            if current_response.data:
                current_quantity = current_response.data[0]["quantity"]
                new_quantity = current_quantity + quantity
                (
                    self.supabase.table("player_inventory")
                    .update({"quantity": new_quantity})
                    .eq("player_id", player_id)
                    .eq("item_id", item_id)
                    .execute()
                )
            else:
                (
                    self.supabase.table("player_inventory")
                    .insert(
                        {
                            "player_id": player_id,
                            "item_id": item_id,
                            "quantity": quantity,
                        }
                    )
                    .execute()
                )
            return True
        except Exception as e:
            print(f"[DB][Shop][add_item_to_inventory] erro: {e}")
            return False

    # ------------------------------------------------------------------
    # Integração com EvolutionCog
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Comando !shop (mesmo comportamento, texto atualizado p/ quantidade)
    # ------------------------------------------------------------------
    @commands.command(name="shop", help="Mostra a loja de itens.")
    async def shop(self, ctx: commands.Context, *, category: str = None):
        """Mostra uma loja com itens do banco de dados, filtrada por categoria."""

        # Mapeamento expandido para 5 categorias
        shop_map = {
            "1": "common",
            "comuns": "common",
            "2": "special",
            "especiais": "special",
            "3": "evo_stone",
            "pedras": "evo_stone",
            "4": "evo_held",
            "seguraveis": "evo_held",
            "5": "mechanics",
            "mecanicas": "mechanics",
        }

        title_map = {
            "common": "🛒 Loja: Itens Comuns 🛒",
            "special": "🛒 Loja: Itens Especiais 🛒",
            "evo_stone": "🛒 Loja: Pedras de Evolução 🛒",
            "evo_held": "🛒 Loja: Itens Evolutivos (Seguráveis) 🛒",
            "mechanics": "🛒 Loja: Mecânicas de Batalha 🛒",
        }

        db_filter_type = None
        if category:
            db_filter_type = shop_map.get(category.lower())

        # Se nenhuma categoria foi dada ou a categoria é inválida, mostra o menu
        if not db_filter_type:
            embed = discord.Embed(
                title="🛒 Loja Pokémon 🛒", color=discord.Color.blue()
            )
            embed.description = (
                "Bem-vindo! Use `!shop <categoria>` para ver os itens.\n\n"
                "Agora você também pode comprar **em quantidade** com `!buy \"Item\" <quantidade>`.\n"
                "Exemplo: `!buy \"Pokeball\" 10`"
            )
            embed.add_field(
                name="`!shop 1` ou `!shop comuns`",
                value="Itens de Batalha (Pokeballs, Potions...)",
                inline=False,
            )
            embed.add_field(
                name="`!shop 2` ou `!shop especiais`",
                value="Itens Raros (Link Cable, Itens de Hisui...)",
                inline=False,
            )
            embed.add_field(
                name="`!shop 3` ou `!shop pedras`",
                value="Pedras de Evolução (Fire Stone, Moon Stone...)",
                inline=False,
            )
            embed.add_field(
                name="`!shop 4` ou `!shop seguraveis`",
                value="Itens Evolutivos Seguráveis (Metal Coat...)",
                inline=False,
            )
            embed.add_field(
                name="`!shop 5` ou `!shop mecanicas`",
                value="Sistemas Futuros (Mega Evolução...)",
                inline=False,
            )
            embed.set_footer(
                text="Para comprar, use !buy \"Nome do Item\" [quantidade]\nEx: !buy \"Pokeball\" 10"
            )
            await ctx.send(embed=embed)
            return

        # Se a categoria é válida, busca os itens
        try:
            response = (
                self.supabase.table("items")
                .select("*")
                .eq("type", db_filter_type)
                .lte("required_badges", 99)
                .order("name", desc=False)
                .execute()
            )

            if not response.data:
                await ctx.send(
                    f"A categoria '{db_filter_type}' está vazia no momento ou você ainda não tem insígnias suficientes."
                )
                return

            embed = discord.Embed(
                title=title_map.get(db_filter_type, "🛒 Loja 🛒"),
                color=discord.Color.blue(),
            )
            embed.description = (
                "Itens disponíveis.\n"
                "• Itens normais: `!buy \"Nome do Item\" <quantidade>`\n"
                "• Itens de evolução: `!buy \"Nome do Item\" <Apelido do Pokémon>`"
            )

            for item in response.data:
                price_str = "Preço Indefinido"
                effect_tag = item.get("effect_tag")
                if effect_tag:
                    try:
                        price = int(effect_tag.split(":")[-1])
                        price_str = f"${price:,}"
                    except (ValueError, TypeError, IndexError):
                        price_str = "Preço Mal Formado"

                badge_req = item.get("required_badges", 0)
                badge_str = (
                    f" (Requer {badge_req} Insígnias)" if badge_req > 0 else ""
                )

                embed.add_field(
                    name=f"{item['name']} - {price_str}{badge_str}",
                    value=item["description"],
                    inline=False,
                )

            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"Ocorreu um erro ao carregar a loja: {e}")

    # ------------------------------------------------------------------
    # Comando !bag (igual, só com logs melhores)
    # ------------------------------------------------------------------
    @commands.command(name="bag", help="Mostra seu inventário.")
    async def bag(self, ctx: commands.Context):
        """Exibe o inventário do jogador, organizado por novas categorias."""
        try:
            response = (
                self.supabase.table("player_inventory")
                .select("quantity, items(name, description, type)")
                .eq("player_id", ctx.author.id)
                .execute()
            )

            if not response.data:
                await ctx.send("Seu inventário está vazio.")
                return

            embed = discord.Embed(
                title=f"🎒 Inventário de {ctx.author.display_name}",
                color=discord.Color.orange(),
            )

            bag_items = {
                "common": [],
                "special": [],
                "evo_stone": [],
                "evo_held": [],
                "mechanics": [],
                "other": [],
            }

            for item_entry in response.data:
                item = item_entry["items"]
                if not item:
                    continue

                quantity = item_entry["quantity"]
                item_type = item.get("type", "other")

                item_str = f"**{item['name']}** (x{quantity})\n"
                bag_items.get(item_type, bag_items["other"]).append(item_str)

            if bag_items["common"]:
                embed.add_field(
                    name="Itens Comuns",
                    value="".join(bag_items["common"]),
                    inline=False,
                )
            if bag_items["special"]:
                embed.add_field(
                    name="Itens Especiais",
                    value="".join(bag_items["special"]),
                    inline=False,
                )
            if bag_items["evo_stone"]:
                embed.add_field(
                    name="Pedras de Evolução",
                    value="".join(bag_items["evo_stone"]),
                    inline=False,
                )
            if bag_items["evo_held"]:
                embed.add_field(
                    name="Itens Seguráveis",
                    value="".join(bag_items["evo_held"]),
                    inline=False,
                )
            if bag_items["mechanics"]:
                embed.add_field(
                    name="Itens-Chave (Mecânicas)",
                    value="".join(bag_items["mechanics"]),
                    inline=False,
                )
            if bag_items["other"]:
                embed.add_field(
                    name="Outros",
                    value="".join(bag_items["other"]),
                    inline=False,
                )

            await ctx.send(embed=embed)
        except Exception as e:
            print(f"[DB][Shop][bag] erro: {e}")
            await ctx.send(f"Ocorreu um erro ao abrir sua mochila: {e}")

    # ------------------------------------------------------------------
    # Parsing novo do !buy com quantidade
    # ------------------------------------------------------------------
    def _parse_buy_args(self, raw: str):
        """
        Retorna (item_name, quantity, pokemon_name).

        Regras:
          - Se começar com aspas, pega até a próxima aspas como nome do item.
          - Se o último token for inteiro -> quantidade.
          - Se NÃO for inteiro, pode ser pokemon_name (para EVO_ITEM).
        """
        raw = raw.strip()
        item_name = None
        quantity = None
        pokemon_name = None

        # Caso com aspas: !buy "Fire Stone" Eevee  OU  !buy "Potion" 10
        if raw.startswith('"'):
            closing = raw.find('"', 1)
            if closing == -1:
                # Sem segunda aspa, trata tudo como nome.
                item_name = raw.strip('"')
                return item_name, quantity, pokemon_name

            item_name = raw[1:closing]
            rest = raw[closing + 1 :].strip()

            if not rest:
                return item_name, quantity, pokemon_name

            parts = rest.split()
            if len(parts) == 1 and parts[0].isdigit():
                quantity = int(parts[0])
            else:
                # Para itens de evolução, tratamos o resto como nome do Pokémon
                pokemon_name = rest
            return item_name, quantity, pokemon_name

        # Sem aspas: !buy Pokeball 10  OU  !buy Fire Stone Eevee
        parts = raw.split()
        if not parts:
            return None, None, None

        # Se só tiver um token, é só o item
        if len(parts) == 1:
            return parts[0], None, None

        # Se o último token é inteiro, é quantidade
        if parts[-1].isdigit():
            quantity = int(parts[-1])
            item_name = " ".join(parts[:-1])
            return item_name, quantity, None

        # Senão, trata tudo como nome do item (ou deixa para EVO_ITEM resolver)
        item_name = " ".join(parts)
        return item_name, None, None

    @commands.command(
        name="buy",
        help='Compra um item da loja. Uso: !buy "Item" [quantidade] ou !buy "Evo Item" Pokémon',
    )
    async def buy(self, ctx: commands.Context, *, raw_args: str):
        """Compra um item da loja, agora com suporte a quantidade."""
        try:
            item_name, quantity, pokemon_name = self._parse_buy_args(raw_args)

            if not item_name:
                await ctx.send(
                    "Uso: `!buy \"Nome do Item\" [quantidade]` ou `!buy \"Evo Item\" ApelidoDoPokémon`."
                )
                return

            # Busca o item (sem .single())
            item_res = (
                self.supabase.table("items")
                .select("*, api_name")
                .ilike("name", item_name)
                .limit(1)
                .execute()
            )

            if not item_res.data:
                await ctx.send(
                    f"O item `{item_name}` não existe na loja. Verifique o nome e use aspas se necessário."
                )
                return

            item = item_res.data[0]
            item_id = item["id"]

            # =================================================================
            # CORREÇÃO DO 'effect_tag' NULO + parsing
            # =================================================================
            effect_tag = item.get("effect_tag")

            if not effect_tag:
                await ctx.send(
                    f"Erro de Jogo: O item `{item['name']}` tem um `effect_tag` inválido (NULO) no banco de dados. Este item não pode ser comprado."
                )
                return

            try:
                tag_parts = effect_tag.split(":")
                item_type_tag = tag_parts[0]
                item_price = int(tag_parts[1])
            except (ValueError, IndexError):
                await ctx.send(
                    f"Erro de Jogo: O item `{item['name']}` tem um `effect_tag` mal formatado (`{effect_tag}`). "
                    "O formato esperado é 'TIPO:PREÇO' (ex: 'STORABLE:5000')."
                )
                return
            # =================================================================

            # Se quantidade não foi passada, default é 1 (para itens guardáveis)
            if quantity is None:
                quantity = 1

            # EVOLUTION ITEMS: ainda tratamos como uso imediato, 1 por vez.
            if item_type_tag == "EVO_ITEM":
                if quantity != 1:
                    await ctx.send(
                        f"O item `{item_name}` é de uso imediato e só pode ser comprado **1 por vez**.\n"
                        f"Use: `!buy \"{item_name}\" ApelidoDoPokémon`."
                    )
                    return

                if not pokemon_name:
                    await ctx.send(
                        f"O item `{item_name}` é de uso imediato. Você precisa especificar em qual Pokémon usá-lo.\n"
                        f"Ex: `!buy \"{item_name}\" Eevee`"
                    )
                    return
                if not self.evolve_pokemon_func:
                    await ctx.send("Erro: O sistema de evolução não está online.")
                    return

                # Busca o Pokémon do jogador (sem .single())
                pokemon_res = (
                    self.supabase.table("player_pokemon")
                    .select("id")
                    .eq("player_id", ctx.author.id)
                    .ilike("nickname", pokemon_name.strip())
                    .limit(1)
                    .execute()
                )
                if not pokemon_res.data:
                    await ctx.send(
                        f"Não encontrei um Pokémon chamado `{pokemon_name}` na sua equipe."
                    )
                    return

                pokemon_db_id = pokemon_res.data[0]["id"]

                item_api_name = item.get("api_name")
                if not item_api_name:
                    await ctx.send(
                        f"Erro de Jogo: O item `{item['name']}` não tem um `api_name` e não pode ser usado."
                    )
                    return

                current_money = await self.get_player_money(ctx.author.id)
                if current_money < item_price:
                    await ctx.send(
                        f"Você não tem dinheiro suficiente. Você tem ${current_money:,} e o item custa ${item_price:,}."
                    )
                    return

                context = {"item_name": item_api_name}

                evo_result = await evolution_utils.check_evolution(
                    supabase=self.supabase,
                    pokemon_db_id=pokemon_db_id,
                    trigger_event="item_use",
                    context=context,
                )

                if evo_result:
                    await self.update_player_money(
                        ctx.author.id, current_money - item_price
                    )
                    await self.evolve_pokemon_func(
                        ctx.author.id,
                        pokemon_db_id,
                        evo_result["new_name"],
                        ctx.channel,
                    )
                    await ctx.send(
                        f"Você gastou ${item_price:,} no item **{item['name']}**."
                    )
                else:
                    await ctx.send(
                        f"O item **{item_name}** não parece ter efeito em **{pokemon_name}** "
                        "(verifique as condições, como hora do dia)."
                    )
                return

            # STORABLE (ex: Pokeballs, potions etc.) — aqui entra quantidade
            if item_type_tag == "STORABLE":
                if quantity <= 0:
                    await ctx.send("A quantidade precisa ser um número positivo.")
                    return

                current_money = await self.get_player_money(ctx.author.id)
                total_price = item_price * quantity

                if current_money < total_price:
                    await ctx.send(
                        f"Você não tem dinheiro suficiente.\n"
                        f"• Saldo atual: ${current_money:,}\n"
                        f"• Preço unitário: ${item_price:,}\n"
                        f"• Quantidade: {quantity}\n"
                        f"• Total: ${total_price:,}"
                    )
                    return

                # Debita o dinheiro
                success_money = await self.update_player_money(
                    ctx.author.id, current_money - total_price
                )
                if not success_money:
                    await ctx.send(
                        "Ocorreu um erro ao processar seu pagamento. Tente novamente."
                    )
                    return

                # Adiciona os itens
                success_item = await self.add_item_to_inventory(
                    ctx.author.id, item_id, quantity
                )
                if not success_item:
                    # Tenta reverter o dinheiro
                    await self.update_player_money(ctx.author.id, current_money)
                    await ctx.send(
                        "Ocorreu um erro ao guardar o item no seu inventário. Seu dinheiro foi devolvido."
                    )
                    return

                await ctx.send(
                    f"Você comprou **{quantity}x {item_name}** por ${total_price:,}! "
                    "Eles foram guardados na sua mochila (`!bag`)."
                )
                return

            # Outros tipos (caso tenham)
            await ctx.send(
                f"O item `{item_name}` não pode ser comprado (tipo indefinido: `{item_type_tag}`)."
            )

        except Exception as e:
            await ctx.send(f"Ocorreu um erro inesperado no comando !buy.")
            print(f"[Shop][buy] erro: {e}")

    # ------------------------------------------------------------------
    # Cassino simples: !coinflip
    # ------------------------------------------------------------------
    @commands.command(
        name="coinflip",
        help="Cassino simples: cara ou coroa. Uso: !coinflip <valor> <cara|coroa>",
    )
    async def coinflip(self, ctx: commands.Context, amount: int, choice: str):
        """
        Minijogo de aposta básica:
          - 50% de chance
          - Se acertar, ganha o dobro da aposta (lucro = aposta)
          - Se perder, perde o valor apostado
        """
        choice = choice.lower()
        if choice not in ("cara", "coroa"):
            await ctx.send("Escolha precisa ser `cara` ou `coroa`.")
            return

        if amount <= 0:
            await ctx.send("A aposta deve ser um número positivo.")
            return

        # Limite simples por aposta (você pode ajustar)
        MAX_BET = 50_000
        if amount > MAX_BET:
            await ctx.send(
                f"O máximo por aposta é ${MAX_BET:,}. Reduza sua aposta, high roller. 💸"
            )
            return

        current_money = await self.get_player_money(ctx.author.id)
        if current_money < amount:
            await ctx.send(
                f"Você não tem dinheiro suficiente para apostar ${amount:,}. "
                f"Saldo atual: ${current_money:,}."
            )
            return

        # Roda o coinflip
        result = random.choice(["cara", "coroa"])

        if result == choice:
            # Ganhou: +amount
            new_money = current_money + amount
            delta = amount
            outcome_text = (
                f"🎉 Deu **{result}** e você acertou!\n"
                f"Você ganhou **${amount:,}** (lucro)."
            )
        else:
            # Perdeu: -amount
            new_money = current_money - amount
            delta = -amount
            outcome_text = (
                f"💀 Deu **{result}** e você errou...\n"
                f"Você perdeu **${amount:,}**."
            )

        success = await self.update_player_money(ctx.author.id, new_money)
        if not success:
            await ctx.send(
                "Ocorreu um erro ao atualizar seu saldo. A aposta foi cancelada."
            )
            return

        # Tenta registrar log (se a tabela existir)
        try:
            self.supabase.table("player_gambling_logs").insert(
                {
                    "player_id": ctx.author.id,
                    "game_type": "coinflip",
                    "bet_amount": amount,
                    "result_amount": delta,
                }
            ).execute()
        except Exception as e:
            # Tabela pode não existir ainda – logamos só no console.
            print(f"[Cassino][coinflip] falha ao registrar log (ok ignorar): {e}")

        embed = discord.Embed(
            title="🎰 Cassino - Coinflip", color=discord.Color.gold()
        )
        embed.description = outcome_text
        embed.add_field(
            name="Saldo Atual",
            value=f"${new_money:,}",
            inline=False,
        )
        embed.set_footer(text="Jogue com responsabilidade. 😄")

        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # !givemoney admin (sem alterações grandes)
    # ------------------------------------------------------------------
    @commands.command(
        name="givemoney", help="(Admin) Adiciona dinheiro ao seu perfil."
    )
    @commands.is_owner()
    async def give_money(self, ctx: commands.Context, amount: int):
        """(Admin) Dá dinheiro para o jogador."""
        if amount <= 0:
            await ctx.send("A quantia deve ser um número positivo.")
            return
        try:
            current_money = await self.get_player_money(ctx.author.id)
            new_amount = current_money + amount
            success = await self.update_player_money(ctx.author.id, new_amount)
            if success:
                await ctx.send(
                    f"💸 Você adicionou ${amount:,} à sua conta! Novo saldo: ${new_amount:,}."
                )
            else:
                await ctx.send("Falha ao atualizar o dinheiro no banco de dados.")
        except Exception as e:
            await ctx.send(f"Ocorreu um erro inesperado: {e}")
            print(f"[Shop][givemoney] erro: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(ShopCog(bot))
