# cogs/adventure_cog.py

import os
import discord
from discord.ext import commands
from discord import ui
from supabase import create_client, Client

import utils.event_utils as event_utils

# ==========================
# View principal do Adventure
# ==========================

class AdventureView(ui.View):
    """
    Renderiza os botões de ação com base nos 'possible_events'.
    A própria view recebe o player e a location para validar cliques.
    """
    def __init__(self, possible_events: list[str], cog_instance: "AdventureCog"):
        super().__init__(timeout=300)
        self.cog = cog_instance
        self.player: dict | None = None
        self.location: dict | None = None

        # Mapa de botões por evento
        event_map: dict[str, ui.Button] = {
            "wild_encounter": ui.Button(
                label="Procurar Pokémon", emoji="🌿",
                custom_id="adv:wild", style=discord.ButtonStyle.primary, row=0
            ),
            "move_to_location": ui.Button(
                label="Mudar de Rota", emoji="🗺️",
                custom_id="adv:travel", style=discord.ButtonStyle.secondary, row=1
            ),
            "find_item": ui.Button(
                label="Investigar Área", emoji="🎒",
                custom_id="adv:find_item", style=discord.ButtonStyle.secondary, row=1
            ),
            "pokemon_center": ui.Button(
                label="Centro Pokémon", emoji="🏥",
                custom_id="adv:heal", style=discord.ButtonStyle.primary, row=0
            ),
            "shop": ui.Button(
                label="Loja", emoji="🛒",
                custom_id="adv:shop", style=discord.ButtonStyle.secondary, row=1
            ),
            "challenge_gym": ui.Button(
                label="Desafiar Ginásio", emoji="🏅",
                custom_id="adv:gym", style=discord.ButtonStyle.danger, row=0
            ),
            "talk_npc": ui.Button(
                label="Falar (NPC)", emoji="💬",
                custom_id="adv:talk", style=discord.ButtonStyle.secondary, row=1
            ),
            # alias (compatibilidade)
            "move_to_route": ui.Button(
                label="Mudar de Rota", emoji="🗺️",
                custom_id="adv:travel", style=discord.ButtonStyle.secondary, row=1
            ),
        }

        # Só adiciona os botões mapeados
        for event_name in possible_events:
            button = event_map.get(event_name)
            if button:
                # Cada botão aponta para o mesmo callback (identificamos pelo custom_id)
                button.callback = self.on_button_click
                self.add_item(button)

    async def on_button_click(self, interaction: discord.Interaction):
        # Segurança: botões são do dono do contexto
        if not self.player or interaction.user.id != self.player["discord_id"]:
            await interaction.response.send_message("Estes não são seus botões!", ephemeral=True)
            return

        # Desabilita todos para evitar duplo clique
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        action = str(interaction.data.get("custom_id", "")).split(":")[-1]
        # shop responde imediatamente (para mensagem efêmera), o resto usa followup
        respond_now = (action == "shop")
        await self.cog.handle_adventure_action(
            interaction, self.player, self.location, action, respond_now=respond_now
        )


# =====================
# View para escolher rota
# =====================

class TravelView(ui.View):
    def __init__(self, destinations: list[dict], cog_instance: "AdventureCog"):
        """
        `destinations` vem de event_utils.get_adjacent_locations_in_region()
        e já traz: location_api_name, name_pt/name, type, etc.
        """
        super().__init__(timeout=180)
        self.cog = cog_instance
        self.player: dict | None = None

        for loc in destinations:
            api_name = loc["location_api_name"]
            # prioriza 'name_pt', depois 'name', depois o api_name formatado
            label = loc.get("name_pt") or loc.get("name") or api_name.replace("-", " ").title()
            button = ui.Button(label=label, custom_id=f"travel:{api_name}")
            button.callback = self.on_travel_click
            self.add_item(button)

    async def on_travel_click(self, interaction: discord.Interaction):
        if not self.player or interaction.user.id != self.player["discord_id"]:
            await interaction.response.send_message("Estes não são seus botões!", ephemeral=True)
            return
        # trava visual
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=None)

        new_location = str(interaction.data.get("custom_id", "")).split(":")[-1]
        await self.cog.action_move_to(interaction, self.player, new_location)


# ============
# Cog principal
# ============

class AdventureCog(commands.Cog):
    """Exploração, eventos e interações com o mundo."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        url: str = os.environ.get("SUPABASE_URL")
        key: str = os.environ.get("SUPABASE_KEY")
        self.supabase: Client = create_client(url, key)
        # caminho base do projeto (para achar assets/Regions/<Região>.png)
        self.base_project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        print("AdventureCog carregado.")

    # -------------------------
    # Fetch helpers (Supabase)
    # -------------------------

    async def _get_player_data(self, player_id: int) -> dict | None:
        res = (
            self.supabase.table("players")
            .select("*")
            .eq("discord_id", player_id)
            .single()
            .execute()
        )
        return res.data if res.data else None  # :contentReference[oaicite:4]{index=4}

    async def _get_location_data(self, location_name: str) -> dict | None:
        res = (
            self.supabase.table("locations")
            .select("*")
            .eq("location_api_name", location_name)
            .single()
            .execute()
        )
        return res.data if res.data else None  # :contentReference[oaicite:5]{index=5}

    # -------------------------
    # Missão (placeholder)
    # -------------------------

    def _get_location_mission(self, location: dict, player: dict) -> tuple[str, str]:
        """
        Placeholder simples para enriquecer o embed.
        """
        if location.get("location_api_name") == "route-1":
            return ("Progresso da Rota", "Derrote 10 Pokémon selvagens. (0/10)")
        if location.get("type") == "city":
            if location.get("has_gym", False):
                return ("Desafio da Cidade", "Derrote o Líder de Ginásio.")
            return ("Exploração", "Converse com os habitantes locais.")
        return ("Exploração", "Explore a área.")  # :contentReference[oaicite:6]{index=6}

    async def _build_adventure_embed(
        self, player: dict, location: dict, mission: tuple[str, str]
    ) -> discord.Embed:
        """
        Constrói o embed principal do Adventure.
        """
        location_name_pt = location.get(
            "name_pt", player["current_location_name"].replace("-", " ").title()
        )
        embed = discord.Embed(
            title=f"📍 Local: {location_name_pt}",
            description=f"O que você gostaria de fazer, {player['trainer_name']}?",
            color=discord.Color.dark_green(),
        )
        mission_title, mission_desc = mission
        embed.add_field(name=f"🎯 {mission_title}", value=mission_desc, inline=False)
        embed.set_image(url="attachment://region_map.png")
        embed.set_footer(text=f"Explorando como {player['trainer_name']}.")
        return embed  # :contentReference[oaicite:7]{index=7}

    # -------------------------
    # Comando principal
    # -------------------------

    @commands.command(name="adventure", aliases=["adv", "a"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def adventure(self, ctx: commands.Context):
        player = await self._get_player_data(ctx.author.id)
        if not player:
            await ctx.send(f"Você ainda não começou sua jornada, {ctx.author.mention}. Use `!start`!")
            return

        location = await self._get_location_data(player["current_location_name"])
        if not location:
            await ctx.send("Erro: sua localização atual não foi encontrada no DB. Contate um admin.")
            return

        possible_events = await event_utils.get_possible_events(self.supabase, player)
        if not possible_events:
            await ctx.send("Você olha ao redor, mas não há nada de interessante para fazer agora.")
            return

        view = AdventureView(possible_events, self)
        view.player = player
        view.location = location

        mission_data = self._get_location_mission(location, player)
        embed = await self._build_adventure_embed(player, location, mission_data)

        # Estado 'forçado' de Centro Pokémon
        if "pokemon_center" in possible_events and len(possible_events) == 1:
            embed.color = discord.Color.red()
            embed.description = "Seu time está exausto! Você corre para o Centro Pokémon."

        # Tenta anexar o mapa da região: assets/Regions/<Região>.png
        discord_file = None
        filepath = ""
        try:
            player_region = player.get("current_region", "Kanto")
            region_filename = f"{player_region.capitalize()}.png"
            filepath = os.path.join(self.base_project_dir, "assets", "Regions", region_filename)

            if os.path.exists(filepath):
                with open(filepath, "rb") as f:
                    discord_file = discord.File(f, filename="region_map.png")
            else:
                embed.set_image(url=None)
                print(f"[Adventure] AVISO: Mapa não encontrado em {filepath}")

            msg = await ctx.send(embed=embed, view=view, file=discord_file)
            view.message = msg

        except discord.HTTPException as e:
            print(f"[Adventure] HTTPException ao anexar imagem: {e}")
            embed.set_image(url=None)
            msg = await ctx.send(embed=embed, view=view)
            view.message = msg

        except Exception as e:
            print(f"[Adventure] Erro geral ao anexar imagem ({filepath}): {e}")
            embed.set_image(url=None)
            msg = await ctx.send(embed=embed, view=view)
            view.message = msg

    # -------------------------
    # Handlers / Ações
    # -------------------------

    async def handle_adventure_action(
        self,
        interaction: discord.Interaction,
        player: dict,
        location: dict,
        action: str,
        respond_now: bool = False,
    ):
        sender = interaction.response.send_message if respond_now else interaction.followup.send

        if action == "heal":
            await self.action_heal_team(player["discord_id"], sender)
        elif action == "travel":
            await self.action_show_travel(interaction, player, location, sender)
        elif action == "shop":
            await sender("Você se dirige à loja. Use `!shop` para ver os itens ou `!buy` para comprar.", ephemeral=True)
        elif action == "wild":
            await sender("Você começa a procurar na grama alta... (Encontro selvagem em breve!)")
        elif action == "gym":
            await sender("Você está na porta do Ginásio. (Desafio ao líder em breve!)")
        elif action == "talk":
            await sender("Você procura alguém para conversar. (Interações com NPCs em breve!)")
        elif action == "find_item":
            await sender("Você vasculha a área. (Procura por itens em breve!)")

    async def action_heal_team(self, player_id: int, sender):
        try:
            party_res = (
                self.supabase.table("player_pokemon")
                .select("id, max_hp")
                .eq("player_id", player_id)
                .filter("party_position", "not.is", "null")
                .execute()
            )
            if not party_res.data:
                await sender("Você não tem Pokémon no seu time para curar.")
                return

            for p in party_res.data:
                (
                    self.supabase.table("player_pokemon")
                    .update({"current_hp": p["max_hp"]})
                    .eq("id", p["id"])
                    .execute()
                )
            await sender("🏥 Seu time foi completamente curado!")

        except Exception as e:
            await sender(f"Ocorreu um erro ao curar seu time: {e}")

    async def action_show_travel(self, interaction: discord.Interaction, player: dict, location: dict, sender):
        """
        Mostra destinos alcançáveis a partir do local atual, **filtrados pela região do jogador**.
        """
        try:
            destinations = await event_utils.get_adjacent_locations_in_region(
                supabase=self.supabase,
                from_location_api_name=location["location_api_name"],
                region=player["current_region"],
            )

            if not destinations:
                await sender("Não há rotas conectadas a este local.")
                return

            view = TravelView(destinations, self)
            view.player = player

            embed = discord.Embed(
                title="Para onde você quer ir?",
                description="Escolha seu destino:",
                color=discord.Color.blue(),
            )
            await sender(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            await sender(f"Ocorreu um erro ao buscar rotas: {e}")  # :contentReference[oaicite:8]{index=8}

    async def action_move_to(self, interaction: discord.Interaction, player: dict, new_location_api_name: str):
        try:
            (
                self.supabase.table("players")
                .update({"current_location_name": new_location_api_name})
                .eq("discord_id", player["discord_id"])
                .execute()
            )
            loc_data = await self._get_location_data(new_location_api_name)
            new_loc_name_pt = (
                (loc_data or {}).get("name_pt")
                or (loc_data or {}).get("name")
                or new_location_api_name.replace("-", " ").title()
            )
            await interaction.followup.send(f"Você viajou para **{new_loc_name_pt}**!")

        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro ao viajar: {e}")

    # -------------------------
    # Error handler
    # -------------------------

    @adventure.error
    async def adventure_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Você está explorando. (Disponível em {error.retry_after:.1f}s)", delete_after=3)
        else:
            await ctx.send(f"Ocorreu um erro no comando !adventure: {error}")
            print(f"[Adventure] Erro no !adventure: {error}")


# ---- setup do cog ----

async def setup(bot: commands.Bot):
    await bot.add_cog(AdventureCog(bot))
