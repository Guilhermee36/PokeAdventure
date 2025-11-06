# cogs/adventure_cog.py

import discord
import os  # Importado para verificar o caminho do arquivo
from discord.ext import commands
from discord import ui
from supabase import create_client, Client
import utils.event_utils as event_utils

# --- Classes de UI (Botões) ---
class AdventureView(ui.View):
    def __init__(self, possible_events: list[str], cog_instance):
        super().__init__(timeout=300)
        self.cog = cog_instance
        self.player = None
        self.location = None
        event_map = {
            "wild_encounter": ui.Button(label="Procurar Pokémon", emoji="🌿", custom_id="adv:wild", style=discord.ButtonStyle.primary, row=0),
            "move_to_location": ui.Button(label="Mudar de Rota", emoji="🗺️", custom_id="adv:travel", style=discord.ButtonStyle.secondary, row=1),
            "find_item": ui.Button(label="Investigar Área", emoji="🎒", custom_id="adv:find_item", style=discord.ButtonStyle.secondary, row=1),
            "pokemon_center": ui.Button(label="Centro Pokémon", emoji="🏥", custom_id="adv:heal", style=discord.ButtonStyle.primary, row=0),
            "shop": ui.Button(label="Loja", emoji="🛒", custom_id="adv:shop", style=discord.ButtonStyle.secondary, row=1),
            "challenge_gym": ui.Button(label="Desafiar Ginásio", emoji="🏅", custom_id="adv:gym", style=discord.ButtonStyle.danger, row=0),
            "talk_npc": ui.Button(label="Falar (NPC)", emoji="💬", custom_id="adv:talk", style=discord.ButtonStyle.secondary, row=1),
            "move_to_route": ui.Button(label="Mudar de Rota", emoji="🗺️", custom_id="adv:travel", style=discord.ButtonStyle.secondary, row=1),
        }
        for event_name in possible_events:
            if event_name in event_map:
                button = event_map[event_name]
                button.callback = self.on_button_click
                self.add_item(button)

    async def on_button_click(self, interaction: discord.Interaction):
        custom_id = interaction.data['custom_id']
        if interaction.user.id != self.player['discord_id']:
            await interaction.response.send_message("Estes não são seus botões!", ephemeral=True)
            return
        action = custom_id.split(':')[-1]
        if action == "shop":
            await self.cog.handle_adventure_action(interaction, self.player, self.location, action, respond_now=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await self.cog.handle_adventure_action(interaction, self.player, self.location, action, respond_now=False)


# --- Cog Principal ---
class AdventureCog(commands.Cog):
    """Cog para gerenciar a exploração, eventos e interações no mundo."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        url: str = os.environ.get("SUPABASE_URL")
        key: str = os.environ.get("SUPABASE_KEY")
        self.supabase: Client = create_client(url, key)
        print("AdventureCog carregado.")

    async def _get_player_data(self, player_id: int):
        """Busca dados do jogador."""
        res = self.supabase.table("players").select("*").eq("discord_id", player_id).single().execute()
        return res.data if res.data else None

    async def _get_location_data(self, location_name: str):
        """Busca dados da localização."""
        res = self.supabase.table("locations").select("*").eq("location_api_name", location_name).single().execute()
        return res.data if res.data else None

    def _get_location_mission(self, location: dict, player: dict) -> tuple[str, str]:
        """(SIMULADO) Define a missão da localização atual."""
        if location['location_api_name'] == 'route-1':
            return ("Progresso da Rota", "Derrote 10 Pokémon selvagens. (0/10)")
        if location['type'] == 'city':
            if location.get('has_gym', False):
                return ("Desafio da Cidade", "Derrote o Líder de Ginásio.")
            return ("Exploração", "Fale com os habitantes locais.")
        return ("Exploração", "Explore a área.")

    async def _build_adventure_embed(self, player: dict, location: dict, mission: tuple[str, str]) -> discord.Embed:
        """Constrói o embed da aventura."""
        location_name_pt = location.get('name_pt', player['current_location_name'].capitalize())

        embed = discord.Embed(
            title=f"📍 Local: {location_name_pt}",
            description=f"O que você gostaria de fazer, {player['trainer_name']}?",
            color=discord.Color.dark_green()
        )

        mission_title, mission_desc = mission
        embed.add_field(name=f"🎯 {mission_title}", value=mission_desc, inline=False)
        embed.set_image(url="attachment://region_map.png")
        embed.set_footer(text=f"Explorando como {player['trainer_name']}.")
        return embed

    @commands.command(name='adventure', aliases=['adv', 'a'])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def adventure(self, ctx: commands.Context):
        player = await self._get_player_data(ctx.author.id)
        if not player:
            await ctx.send(f"Você ainda não começou sua jornada, {ctx.author.mention}. Use `!start`!")
            return

        location = await self._get_location_data(player['current_location_name'])
        if not location:
            await ctx.send("Erro crítico: Sua localização atual não foi encontrada no banco de dados.")
            return

        possible_events = await event_utils.get_possible_events(self.supabase, player)
        if not possible_events:
            await ctx.send("Você olha ao redor, mas não há nada de interessante para fazer agora.")
            return

        mission_data = self._get_location_mission(location, player)
        view = AdventureView(possible_events, self)
        view.player = player
        view.location = location
        embed = await self._build_adventure_embed(player, location, mission_data)

        if 'pokemon_center' in possible_events and len(possible_events) == 1:
            embed.color = discord.Color.red()
            embed.description = "Seu time está exausto! Você corre para o Centro Pokémon."

        discord_file = None
        filepath = ""

        try:
            player_region = player.get('current_region', 'Kanto')
            region_filename = f"{player_region.capitalize()}.png"

            # ✅ CORREÇÃO: caminho absoluto seguro
            base_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(base_dir)
            filepath = os.path.join(project_root, "assets", "Regions", region_filename)

            if os.path.exists(filepath):
                with open(filepath, 'rb') as f:
                    discord_file = discord.File(f, filename="region_map.png")
            else:
                embed.set_image(url=None)
                print(f"AVISO: Imagem do mapa não encontrada em {filepath}")
                if await self.bot.is_owner(ctx.author):
                    await ctx.send(f"**Debug (Admin):** Mapa não encontrado. Verifiquei: `{filepath}`", delete_after=10)

            msg = await ctx.send(embed=embed, view=view, file=discord_file)
            view.message = msg

        except discord.HTTPException as e:
            print(f"ERRO DE DISCORD (HTTPException): {e}")
            embed.set_image(url=None)
            msg = await ctx.send(embed=embed, view=view)
            view.message = msg
            await ctx.send(f"Houve um erro ao tentar carregar a imagem do mapa (HTTPException): {e}", ephemeral=True)

        except Exception as e:
            print(f"ERRO GERAL no anexo de imagem (Caminho: {filepath}): {e}")
            embed.set_image(url=None)
            msg = await ctx.send(embed=embed, view=view)
            view.message = msg
            await ctx.send(f"Houve um erro inesperado ao carregar a imagem: {e}", ephemeral=True)

    @adventure.error
    async def adventure_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Você está explorando... (Disponível em {error.retry_after:.1f}s)", delete_after=3)
        else:
            await ctx.send(f"Ocorreu um erro no comando !adventure: {error}")
            print(f"Erro no !adventure: {error}")

    async def handle_adventure_action(self, interaction: discord.Interaction, player: dict, location: dict, action: str, respond_now: bool = False):
        sender = interaction.response.send_message if respond_now else interaction.followup.send

        if action == "heal":
            await self.action_heal_team(interaction, player['discord_id'], sender)
        elif action == "travel":
            await self.action_show_travel(interaction, player, location, sender)
        elif action == "shop":
            await sender("Você se dirige à loja. Use `!shop` para ver os itens ou `!buy` para comprar.", ephemeral=True)
        elif action == "wild":
            await sender("Você começa a procurar na grama alta... (Lógica de `wild_encounter` ainda não implementada)")
        elif action == "gym":
            await sender("Você está na porta do Ginásio. (Lógica de `challenge_gym` ainda não implementada)")
        elif action == "talk":
            await sender("Você procura alguém para conversar... (Lógica de `talk_npc` ainda não implementada)")
        elif action == "find_item":
            await sender("Você vasculha a área... (Lógica de `find_item` ainda não implementada)")

    async def action_heal_team(self, interaction: discord.Interaction, player_id: int, sender):
        try:
            party_res = self.supabase.table("player_pokemon").select("id, max_hp").eq("player_id", player_id).filter("party_position", "not.is", "null").execute()
            if not party_res.data:
                await sender("Você não tem Pokémon no seu time para curar.")
                return

            for p in party_res.data:
                self.supabase.table("player_pokemon").update({"current_hp": p['max_hp']}).eq("id", p['id']).execute()

            await sender("🏥 Seu time foi completamente curado e está pronto para a batalha!")

        except Exception as e:
            await sender(f"Ocorreu um erro ao curar seu time: {e}")

    async def action_show_travel(self, interaction: discord.Interaction, player: dict, location: dict, sender):
        try:
            routes_res = self.supabase.table("routes").select("location_to, locations!routes_location_to_fkey(name_pt)").eq("location_from", location['location_api_name']).execute()
            if not routes_res.data:
                await sender("Não há rotas conectadas a este local.")
                return

            view = TravelView(routes_res.data, self)
            view.player = player
            embed = discord.Embed(title="Para onde você quer ir?", description="Escolha seu destino:", color=discord.Color.blue())
            await sender(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            await sender(f"Ocorreu um erro ao buscar rotas: {e}")

    async def action_move_to(self, interaction: discord.Interaction, player: dict, new_location_api_name: str):
        try:
            self.supabase.table("players").update({"current_location_name": new_location_api_name}).eq("discord_id", player['discord_id']).execute()
            loc_data = await self._get_location_data(new_location_api_name)
            new_loc_name_pt = loc_data['name_pt'] if loc_data else new_location_api_name.capitalize()
            await interaction.followup.send(f"Você viajou para **{new_loc_name_pt}**!")
        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro ao viajar: {e}")


# --- View de Viagem ---
class TravelView(ui.View):
    def __init__(self, routes_data: list, cog_instance):
        super().__init__(timeout=180)
        self.cog = cog_instance
        self.player = None
        for route in routes_data:
            location_api_name = route['location_to']
            location_pt_name = route['locations']['name_pt']
            button = ui.Button(label=location_pt_name, custom_id=f"travel:{location_api_name}")
            button.callback = self.on_travel_click
            self.add_item(button)

    async def on_travel_click(self, interaction: discord.Interaction):
        if interaction.user.id != self.player['discord_id']:
            await interaction.response.send_message("Estes não são seus botões!", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        custom_id = interaction.data['custom_id']
        new_location = custom_id.split(':')[-1]
        await interaction.response.edit_message(content=f"Viajando para {new_location}...", view=None)
        await self.cog.action_move_to(interaction, self.player, new_location)


# --- Setup ---
async def setup(bot: commands.Bot):
    await bot.add_cog(AdventureCog(bot))
