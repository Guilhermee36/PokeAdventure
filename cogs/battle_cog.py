# cogs/battle_cog.py
# -*- coding: utf-8 -*-

from __future__ import annotations
import os
import math
import asyncio
import discord
from discord.ext import commands
from typing import Optional, Tuple

from supabase import create_client, Client

# usamos seu serviço pokeapi (já no projeto)
import utils.pokeapi_service as pokeapi  # get_pokemon_data, get_pokemon_species_data, get_total_xp_for_level, calculate_stats_for_level

# ======================================================================================
# Supabase helper (mesmo padrão do player_cog)
# ======================================================================================

def get_supabase_client() -> Client:
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY")
    return create_client(url, key)  # igual ao PlayerCog, mantém consistência
# (mesmo modelo usado no PlayerCog)  # ref: :contentReference[oaicite:1]{index=1}

# ======================================================================================
# Regras simples do "teste de batalha"
# ======================================================================================

# Oponente padrão do modo teste (para XP base simples via PokeAPI)
TEST_OPPONENT_NAME = "pidgey"   # base_experience ~ 50 (valor típico)
HAPPINESS_GAIN_ON_WIN = 2
HAPPINESS_CAP = 255
LEVEL_CAP = 100

async def compute_reward_xp(player_level: int) -> int:
    """
    Fórmula simples inspirada no ganho de XP em lutas contra selvagem:
        xp = floor( (base_exp_oponente * level_oponente) / 7 )
    Oponente de teste tem mesmo level do seu Pokémon.
    """
    opp = await pokeapi.get_pokemon_data(TEST_OPPONENT_NAME)  # base_experience
    base_exp = (opp or {}).get("base_experience", 50) or 50
    return max(1, math.floor((base_exp * max(1, int(player_level))) / 7))

async def total_xp_for_level(species_growth_url: str, level: int) -> int:
    # usa exatamente sua função utilitária para compatibilidade com XP absoluto do BD
    # (o seu schema guarda "current_xp" como XP TOTAL acumulado até o level)  # ref: sprigatito lvl5 xp=135
    # :contentReference[oaicite:2]{index=2}
    return int(await pokeapi.get_total_xp_for_level(species_growth_url, int(level)) or 0)

async def apply_level_ups_if_any(poke_row: dict, species_growth_url: str, new_total_xp: int) -> Tuple[int, dict, int]:
    """
    Checa se o XP total passou o limiar do próximo nível e sobe múltiplos níveis se for o caso.
    Retorna: (novo_level, novos_stats, delta_max_hp)
    """
    current_level = int(poke_row["current_level"])
    if current_level >= LEVEL_CAP:
        return LEVEL_CAP, {}, 0

    # Loop de level up com CAP em 100
    target_level = current_level
    while target_level < LEVEL_CAP:
        next_level = target_level + 1
        need_total_for_next = await total_xp_for_level(species_growth_url, next_level)
        if need_total_for_next == float("inf") or need_total_for_next <= 0:
            break
        if new_total_xp >= need_total_for_next:
            target_level = next_level
        else:
            break

    if target_level == current_level:
        return current_level, {}, 0

    # Recalcula stats para o novo nível (mesma função do seu add_pokemon)
    # :contentReference[oaicite:3]{index=3}
    pkmn_data = await pokeapi.get_pokemon_data(poke_row["pokemon_api_name"])
    base_stats = (pkmn_data or {}).get("stats", [])
    new_stats = pokeapi.calculate_stats_for_level(base_stats, target_level)
    delta_hp = int(new_stats.get("max_hp", poke_row["max_hp"])) - int(poke_row["max_hp"])
    return target_level, new_stats, max(0, delta_hp)

# ======================================================================================
# Cog
# ======================================================================================

class BattleCog(commands.Cog):
    """
    !battle  -> batalha de teste
    - pega o 1º Pokémon da party do jogador
    - simula vitória
    - concede XP (com possível level-up) +2 happiness
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.supabase = get_supabase_client()

    # ----------------- helpers de BD -----------------

    def _get_active_party_mon(self, player_id: int) -> Optional[dict]:
        """
        Busca o primeiro Pokémon da party (menor party_position) do jogador.
        Compatível com colunas do seu schema player_pokemon.  # :contentReference[oaicite:4]{index=4}
        """
        try:
            res = (
                self.supabase.table("player_pokemon")
                .select("*")
                .eq("player_id", player_id)
                .not_.is_("party_position", "null")
                .order("party_position", desc=False)
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            print(f"[BattleCog] erro ao buscar party: {e}", flush=True)
            return None

    # ----------------- comando principal -----------------

    @commands.command(name="battle")
    async def battle_test(self, ctx: commands.Context):
        """
        Batalha de teste (vitória garantida):
        - Ganha XP calculado e +2 de happiness.
        - Aplica level-up real pela growth-rate da espécie.
        """
        player_id = ctx.author.id
        poke_row = self._get_active_party_mon(player_id)
        if not poke_row:
            return await ctx.send("Você não tem Pokémon na party. Capture ou adicione um para lutar!")

        nickname = poke_row.get("nickname") or poke_row.get("pokemon_api_name", "Pokémon").capitalize()
        level = int(poke_row.get("current_level") or 1)
        current_xp = int(poke_row.get("current_xp") or 0)
        current_hp = int(poke_row.get("current_hp") or 1)
        max_hp = int(poke_row.get("max_hp") or 1)
        happiness = int(poke_row.get("happiness") or 0)

        # Dados da espécie do SEU Pokémon para growth_rate
        species = await pokeapi.get_pokemon_species_data(poke_row["pokemon_api_name"])
        if not species or "growth_rate" not in species:
            return await ctx.send("Não consegui obter os dados de espécie para calcular XP. Tente novamente.")

        growth_url = species["growth_rate"]["url"]

        # 1) Ganho de XP conforme level (oponente de teste usa base_exp do Pidgey)
        reward_xp = await compute_reward_xp(level)

        # 2) Novo XP total
        new_total_xp = current_xp + reward_xp

        # 3) Level ups (pode subir vários níveis)
        new_level, new_stats, delta_hp = await apply_level_ups_if_any(poke_row, growth_url, new_total_xp)

        # 4) Happiness
        new_happiness = min(HAPPINESS_CAP, happiness + HAPPINESS_GAIN_ON_WIN)

        # 5) HP atual ao subir de nível: aumenta pela diferença do max_hp (sem ultrapassar o novo máximo)
        if new_stats:
            new_max_hp = int(new_stats.get("max_hp", max_hp))
            new_current_hp = min(new_max_hp, current_hp + max(0, delta_hp))
        else:
            new_max_hp = max_hp
            new_current_hp = current_hp

        # 6) Monta payload de update
        update_payload = {
            "current_xp": new_total_xp,
            "happiness": new_happiness,
            "current_level": new_level,
            "current_hp": new_current_hp,
        }

        # se houver level up, persistir todos os stats recalculados
        if new_stats:
            update_payload.update({
                "max_hp": new_stats.get("max_hp", new_max_hp),
                "attack": new_stats.get("attack", poke_row["attack"]),
                "defense": new_stats.get("defense", poke_row["defense"]),
                "special_attack": new_stats.get("special_attack", poke_row["special_attack"]),
                "special_defense": new_stats.get("special_defense", poke_row["special_defense"]),
                "speed": new_stats.get("speed", poke_row["speed"]),
            })

        # 7) Persiste no BD
        try:
            (
                self.supabase.table("player_pokemon")
                .update(update_payload)
                .eq("id", poke_row["id"])
                .execute()
            )
        except Exception as e:
            return await ctx.send(f"Falha ao salvar progresso da batalha: `{e}`")

        # 8) Feedback visual
        lvl_up_text = ""
        if new_level > level:
            lvl_up_text = f"\n\u2197\uFE0F **Level up!** {level} → **{new_level}** (+{HAPPINESS_GAIN_ON_WIN} happiness)."
        else:
            lvl_up_text = f"\nGanhou +{HAPPINESS_GAIN_ON_WIN} happiness."

        embed = discord.Embed(
            title=f"⚔️ Batalha de Teste — Vitória!",
            description=(
                f"**{nickname}** (Lv. {level}) venceu o oponente de treino.\n"
                f"+ **{reward_xp} XP** aplicados.{lvl_up_text}"
            ),
            color=discord.Color.green(),
        )
        embed.add_field(name="XP total", value=f"{current_xp} → **{new_total_xp}**", inline=True)
        embed.add_field(name="Happiness", value=f"{happiness} → **{new_happiness}**", inline=True)
        if new_level > level:
            # mostra stats novos resumidos (se houve level up)
            s = update_payload if new_stats else poke_row
            embed.add_field(
                name="Stats (novo nível)",
                value=f"HP {new_current_hp}/{update_payload.get('max_hp', new_max_hp)} · "
                      f"ATK {s.get('attack')} · DEF {s.get('defense')} · "
                      f"SPA {s.get('special_attack')} · SPD {s.get('special_defense')} · SPE {s.get('speed')}",
                inline=False
            )

        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(BattleCog(bot))
