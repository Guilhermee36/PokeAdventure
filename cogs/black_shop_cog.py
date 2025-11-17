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

# Multiplicadores por raridade no caça-níquel:
SLOTS_PAYOUT_MULTIPLIERS = {
    "common": 2,      # 3 comuns  => aposta x2
    "uncommon": 5,    # 3 incomuns => aposta x5
    "rare": 10,       # 3 raros   => aposta x10
    "mythical": 20,   # 3 míticos => aposta x20
}

# Pesos das raridades no caça-níquel (quanto maior, mais comum)
SLOTS_RARITY_WEIGHTS = {
    "common": 60,
    "uncommon": 25,
    "rare": 10,
    "mythical": 5,
}

# Ícones de “slot machine” por raridade
RARITY_ICONS = {
    "common": "🍒",      # equivalente à cereja
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
        """
        rarity = self._roll_rarity()
        pool = get_black_slots_pool(rarity)
        if not pool:
            # fallback de segurança
            pool = get_black_shop_basic_pool()

        pokemon = random.choice(pool)
        pokedex_id = pokemon["id"]
        return {
            "rarity": rarity,
            "icon": RARITY_ICONS.get(rarity, "?"),
            "pokemon_id": pokedex_id,
            "pokemon_name": pokemon["name"],
            "sprite_url": get_sprite_url(pokedex_id),
        }

    def _spin_slots(self, reels: int = 3):
        return [self._roll_slot_symbol() for _ in range(reels)]

    # ---------------------- helpers de pokémon -----------------------

    async def _grant_pokemon_to_player(self, player_id: int, pokemon_def: StaticPokemon) -> dict:
        """
        HOOK para integrar com seu sistema de criação de Pokémon.

        Schema real (tabela player_pokemon):
          - id (uuid, PK)
          - player_id (bigint -> players.discord_id)
          - pokemon_api_name (text)
          - pokemon_pokedex_id (integer)
          - current_level (integer)
          - current_hp (integer, NOT NULL)
          - ... outros stats

        pokemon_def vem do BASIC_BLACK_MARKET_POOL:
            { "id": <pokedex_id>, "name": "Bulbasaur", "region": 1 }

        Aqui você deveria chamar o seu service de criação que popula:
          - current_hp
          - stats
          - moves
          - etc.

        Retorne um dict com infos para mostrar no embed, por exemplo:
            {
                "species_name": "Bulbasaur",
                "level": 5,
                "nickname": "Bulbasaur",
                "sprite_url": <url>,
                "pokemon_pokedex_id": 1,
                "pokemon_api_name": "bulbasaur"
            }

        ⚠️ Por padrão, essa implementação **NÃO SALVA NADA** no banco,
        apenas devolve um dict “fake” para exibir na mensagem.
        """

        pokedex_id = pokemon_def["id"]
        species_name = pokemon_def["name"]

        # TODO: Trocar essa parte para o SEU service de criação.
        # Exemplo:
        # created = await pokemon_service.create_random_basic(
        #     player_id=player_id,
        #     pokemon_pokedex_id=pokedex_id,
        #     pokemon_api_name=species_name.lower(),
        # )
        # return {
        #     "species_name": created["pokemon_species_name"],
        #     "level": created["current_level"],
        #     "nickname": created["nickname"],
        #     "sprite_url": created["sprite_url"],
        #     "pokemon_pokedex_id": created["pokemon_pokedex_id"],
        #     "pokemon_api_name": created["pokemon_api_name"],
        # }

        # Implementação de placeholder (não persiste):
        fake_level = random.randint(5, 10)

        return {
            "species_name": species_name,
            "level": fake_level,
            "nickname": species_name,
            "sprite_url": get_sprite_url(pokedex_id),
            "pokemon_pokedex_id": pokedex_id,
            "pokemon_api_name": species_name.lower(),
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
                "   - 4 raridades (🍒 comum, 🪙 incomum, 💎 raro, 7️⃣ mítico)\n"
                "   - 3 iguais = prêmio, multiplicador por raridade.\n\n"
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
        help="Cassino clandestino: caça-níquel com pokémons. Uso: !blackslots <aposta>",
    )
    async def blackslots(self, ctx: commands.Context, bet: int):
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
        rarities = [s["rarity"] for s in slots]
        icons = [s["icon"] for s in slots]

        # Determina se ganhou
        won = rarities[0] == rarities[1] == rarities[2]
        payout = 0
        rarity_label = None

        if won:
            rarity = rarities[0]
            rarity_label = rarity
            multiplier = SLOTS_PAYOUT_MULTIPLIERS.get(rarity, 0)
            payout = bet * multiplier
            new_money = new_money + payout
            await self.update_player_money(ctx.author.id, new_money)

        # Monta a mensagem visual
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

        if won:
            label_pt = {
                "common": "Comum (🍒)",
                "uncommon": "Incomum (🪙)",
                "rare": "Raro (💎)",
                "mythical": "Mítico (7️⃣)",
            }.get(rarity_label, rarity_label)

            embed.add_field(
                name="Resultado",
                value=(
                    f"🎉 **3 de mesma raridade!**\n"
                    f"Raridade: **{label_pt}**\n"
                    f"Multiplicador: **x{SLOTS_PAYOUT_MULTIPLIERS[rarity_label]}**\n"
                    f"Você ganhou **${payout:,}**!"
                ),
                inline=False,
            )
        else:
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
            granted = await self._grant_pokemon_to_player(ctx.author.id, base_def)
            bought_pokemon.append(granted)

        # Monta embed de feedback
        embed = discord.Embed(
            title="🖤 Compra Clandestina Concluída",
            description=(
                f"Você pagou **${total_price:,}** ao mercado negro.\n"
                "Pokémons recebidos (teoricamente 😏):"
            ),
            color=discord.Color.dark_purple(),
        )

        for idx, pkm in enumerate(bought_pokemon, start=1):
            species = pkm.get("species_name", "???")
            level = pkm.get("level", "?")
            nick = pkm.get("nickname", species)
            line = f"Lv.{level} **{nick}** (*{species}*)"
            embed.add_field(
                name=f"#{idx}",
                value=line,
                inline=False,
            )

        # Usa sprite do primeiro como thumbnail, se tiver
        if bought_pokemon and bought_pokemon[0].get("sprite_url"):
            embed.set_thumbnail(url=bought_pokemon[0]["sprite_url"])

        embed.add_field(
            name="Seu novo saldo",
            value=f"**${new_money:,}**",
            inline=False,
        )

        embed.set_footer(
            text=(
                "⚠️ IMPORTANTE: Integre o método _grant_pokemon_to_player "
                "com seu sistema de criação para realmente salvar esses pokémons no banco."
            )
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
