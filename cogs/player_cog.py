# cogs/player_cog.py

import os
import random
import asyncio
import discord
from discord.ext import commands
from discord import ui
from typing import Optional

from supabase import create_client, Client

# Utils do projeto (mantidos)
import utils.pokeapi_service as pokeapi
import utils.evolution_utils as evolution_utils  # (mantido para futuras evoluções)

# ===============================================
# Supabase helper
# ===============================================

def get_supabase_client() -> Client:
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY")
    return create_client(url, key)

# Helper de busca segura (evita .single() -> PGRST116)
def supabase_fetch_one(supabase: Client, table: str, **filters) -> dict | None:
    try:
        q = supabase.table(table).select("*")
        for k, v in filters.items():
            q = q.eq(k, v)
        res = q.limit(1).execute()
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as e:
        print(f"[player_cog] fetch_one erro ({table}, {filters}): {e}")
        return None

# ===============================================
# Spawn por região (mantido + ajustado)
# ===============================================

REGION_SPAWNS: dict[str, str] = {
    "Kanto": "pallet-town",
    "Johto": "new-bark-town",
    "Hoenn": "littleroot-town",
    "Sinnoh": "twinleaf-town",
    "Unova": "nuvema-town",
    "Kalos": "vaniville-town",
    "Alola": "iki-town",           # << ajustado para Iki (combina com seu DB)
    "Galar": "postwick",
    "Paldea": "cabo-poco",
}

def _spawn_for_region(region: str) -> str:
    return REGION_SPAWNS.get(region, "pallet-town")

VALID_REGIONS = list(REGION_SPAWNS.keys())

# ===============================================
# Funções utilitárias do jogador / Pokémon (mantidas)
# ===============================================

async def add_pokemon_to_player(
    player_id: int,
    pokemon_api_name: str,
    level: int = 5,
    captured_at: str = "Início da Jornada",
) -> dict:
    """
    Lógica mantida: adiciona Pokémon ao jogador, respeitando party (<=6),
    shiny roll 1/4096, stats calculados, moves iniciais e gênero.
    """
    supabase = get_supabase_client()

    # Quantos Pokémon já estão na party (1-6)?
    try:
        count_response = (
            supabase.table("player_pokemon")
            .select("id", count="exact")
            .eq("player_id", player_id)
            .filter("party_position", "not.is", "null")
            .execute()
        )
        pokemon_count_in_party = count_response.count
    except Exception as e:
        return {"success": False, "error": f"Erro ao contar Pokémon: {e}"}

    party_position = None
    is_going_to_box = True
    if pokemon_count_in_party < 6:
        party_position = pokemon_count_in_party + 1
        is_going_to_box = False

    poke_data = await pokeapi.get_pokemon_data(pokemon_api_name)
    if not poke_data:
        return {"success": False, "error": f"Pokémon '{pokemon_api_name}' não encontrado na API."}

    is_shiny = random.randint(1, 4096) == 1
    calculated_stats = pokeapi.calculate_stats_for_level(poke_data["stats"], level)
    initial_moves = pokeapi.get_initial_moves(poke_data, level)

    # Gênero e XP inicial (mantido)
    gender_ratio = -1
    starting_xp = 0

    base_species_name = poke_data.get("species", {}).get("name") or pokemon_api_name
    species_data = await pokeapi.get_pokemon_species_data(base_species_name)

    if species_data:
        gender_ratio = species_data.get("gender_rate", -1)
        if "growth_rate" in species_data and level > 1:
            growth_rate_url = species_data["growth_rate"]["url"]
            xp_for_level = await pokeapi.get_total_xp_for_level(growth_rate_url, level)
            if xp_for_level != float("inf"):
                starting_xp = xp_for_level

    gender = "genderless"
    if gender_ratio != -1:
        gender = "female" if random.randint(1, 8) <= gender_ratio else "male"

    new_pokemon_data = {
        "player_id": player_id,
        "pokemon_api_name": pokemon_api_name,
        "pokemon_pokedex_id": poke_data["id"],
        "nickname": pokemon_api_name.capitalize(),
        "captured_at_location": captured_at,
        "is_shiny": is_shiny,
        "party_position": party_position,
        "current_level": level,
        "current_hp": calculated_stats["max_hp"],
        "current_xp": starting_xp,
        "moves": initial_moves,
        "gender": gender,
        "happiness": 70,
        **calculated_stats,
    }

    try:
        insert_response = supabase.table("player_pokemon").insert(new_pokemon_data).execute()
        if insert_response.data:
            if is_going_to_box:
                success_message = "Pokémon adicionado com sucesso e enviado para a Box (seu time está cheio)!"
            else:
                success_message = f"Pokémon adicionado com sucesso na posição {party_position}!"
            return {"success": True, "message": success_message, "data": insert_response.data[0]}
        else:
            return {"success": False, "error": "Falha ao inserir o Pokémon no banco de dados."}
    except Exception as e:
        return {"success": False, "error": f"Erro no banco de dados: {e}"}

# ===============================================
# UI / Fluxo de criação (mantido e consolidado)
# ===============================================

class StartJourneyView(ui.View):
    def __init__(self, supabase_client: Client):
        super().__init__(timeout=None)
        self.supabase = supabase_client

    @ui.button(label="Iniciar Jornada", style=discord.ButtonStyle.success, emoji="🎉")
    async def begin(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(TrainerNameModal(supabase_client=self.supabase))


class TrainerNameModal(ui.Modal, title="Crie seu Personagem"):
    def __init__(self, supabase_client: Client):
        super().__init__(timeout=300)
        self.supabase = supabase_client

    trainer_name_input = ui.TextInput(
        label="Qual será seu nome de treinador?",
        placeholder="Ex: Ash Ketchum",
        required=True,
        max_length=50,
    )

    async def on_submit(self, interaction: discord.Interaction):
        trainer_name = self.trainer_name_input.value
        embed = discord.Embed(
            title="Escolha sua Região Inicial",
            description=f"Ótimo nome, **{trainer_name}**! Agora, escolha a região onde sua aventura vai começar.",
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(
            embed=embed,
            view=RegionSelectView(trainer_name=trainer_name, supabase_client=self.supabase),
            ephemeral=True,
        )


class StarterSelectView(ui.View):
    def __init__(self, region: str):
        super().__init__(timeout=180)
        self.region = region
        self._starters_by_region: dict[str, list[str]] = {
            "Kanto": ["bulbasaur", "charmander", "squirtle"],
            "Johto": ["chikorita", "cyndaquil", "totodile"],
            "Hoenn": ["treecko", "torchic", "mudkip"],
            "Sinnoh": ["turtwig", "chimchar", "piplup"],
            "Unova": ["snivy", "tepig", "oshawott"],
            "Kalos": ["chespin", "fennekin", "froakie"],
            "Alola": ["rowlet", "litten", "popplio"],
            "Galar": ["grookey", "scorbunny", "sobble"],
            "Paldea": ["sprigatito", "fuecoco", "quaxly"],
        }

        for starter in self._starters_by_region.get(self.region, []):
            button = ui.Button(
                label=starter.capitalize(),
                style=discord.ButtonStyle.primary,
                custom_id=starter,
            )
            button.callback = self.select_starter
            self.add_item(button)

    async def select_starter(self, interaction: discord.Interaction):
        starter_name = interaction.data["custom_id"]

        # trava visual
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        result = await add_pokemon_to_player(
            player_id=interaction.user.id,
            pokemon_api_name=starter_name,
            level=5,
            captured_at=f"Recebido em {self.region}",
        )

        if result["success"]:
            pokemon_data = result["data"]
            is_shiny = pokemon_data.get("is_shiny", False)
            shiny_text = "\n\n✨ **UAU, ELE É SHINY! QUE SORTE!** ✨" if is_shiny else ""

            public_embed = discord.Embed(
                title="Uma Nova Jornada Começa!",
                description=f"{interaction.user.mention} iniciou sua aventura e escolheu **{starter_name.capitalize()}** como seu primeiro parceiro!{shiny_text}",
                color=discord.Color.green(),
            )

            # thumbnail do Pokémon (mantido)
            poke_api_data = await pokeapi.get_pokemon_data(starter_name)
            if poke_api_data:
                sprite_url = (
                    poke_api_data["sprites"]["other"]["official-artwork"]["front_shiny"]
                    if is_shiny
                    else poke_api_data["sprites"]["other"]["official-artwork"]["front_default"]
                )
                if not sprite_url:
                    sprite_url = (
                        poke_api_data["sprites"]["front_shiny"]
                        if is_shiny
                        else poke_api_data["sprites"]["front_default"]
                    )
                if sprite_url:
                    public_embed.set_thumbnail(url=sprite_url)

            await interaction.followup.send(embed=public_embed)
        else:
            await interaction.followup.send(
                f"Ocorreu um erro ao adicionar seu Pokémon: {result['error']}", ephemeral=True
            )
        self.stop()


class RegionSelectView(ui.View):
    """
    Seleção de região com gravação do spawn correto (mantido e corrigido).
    """
    def __init__(self, trainer_name: str, supabase_client: Client):
        super().__init__(timeout=180)
        self.trainer_name = trainer_name
        self.supabase = supabase_client

    async def select_region(self, interaction: discord.Interaction, region: str):
        # trava visual
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        discord_id = interaction.user.id

        # Monta os dados do player + spawn correto da região
        player_data = {
            "discord_id": discord_id,
            "trainer_name": self.trainer_name,
            "current_region": region,
            "current_location_name": _spawn_for_region(region),
        }

        try:
            existing = (
                self.supabase.table("players")
                .select("discord_id")
                .eq("discord_id", discord_id)
                .limit(1)
                .execute()
            )
            if not (existing.data or []):
                self.supabase.table("players").insert(player_data).execute()
            else:
                self.supabase.table("players").update(player_data).eq("discord_id", discord_id).execute()

            starter_embed = discord.Embed(
                title=f"Bem-vindo(a) a {region}!",
                description="Agora, a escolha mais importante: quem será seu parceiro inicial?",
                color=discord.Color.blue(),
            )
            await interaction.followup.send(
                embed=starter_embed,
                view=StarterSelectView(region=region),
                ephemeral=True,
            )

        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro ao salvar seus dados: {e}", ephemeral=True)

        self.stop()

    # Botões de região (mantidos)
    @ui.button(label="Kanto", style=discord.ButtonStyle.primary, emoji="1️⃣", row=0)
    async def kanto(self, interaction: discord.Interaction, button: ui.Button):
        await self.select_region(interaction, "Kanto")

    @ui.button(label="Johto", style=discord.ButtonStyle.primary, emoji="2️⃣", row=0)
    async def johto(self, interaction: discord.Interaction, button: ui.Button):
        await self.select_region(interaction, "Johto")

    @ui.button(label="Hoenn", style=discord.ButtonStyle.primary, emoji="3️⃣", row=0)
    async def hoenn(self, interaction: discord.Interaction, button: ui.Button):
        await self.select_region(interaction, "Hoenn")

    @ui.button(label="Sinnoh", style=discord.ButtonStyle.primary, emoji="4️⃣", row=1)
    async def sinnoh(self, interaction: discord.Interaction, button: ui.Button):
        await self.select_region(interaction, "Sinnoh")

    @ui.button(label="Unova", style=discord.ButtonStyle.primary, emoji="5️⃣", row=1)
    async def unova(self, interaction: discord.Interaction, button: ui.Button):
        await self.select_region(interaction, "Unova")

    @ui.button(label="Kalos", style=discord.ButtonStyle.primary, emoji="6️⃣", row=1)
    async def kalos(self, interaction: discord.Interaction, button: ui.Button):
        await self.select_region(interaction, "Kalos")

    @ui.button(label="Alola", style=discord.ButtonStyle.primary, emoji="7️⃣", row=2)
    async def alola(self, interaction: discord.Interaction, button: ui.Button):
        await self.select_region(interaction, "Alola")

    @ui.button(label="Galar", style=discord.ButtonStyle.primary, emoji="8️⃣", row=2)
    async def galar(self, interaction: discord.Interaction, button: ui.Button):
        await self.select_region(interaction, "Galar")

    @ui.button(label="Paldea", style=discord.ButtonStyle.primary, emoji="9️⃣", row=2)
    async def paldea(self, interaction: discord.Interaction, button: ui.Button):
        await self.select_region(interaction, "Paldea")

# ===============================================
# View de confirmação para o delete (mantida)
# ===============================================

class ConfirmDeleteView(ui.View):
    def __init__(self, supabase_client: Client, discord_id: int):
        super().__init__(timeout=60)
        self.supabase = supabase_client
        self.discord_id = discord_id

    @ui.button(label="Confirmar", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message("Você não pode confirmar esta ação.", ephemeral=True)
            return
        try:
            # Apaga player e (opcional) cascatas, ajuste conforme constraints do seu schema
            self.supabase.table("players").delete().eq("discord_id", self.discord_id).execute()
            # Se for necessário, apagar os Pokémon do jogador:
            # self.supabase.table("player_pokemon").delete().eq("player_id", self.discord_id).execute()
            await interaction.response.edit_message(
                content="Sua jornada foi **excluída** com sucesso.",
                view=None,
                embed=None,
            )
        except Exception as e:
            await interaction.response.send_message(f"Erro ao excluir: {e}", ephemeral=True)

    @ui.button(label="Cancelar", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message("Você não pode cancelar esta ação.", ephemeral=True)
            return
        await interaction.response.edit_message(content="Exclusão cancelada.", view=None, embed=None)

# ===============================================
# Cog do Jogador (comandos principais)
# ===============================================

class PlayerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.supabase = get_supabase_client()

    # ------- helpers (mantidos) -------
    async def player_exists(self, discord_id: int) -> bool:
        try:
            res = self.supabase.table("players").select("discord_id").eq("discord_id", discord_id).limit(1).execute()
            return bool(res.data)
        except Exception:
            return False

    # --------------------------------
    # Comandos principais do jogador
    # --------------------------------

    @commands.command(name="start")
    async def start_adventure(self, ctx: commands.Context):
        """
        Inicia o fluxo de criação: botão → modal (nome) → seleção de região → escolha de starter.
        """
        if await self.player_exists(ctx.author.id):
            await ctx.send(f"Olá novamente, {ctx.author.mention}! Você já tem uma jornada em andamento.")
            return
        embed = discord.Embed(
            title="Bem-vindo ao PokeAdventure!",
            description="Clique no botão abaixo para criar seu personagem e dar o primeiro passo.",
            color=discord.Color.gold(),
        )
        await ctx.send(embed=embed, view=StartJourneyView(supabase_client=self.supabase))

    @commands.command(name="profile")
    async def profile(self, ctx: commands.Context):
        """
        Mostra o perfil do jogador (safe fetch; avatar None-safe).
        """
        try:
            player = supabase_fetch_one(self.supabase, "players", discord_id=ctx.author.id)
            if not player:
                await ctx.send(f"Você ainda não começou sua jornada, {ctx.author.mention}. Use `!start` para iniciar!")
                return

            embed = discord.Embed(
                title=f"Perfil de: {player.get('trainer_name', ctx.author.display_name)}",
                color=discord.Color.green()
            )
            embed.set_author(name=ctx.author.display_name, icon_url=getattr(ctx.author.avatar, "url", None))
            embed.add_field(name="💰 Dinheiro", value=f"${player.get('money', 0):,}", inline=True)
            embed.add_field(name="🏅 Insígnias", value=str(player.get("badges", 0)), inline=True)
            loc = player.get("current_location_name", "Desconhecida").replace("-", " ").title()
            embed.add_field(name="📍 Localização", value=loc, inline=False)
            embed.add_field(name="🌍 Região", value=player.get("current_region", "—"), inline=True)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"Ocorreu um erro ao buscar seu perfil: {e}")

    @commands.command(name="delete")
    async def delete_journey(self, ctx: commands.Context):
        """
        Abre uma view de confirmação para excluir TODO o progresso do jogador.
        (Sem ephemeral em ctx.send, pois não é interaction.)
        """
        if not await self.player_exists(ctx.author.id):
            await ctx.send(f"Você não tem uma jornada para excluir, {ctx.author.mention}.")
            return

        embed = discord.Embed(
            title="⚠️ Atenção: Excluir Jornada ⚠️",
            description=(
                "Você tem certeza que deseja excluir **todo** o seu progresso?\n\n"
                "Esta ação é **irreversível**. Clique em **Confirmar** para prosseguir."
            ),
            color=discord.Color.red(),
        )
        await ctx.send(embed=embed, view=ConfirmDeleteView(self.supabase, ctx.author.id))

    @commands.command(name="addpokemon")
    async def add_pokemon_cmd(self, ctx: commands.Context, pokemon_api_name: str, level: int = 5):
        """
        Comando de utilidade/admin para adicionar um Pokémon ao jogador atual.
        Mantém a lógica original: texto (sem view).
        """
        if not await self.player_exists(ctx.author.id):
            await ctx.send("Você precisa iniciar sua jornada primeiro (`!start`).")
            return

        if level < 1:
            level = 1
        if level > 100:
            level = 100

        result = await add_pokemon_to_player(
            player_id=ctx.author.id,
            pokemon_api_name=pokemon_api_name.lower(),
            level=level,
            captured_at="Comando addpokemon",
        )
        if result["success"]:
            p = result["data"]
            await ctx.send(
                f"✅ **{p.get('nickname', pokemon_api_name.capitalize())}** adicionado! "
                f"(nível {p.get('current_level', level)}; "
                f"{'shiny' if p.get('is_shiny') else 'normal'})"
            )
        else:
            await ctx.send(f"❌ Erro: {result['error']}")

    # ============================
    # NOVOS COMANDOS
    # ============================

    @commands.command(name="setregion")
    async def cmd_setregion(self, ctx: commands.Context, *, region: str):
        """
        Define/atualiza a região do jogador e aplica o spawn correspondente.
        Uso: !setregion Paldea
        """
        region = (region or "").strip().title()
        if region not in VALID_REGIONS:
            await ctx.send(f"Região inválida. Escolha uma de: {', '.join(VALID_REGIONS)}")
            return

        spawn = _spawn_for_region(region)
        try:
            # upsert simples
            (
                self.supabase.table("players")
                .upsert(
                    {
                        "discord_id": ctx.author.id,
                        "current_region": region,
                        "current_location_name": spawn,
                    },
                    on_conflict="discord_id",
                )
                .execute()
            )
            # garante update se já existia
            (
                self.supabase.table("players")
                .update({"current_region": region, "current_location_name": spawn})
                .eq("discord_id", ctx.author.id)
                .execute()
            )
            await ctx.send(f"Região definida para **{region}**. Spawn em **{spawn.replace('-', ' ').title()}**.")
        except Exception as e:
            await ctx.send(f"Falha ao definir região: `{e}`")

    @commands.command(name="whereami", aliases=["onde"])
    async def cmd_whereami(self, ctx: commands.Context):
        """Mostra região e local atual do jogador (debug rápido)."""
        try:
            res = (
                self.supabase.table("players")
                .select("current_region,current_location_name,badges")
                .eq("discord_id", ctx.author.id)
                .limit(1)
                .execute()
            )
            rows = res.data or []
            if not rows:
                await ctx.send("Nenhum perfil encontrado. Use `!start` para iniciar.")
                return
            row = rows[0]
            reg = row.get("current_region") or "—"
            loc = row.get("current_location_name") or "—"
            bdg = row.get("badges") or 0
            await ctx.send(f"🌍 **{reg}** · 📍 **{loc.replace('-', ' ').title()}** · 🏅 **{bdg}/8**")
        except Exception as e:
            await ctx.send(f"Erro ao consultar: `{e}`")

    @commands.command(name="help")
    async def custom_help(self, ctx: commands.Context):
        embed = discord.Embed(
            title="Ajuda do PokeAdventure",
            description=(
                "Comandos principais:\n"
                "`!start` — criar personagem\n"
                "`!travel` — explorar o mundo\n"
                "`!profile` — ver seu perfil\n"
                "`!whereami` — ver região/local/insígnias\n"
                "`!setregion <Região>` — trocar de região (vai para o spawn)\n"
                "`!delete` — excluir sua jornada\n"
                "`!addpokemon <nome> [level]` — adicionar Pokémon ao seu time/box"
            ),
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=embed)

# ---- setup do cog ----
async def setup(bot: commands.Bot):
    await bot.add_cog(PlayerCog(bot))
