# cogs/adventure_cog.py

import discord
import os
from discord.ext import commands
from discord import ui
from supabase import create_client, Client
import utils.event_utils as event_utils

# --- Classes de UI (Botões) ---

class AdventureView(ui.View):
    """Gera botões dinâmicos baseados nos eventos possíveis."""
    
    def __init__(self, possible_events: list[str], cog_instance):
        super().__init__(timeout=300)
        self.cog = cog_instance # Referência ao AdventureCog
        self.player = None # Será definido pelo Cog
        self.location = None # Será definido pelo Cog

        # Mapeamento de eventos para botões
        event_map = {
            "pokemon_center": ui.Button(label="Curar", emoji="🏥", custom_id="adv:heal", style=discord.ButtonStyle.green),
            "shop": ui.Button(label="Loja", emoji="🛒", custom_id="adv:shop", style=discord.ButtonStyle.secondary),
            "talk_npc": ui.Button(label="Falar", emoji="💬", custom_id="adv:talk", style=discord.ButtonStyle.secondary),
            "challenge_gym": ui.Button(label="Ginásio", emoji="🏅", custom_id="adv:gym", style=discord.ButtonStyle.danger),
            "move_to_route": ui.Button(label="Viajar", emoji="🗺️", custom_id="adv:travel", style=discord.ButtonStyle.primary),
            "move_to_location": ui.Button(label="Viajar", emoji="🗺️", custom_id="adv:travel", style=discord.ButtonStyle.primary),
            "wild_encounter": ui.Button(label="Procurar", emoji="🌿", custom_id="adv:wild", style=discord.ButtonStyle.primary),
            "find_item": ui.Button(label="Investigar", emoji="🎒", custom_id="adv:find_item", style=discord.ButtonStyle.secondary),
        }

        # Adiciona apenas os botões para os eventos possíveis
        for event_name in possible_events:
            if event_name in event_map:
                button = event_map[event_name]
                # Vincula o callback ao botão dinamicamente
                button.callback = self.on_button_click
                self.add_item(button)

    async def on_button_click(self, interaction: discord.Interaction):
        """Callback genérico para todos os botões."""
        custom_id = interaction.data['custom_id']
        
        # Verifica se o jogador pode interagir
        if interaction.user.id != self.player['discord_id']:
            await interaction.response.send_message("Estes não são seus botões!", ephemeral=True)
            return

        # Desativa a view
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        # Delega a ação para o Cog
        action = custom_id.split(':')[-1]
        await self.cog.handle_adventure_action(interaction, self.player, self.location, action)


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

    @commands.command(name='adventure', aliases=['adv', 'a'])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def adventure(self, ctx: commands.Context):
        """Mostra as ações possíveis na sua localização atual."""
        
        player = await self._get_player_data(ctx.author.id)
        if not player:
            await ctx.send(f"Você ainda não começou sua jornada, {ctx.author.mention}. Use `!start`!")
            return
            
        location = await self._get_location_data(player['current_location_name'])
        if not location:
            await ctx.send("Erro crítico: Sua localização atual não foi encontrada no banco de dados. Contate um admin.")
            return

        # 1. Busca eventos possíveis
        possible_events = await event_utils.get_possible_events(self.supabase, player)
        
        if not possible_events:
            await ctx.send("Você olha ao redor, mas não há nada de interessante para fazer agora.")
            return
            
        # 2. Gera a UI
        view = AdventureView(possible_events, self)
        view.player = player
        view.location = location
        
        embed = discord.Embed(
            title=f"📍 {location['name_pt']}",
            description=f"O que você gostaria de fazer, {player['trainer_name']}?",
            color=discord.Color.blue()
        )
        
        if 'pokemon_center' in possible_events and len(possible_events) == 1:
            embed.description = "Seu time está exausto! Você corre para o Centro Pokémon."
            embed.color = discord.Color.red()

        # 3. Envia a mensagem
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg # Guarda a mensagem para o timeout

    @adventure.error
    async def adventure_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Você está explorando... (Disponível em {error.retry_after:.1f}s)", delete_after=3)
        else:
            await ctx.send(f"Ocorreu um erro no comando !adventure: {error}")


    # --- Lógica de Ações (Callbacks) ---

    async def handle_adventure_action(self, interaction: discord.Interaction, player: dict, location: dict, action: str):
        """Função central que recebe os cliques dos botões da AdventureView."""
        
        # O 'interaction' já foi respondido (edit) na View.
        # Usamos interaction.followup.send() para novas mensagens.

        if action == "heal":
            await self.action_heal_team(interaction, player['discord_id'])
            
        elif action == "travel":
            await self.action_show_travel(interaction, player, location)
            
        elif action == "shop":
            # O ShopCog já tem o comando !shop, idealmente o jogador deveria usá-lo.
            # Mas podemos fornecer um atalho.
            await interaction.followup.send(f"Você se dirige à loja. Use `!shop` para ver os itens ou `!buy` para comprar.")
        
        # --- Placeholders para lógicas futuras ---
        elif action == "wild":
            await interaction.followup.send(f"Você começa a procurar na grama alta... (Lógica de `wild_encounter` ainda não implementada)")
        
        elif action == "gym":
            await interaction.followup.send(f"Você está na porta do Ginásio. (Lógica de `challenge_gym` ainda não implementada)")
        
        elif action == "talk":
            await interaction.followup.send(f"Você procura alguém para conversar... (Lógica de `talk_npc` ainda não implementada)")

        elif action == "find_item":
            await interaction.followup.send(f"Você vasculha a área... (Lógica de `find_item` ainda não implementada)")


    async def action_heal_team(self, interaction: discord.Interaction, player_id: int):
        """Cura todos os Pokémon da party do jogador."""
        try:
            party_res = self.supabase.table("player_pokemon") \
                .select("id, max_hp") \
                .eq("player_id", player_id) \
                .filter("party_position", "not.is", "null") \
                .execute()
            
            if not party_res.data:
                await interaction.followup.send("Você não tem Pokémon no seu time para curar.")
                return

            # Atualiza o HP de cada Pokémon
            updates = []
            for p in party_res.data:
                updates.append(
                    self.supabase.table("player_pokemon")
                    .update({"current_hp": p['max_hp']})
                    .eq("id", p['id'])
                    .execute()
                )
            
            # (Opcional: Fazer em lote se o 'supabase-py' suportar upsert em lote)
            
            await interaction.followup.send("🏥 Seu time foi completamente curado e está pronto para a batalha!")

        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro ao curar seu time: {e}")


    async def action_show_travel(self, interaction: discord.Interaction, player: dict, location: dict):
        """Busca as rotas conectadas e mostra botões de destino."""
        try:
            routes_res = self.supabase.table("routes") \
                .select("location_to, locations!routes_location_to_fkey(name_pt)") \
                .eq("location_from", location['location_api_name']) \
                .execute()

            if not routes_res.data:
                await interaction.followup.send("Não há rotas conectadas a este local.")
                return

            view = TravelView(routes_res.data, self)
            view.player = player
            
            embed = discord.Embed(
                title="Para onde você quer ir?",
                description="Escolha seu destino:",
                color=discord.Color.blue()
            )
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro ao buscar rotas: {e}")

    async def action_move_to(self, interaction: discord.Interaction, player: dict, new_location_api_name: str):
        """Atualiza a localização do jogador no DB."""
        try:
            self.supabase.table("players") \
                .update({"current_location_name": new_location_api_name}) \
                .eq("discord_id", player['discord_id']) \
                .execute()
            
            # Busca o nome PT da nova localização
            loc_data = await self._get_location_data(new_location_api_name)
            new_loc_name_pt = loc_data['name_pt'] if loc_data else new_location_api_name.capitalize()

            await interaction.followup.send(f"Você viajou para **{new_loc_name_pt}**!")

        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro ao viajar: {e}")


# --- View Específica de Viagem ---

class TravelView(ui.View):
    def __init__(self, routes_data: list, cog_instance):
        super().__init__(timeout=180)
        self.cog = cog_instance
        self.player = None
        
        for route in routes_data:
            location_api_name = route['location_to']
            # 'locations' é o nome da tabela juntada (foreign key)
            location_pt_name = route['locations']['name_pt'] 
            
            button = ui.Button(label=location_pt_name, custom_id=f"travel:{location_api_name}")
            button.callback = self.on_travel_click
            self.add_item(button)

    async def on_travel_click(self, interaction: discord.Interaction):
        # Verifica se o jogador pode interagir
        if interaction.user.id != self.player['discord_id']:
            await interaction.response.send_message("Estes não são seus botões!", ephemeral=True)
            return

        for item in self.children:
            item.disabled = True
        
        custom_id = interaction.data['custom_id']
        new_location = custom_id.split(':')[-1]
        
        await interaction.response.edit_message(content=f"Viajando para {new_location}...", view=self)
        
        # Delega a ação final
        await self.cog.action_move_to(interaction, self.player, new_location)


# --- Setup ---
async def setup(bot: commands.Bot):
    await bot.add_cog(AdventureCog(bot))