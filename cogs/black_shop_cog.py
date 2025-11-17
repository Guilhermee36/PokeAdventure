# cogs/black_shop_cog.py
# -*- coding: utf-8 -*-

import discord
from discord.ext import commands
import os
import random
from supabase import create_client, Client

from utils.static_pokemon_utils import (
    Rarity,
    StaticPokemon,
    get_sprite_url,
    get_black_slots_pool,
    get_black_shop_basic_pool,
)

# função global de criação de Pokémon
from cogs.player_cog import add_pokemon_to_player


# -------------------------------------------------------------------
# Supabase helper
# -------------------------------------------------------------------

def get_supabase_client() -> Client:
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY")
    return create_client(url, key)

# -------------------------------------------------------------------
# Config do Cassino / Mercado Negro
# -------------------------------------------------------------------

BLACK_MARKET_MIN_BET = 1_000
BLACK_MARKET_MAX_BET = 100_000

# Preço por Pokémon aleatório (mercado negro)
BLACK_MARKET_POKEMON_PRICE = 8_000

# Pesos das raridades no caça-níquel (quanto maior, mais comum)
SLOTS_RARITY_WEIGHTS = {
    "common": 60,
    "uncommon": 25,
    "rare": 10,
    "mythical": 5,
}

# Ícones de “slot machine” por raridade
RARITY_ICONS = {
    "common": "🍒",      # cereja
    "uncommon": "🪙",    # moeda
    "rare": "💎",        # diamante
    "mythical": "7️⃣",   # número 7
}


# -------------------------------------------------------------------
# Cog
# -------------------------------------------------------------------

class BlackShopCog(commands.Cog):
    """
    Mercado negro:
      • Cassino (caça-níquel com Pokémon como símbolos)
      • Compra clandestina de Pokémon aleatórios
      • Venda de Pokémon para dinheiro
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.supabase: Client = get_supabase_client()

    # ---------------------- helpers de dinheiro ----------------------

    async def get_player_money(self, player_id: int) -> int:
        """Busca o dinheiro atual do jogador (tabela players.money)."""
        try:
            res = (
                self.supabase.table("players")
                .select("money")
                .eq("discord_id", player_id)
                .limit(1)
                .execute()
            )
            data = res.data[0] if res.data else None
            if not data:
                return 0
            return int(data.get("money", 0))
        except Exception as e:
            print(f"[BlackShop][get_player_money] erro: {e}")
            return 0

    async def update_player_money(self, player_id: int, new_amount: int) -> bool:
        try:
            self.supabase.table("players").update(
                {"money": new_amount}
            ).eq("discord_id", player_id).execute()
            return True
        except Exception as e:
            print(f"[BlackShop][update_player_money] erro: {e}")
            return False

    async def add_money(self, player_id: int, delta: int) -> int:
        """Soma delta ao dinheiro do jogador e retorna o novo saldo."""
        current = await self.get_player_money(player_id)
        new_amount = max(0, current + delta)
        await self.update_player_money(player_id, new_amount)
        return new_amount

    # ---------------------- helpers de cassino -----------------------

    def _roll_rarity(self) -> str:
        """Sorteia uma raridade (common/uncommon/rare/mythical) com base em SLOTS_RARITY_WEIGHTS."""
        rarities = list(SLOTS_RARITY_WEIGHTS.keys())
        weights = list(SLOTS_RARITY_WEIGHTS.values())
        return random.choices(rarities, weights=weights, k=1)[0]

    def _roll_slot_symbol(self) -> dict:
        """
        Retorna um dict com:
          { 'rarity', 'icon', 'pokemon_id', 'pokemon_name', 'sprite_url' }

        A raridade define o ícone:
          - common   -> 🍒
          - uncommon -> 🪙
          - rare     -> 💎
          - mythical -> 7️⃣

        MAS a checagem de vitória é por Pokémon (3 do MESMO).
        """
        rarity = self._roll_rarity()
        pool = get_black_slots_pool(rarity)
        if not pool:
            # fallback de segurança: pool básico
            pool = get_black_shop_basic_pool()

        pokemon = random.choice(pool)
        pokedex_id = pokemon["id"]
        return {
            "rarity": rarity,
            "icon": RARITY_ICONS.get(rarity, "?"),
            "pokemon_id": pokedex_id,
            "pokemon_name": pokemon["name"],
            "sprite_url": get_sprite_url(pokedex_id),
            "static_def": pokemon,
        }

    def _spin_slots(self, reels: int = 3):
        return [self._roll_slot_symbol() for _ in range(reels)]

    # ---------------------- helpers de pokémon -----------------------

    async def _maybe_boost_shiny(self, pokemon_row: dict, bet_amount: int) -> dict:
        """
        Aumenta chance de shiny dependendo do valor da aposta.

        - A lógica base de shiny (1/4096) já foi aplicada dentro de add_pokemon_to_player.
        - Aqui damos uma chance EXTRA, apenas se ainda não for shiny.

        Regra simples (ajusta se quiser):
          - aposta < 10k  -> sem bônus
          - 10k–50k       -> ~1/1024 extra
          - >= 50k        -> ~1/512 extra
        """
        if pokemon_row.get("is_shiny"):
            return pokemon_row

        if bet_amount < 10_000:
            return pokemon_row
        elif bet_amount < 50_000:
            extra_chance = 1 / 1024
        else:
            extra_chance = 1 / 512

        if random.random() < extra_chance:
            try:
                self.supabase.table("player_pokemon").update(
                    {"is_shiny": True}
                ).eq("id", pokemon_row["id"]).execute()
                pokemon_row["is_shiny"] = True
            except Exception as e:
                print(f"[BlackShop][_maybe_boost_shiny] erro ao atualizar shiny: {e}")

        return pokemon_row

    async def _grant_pokemon_to_player(
        self,
        player_id: int,
        pokemon_def: StaticPokemon,
        bet_amount: int | None = None,
    ) -> dict:
        """
        Usa add_pokemon_to_player para realmente criar o Pokémon no banco.

        pokemon_def vem do STATIC:
            { "id": <pokedex_id>, "name": "Bulbasaur", "region": 1, "api_name"?: "bulbasaur" }

        - api_name: se existir é usado direto pra PokeAPI
        - senão: name.lower() (funciona pra maioria dos casos simples)
        """
        pokedex_id = pokemon_def["id"]
        display_name = pokemon_def["name"]
        api_name = pokemon_def.get("api_name") or display_name.lower()

        # nível base do prêmio do cassino (ajusta à vontade)
        level = random.randint(5, 15)

        result = await add_pokemon_to_player(
            player_id=player_id,
            pokemon_api_name=api_name,
            level=level,
            captured_at="Cassino Mercado Negro",
            assign_to_party_if_space=True,
        )
        if not result.get("success"):
            return {
                "success": False,
                "error": result.get("error", "Erro desconhecido ao criar Pokémon."),
            }

        row = result["data"]

        # bônus de shiny com base na aposta (se houver)
        if bet_amount is not None:
            row = await self._maybe_boost_shiny(row, bet_amount)

        is_shiny = row.get("is_shiny", False)
        nickname = row.get("nickname") or display_name
        level_final = row.get("current_level", level)
        sprite_url = get_sprite_url(row.get("pokemon_pokedex_id", pokedex_id))

        return {
            "success": True,
            "species_name": display_name,
            "level": level_final,
            "nickname": nickname,
            "sprite_url": sprite_url,
            "is_shiny": is_shiny,
        }

    # ----------------------------------------------------------------
    # Comandos
    # ----------------------------------------------------------------

    @commands.command(
        name="blackshop",
        help="Mostra o menu do Mercado Negro (cassino e pokémons clandestinos).",
    )
    async def blackshop(self, ctx: commands.Context):
        embed = discord.Embed(
            title="🖤 Mercado Negro Pokémon 🖤",
            description=(
                "Bem-vindo ao lado sombrio do mundo Pokémon...\n\n"
                "**Cassino**\n"
                "• `!blackslots <aposta>` – caça-níquel com pokémons como símbolos.\n"
                "   - Cada slot mostra um Pokémon + ícone (🍒, 🪙, 💎, 7️⃣)\n"
                "   - Se alinhar **3 do MESMO Pokémon**, você recebe o dinheiro de volta e ainda ganha esse Pokémon.\n"
                "   - Apostas maiores aumentam a chance de vir **shiny**.\n\n"
                "**Tráfico de Pokémon**\n"
                "• `!blackbuy [quantidade]` – compra pokémons aleatórios de 1º estágio\n"
                "   (sem lendários / míticos).\n"
                "• `!blacksell <pokemon_uuid>` – vende um dos seus pokémons pro mercado negro.\n"
            ),
            color=discord.Color.dark_purple(),
        )
        embed.set_footer(text="Use por sua conta e risco. A Liga não precisa saber disso. 😏")
        await ctx.send(embed=embed)

    # --------------------------- CASSINO -----------------------------

    @commands.command(
        name="blackslots",
        help=(
            "Cassino clandestino: caça-níquel com pokémons. "
            "Uso: !blackslots <aposta>"
        ),
    )
    async def blackslots(self, ctx: commands.Context, bet: int):
        """
        Nova lógica:
          - 3 slots, cada um sorteia um Pokémon (com raridades diferentes).
          - Você perde a aposta normalmente.
          - SE os 3 forem o MESMO Pokémon:
              • recebe o dinheiro de volta (sem lucro)
              • ganha aquele Pokémon (com chance extra de shiny conforme o valor apostado).
        """
        if bet <= 0:
            await ctx.send("A aposta precisa ser um número positivo.")
            return
        if bet < BLACK_MARKET_MIN_BET:
            await ctx.send(
                f"A aposta mínima no mercado negro é **${BLACK_MARKET_MIN_BET:,}**."
            )
            return
        if bet > BLACK_MARKET_MAX_BET:
            await ctx.send(
                f"A aposta máxima é **${BLACK_MARKET_MAX_BET:,}** por rodada."
            )
            return

        current_money = await self.get_player_money(ctx.author.id)
        if current_money < bet:
            await ctx.send(
                f"Você não tem dinheiro suficiente. Saldo atual: **${current_money:,}**."
            )
            return

        # Debita imediatamente a aposta
        new_money = current_money - bet
        if not await self.update_player_money(ctx.author.id, new_money):
            await ctx.send("Erro ao processar a aposta. Tente novamente.")
            return

        # Roda o caça-níquel
        slots = self._spin_slots(3)
        pokemon_ids = [s["pokemon_id"] for s in slots]
        icons = [s["icon"] for s in slots]

        three_of_a_kind = (
            pokemon_ids[0] == pokemon_ids[1] == pokemon_ids[2]
        )

        # Monta a linha visual: ícone + nome do Pokémon
        line_symbols = " | ".join(
            f"{icons[i]} **{slots[i]['pokemon_name']}**"
            for i in range(3)
        )

        embed = discord.Embed(
            title="🎰 Cassino do Mercado Negro",
            color=discord.Color.dark_gold(),
        )

        embed.add_field(
            name="Roleta",
            value=f"⇒ {line_symbols}",
            inline=False,
        )

        # Mostra sprite do meio na imagem do embed
        center_sprite = slots[1]["sprite_url"]
        embed.set_thumbnail(url=center_sprite)

        if not three_of_a_kind:
            # perdeu a aposta
            embed.add_field(
                name="Resultado",
                value=f"💀 Nada alinhado... você perdeu **${bet:,}**.",
                inline=False,
            )
            embed.add_field(
                name="Seu saldo após a rodada",
                value=f"**${new_money:,}**",
                inline=False,
            )
            embed.set_footer(text="A casa sempre ganha... eventualmente. 😉")
            await ctx.send(embed=embed)
            return

        # VENCEU: 3 do MESMO Pokémon
        winning_static = slots[0]["static_def"]
        winning_name = winning_static["name"]

        # Dinheiro de volta (sem lucro)
        new_money += bet
        await self.update_player_money(ctx.author.id, new_money)

        # Cria o Pokémon pro jogador
        reward = await self._grant_pokemon_to_player(
            player_id=ctx.author.id,
            pokemon_def=winning_static,
            bet_amount=bet,
        )

        if not reward.get("success"):
            embed.add_field(
                name="Resultado",
                value=(
                    f"⚠️ Você alinhou **3x {winning_name}**, então deveria receber o Pokémon "
                    f"e o dinheiro de volta, mas ocorreu um erro ao criar o Pokémon:\n"
                    f"`{reward.get('error', 'erro desconhecido')}`"
                ),
                inline=False,
            )
        else:
            shiny_text = " ✨ **SHINY!!!** ✨" if reward.get("is_shiny") else ""
            embed.add_field(
                name="Resultado",
                value=(
                    f"🎉 **JACKPOT!**\n"
                    f"Você alinhou **3x {winning_name}**.\n"
                    f"• Aposta devolvida: **${bet:,}**\n"
                    f"• Pokémon recebido: Lv.{reward['level']} "
                    f"**{reward['nickname']}** (*{reward['species_name']}*){shiny_text}"
                ),
                inline=False,
            )
            if reward.get("sprite_url"):
                embed.set_thumbnail(url=reward["sprite_url"])

        embed.add_field(
            name="Seu saldo após a rodada",
            value=f"**${new_money:,}**",
            inline=False,
        )

        embed.set_footer(text="Quanto mais alto o risco, maior a chance de brilhar... literalmente. 😉")
        await ctx.send(embed=embed)

    # -------------------- COMPRA CLANDESTINA ------------------------

    @commands.command(
        name="blackbuy",
        help=(
            "Compra pokémons aleatórios de 1º estágio (sem lendários/míticos). "
            f"Uso: !blackbuy [quantidade] – preço: ${BLACK_MARKET_POKEMON_PRICE:,} cada."
        ),
    )
    async def blackbuy(self, ctx: commands.Context, quantity: int = 1):
        if quantity <= 0:
            await ctx.send("A quantidade deve ser um número positivo.")
            return

        total_price = BLACK_MARKET_POKEMON_PRICE * quantity
        current_money = await self.get_player_money(ctx.author.id)

        if current_money < total_price:
            await ctx.send(
                f"Você não tem dinheiro suficiente.\n"
                f"• Saldo atual: **${current_money:,}**\n"
                f"• Preço por Pokémon: **${BLACK_MARKET_POKEMON_PRICE:,}**\n"
                f"• Quantidade: **{quantity}**\n"
                f"• Total necessário: **${total_price:,}**"
            )
            return

        # Debita
        new_money = current_money - total_price
        if not await self.update_player_money(ctx.author.id, new_money):
            await ctx.send("Erro ao processar a compra. Tente novamente.")
            return

        # Escolhe pokémons aleatórios do pool básico
        bought_pokemon = []
        for _ in range(quantity):
            base_def = random.choice(get_black_shop_basic_pool())
            reward = await self._grant_pokemon_to_player(
                player_id=ctx.author.id,
                pokemon_def=base_def,
                bet_amount=None,  # sem bônus extra de shiny aqui (se quiser, coloca um valor)
            )
            bought_pokemon.append(reward)

        # Monta embed de feedback
        embed = discord.Embed(
            title="🖤 Compra Clandestina Concluída",
            description=(
                f"Você pagou **${total_price:,}** ao mercado negro.\n"
                "Pokémons recebidos:"
            ),
            color=discord.Color.dark_purple(),
        )

        for idx, pkm in enumerate(bought_pokemon, start=1):
            if not pkm.get("success"):
                embed.add_field(
                    name=f"#{idx}",
                    value=f"❌ Erro ao criar Pokémon: {pkm.get('error', 'desconhecido')}",
                    inline=False,
                )
                continue

            species = pkm.get("species_name", "???")
            level = pkm.get("level", "?")
            nick = pkm.get("nickname", species)
            shiny_text = " ✨(shiny)" if pkm.get("is_shiny") else ""
            line = f"Lv.{level} **{nick}** (*{species}*){shiny_text}"
            embed.add_field(
                name=f"#{idx}",
                value=line,
                inline=False,
            )

        # Usa sprite do primeiro como thumbnail, se tiver
        first_ok = next((p for p in bought_pokemon if p.get("success") and p.get("sprite_url")), None)
        if first_ok:
            embed.set_thumbnail(url=first_ok["sprite_url"])

        embed.add_field(
            name="Seu novo saldo",
            value=f"**${new_money:,}**",
            inline=False,
        )

        await ctx.send(embed=embed)

    # ------------------------- VENDA -------------------------------

    @commands.command(
        name="blacksell",
        help="Vende um dos seus pokémons para o mercado negro. Uso: !blacksell <pokemon_uuid>",
    )
    async def blacksell(self, ctx: commands.Context, pokemon_id: str):
        """
        Vende um Pokémon da tabela player_pokemon.

        Schema:
          - id (uuid)           -> parametro pokemon_id
          - player_id (bigint)  -> ctx.author.id
          - current_level (int) -> usado para calcular o valor
        """
        try:
            res = (
                self.supabase.table("player_pokemon")
                .select("*")
                .eq("id", pokemon_id)
                .eq("player_id", ctx.author.id)
                .limit(1)
                .execute()
            )
            data = res.data[0] if res.data else None
        except Exception as e:
            print(f"[BlackShop][blacksell] erro ao buscar pokemon: {e}")
            await ctx.send("Erro ao acessar seus pokémons no banco de dados.")
            return

        if not data:
            await ctx.send(
                f"Não encontrei nenhum Pokémon com ID `{pokemon_id}` pertencente a você."
            )
            return

        # Usa nível atual para precificação
        level = int(data.get("current_level", 5))

        # Base de valor por nível (ajusta se quiser)
        base_per_level = 500
        price = base_per_level * max(1, level)

        # Apaga o Pokémon do jogador
        try:
            self.supabase.table("player_pokemon").delete().eq(
                "id", pokemon_id
            ).eq("player_id", ctx.author.id).execute()
        except Exception as e:
            print(f"[BlackShop][blacksell] erro ao deletar pokemon: {e}")
            await ctx.send("Erro ao remover o Pokémon do banco. Venda cancelada.")
            return

        # Dá o dinheiro
        new_money = await self.add_money(ctx.author.id, price)

        species_name = (
            data.get("nickname")
            or data.get("pokemon_api_name")
            or "Pokémon"
        )

        embed = discord.Embed(
            title="💸 Venda Clandestina",
            description=(
                f"Você vendeu **{species_name}** para alguns sujeitos suspeitos no beco...\n"
                f"Recebeu **${price:,}** em dinheiro vivo."
            ),
            color=discord.Color.dark_teal(),
        )
        embed.add_field(
            name="Seu novo saldo",
            value=f"**${new_money:,}**",
            inline=False,
        )
        embed.set_footer(text="Não conte isso para o Professor Oak.")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(BlackShopCog(bot))
