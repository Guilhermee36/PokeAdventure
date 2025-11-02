# cogs/player_cog.py

import discord
from discord.ext import commands
from discord import ui
import random
# import aiohttp # REMOVIDO: Usaremos o service
from supabase import create_client, Client
import os

# =================================================================
# ALTERAÇÃO 1: Imports centralizados
# =================================================================
import utils.pokeapi_service as pokeapi
import utils.evolution_utils as evolution_utils # NOVO: Importa o utilitário de evolução

# --- Helper Functions ---

# =================================================================
# ALTERAÇÃO 2: Função 'fetch_pokemon_data' removida
# A função 'pokeapi.get_pokemon_data()' substitui isso.
# =================================================================

def get_supabase_client():
    """Cria e retorna um cliente Supabase."""
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY")
    return create_client(url, key)

# =================================================================
# ALTERAÇÃO 3: Função 'get_initial_moves' removida
# A função 'pokeapi.get_initial_moves()' substitui esta.
# =================================================================

# =================================================================
# ALTERAÇÃO 4: 'add_pokemon_to_player' reescrita para usar
# 'pokeapi_service' para stats completos e ataques.
# =================================================================
async def add_pokemon_to_player(player_id: int, pokemon_api_name: str, level: int = 5, captured_at: str = "Início da Jornada") -> dict:
    """Função centralizada que adiciona um Pokémon com stats e ataques iniciais."""
    supabase = get_supabase_client()
    
    # 1. Verifica se o time está cheio
    try:
        count_response = supabase.table("player_pokemon").select("id", count='exact').eq("player_id", player_id).execute()
        pokemon_count = count_response.count
    except Exception as e:
        return {'success': False, 'error': f"Erro ao contar Pokémon: {e}"}

    if pokemon_count >= 6:
        return {'success': False, 'error': "Seu time já está cheio! Você não pode carregar mais de 6 Pokémon."}
        
    # 2. Busca dados da PokeAPI
    poke_data = await pokeapi.get_pokemon_data(pokemon_api_name)
    if not poke_data:
        return {'success': False, 'error': f"Pokémon '{pokemon_api_name}' não encontrado na API."}
    
    # 3. Lógica de Posição, Shiny, etc.
    is_shiny = random.randint(1, 4096) == 1 # Chance real de shiny
    party_position = pokemon_count + 1
    
    # 4. Calcula todos os stats usando o utilitário
    # Isso retorna um dict: {'max_hp': X, 'attack': Y, 'defense': Z, ...}
    calculated_stats = pokeapi.calculate_stats_for_level(poke_data['stats'], level)

    # 5. Busca os ataques iniciais usando o utilitário
    initial_moves = pokeapi.get_initial_moves(poke_data, level)

    # 6. Monta o objeto final para o Supabase
    new_pokemon_data = { 
        "player_id": player_id, 
        "pokemon_api_name": pokemon_api_name, 
        "pokemon_pokedex_id": poke_data['id'], # NOVO: Salva o ID da Pokédex
        "nickname": pokemon_api_name.capitalize(),
        "captured_at_location": captured_at, 
        "is_shiny": is_shiny, 
        "party_position": party_position, 
        "current_level": level, 
        "current_hp": calculated_stats['max_hp'], # Define o HP atual como o máximo
        "current_xp": 0,
        "moves": initial_moves,
        
        # Adiciona todos os stats calculados
        **calculated_stats 
        # Isso irá desempacotar o dict para:
        # "max_hp": ...,
        # "attack": ...,
        # "defense": ...,
        # "special_attack": ...,
        # "special_defense": ...,
        # "speed": ...
    }
    
    # 7. Insere no banco de dados
    try:
        insert_response = supabase.table("player_pokemon").insert(new_pokemon_data).execute()
        if len(insert_response.data) > 0:
            return {'success': True, 'message': f"Pokémon adicionado com sucesso na posição {party_position}!", 'data': insert_response.data[0]}
        else:
            return {'success': False, 'error': "Falha ao inserir o Pokémon no banco de dados."}
    except Exception as e:
        return {'success': False, 'error': f"Erro no banco de dados: {e}"}

# --- Classes de UI (O restante do código permanece o mesmo) ---
# ... (StartJourneyView, TrainerNameModal, StarterSelectView, etc. continuam aqui) ...
# (Vou omiti-las para encurtar a resposta, mas elas devem permanecer no seu arquivo)

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

    trainer_name_input = ui.TextInput(label="Qual será seu nome de treinador?", placeholder="Ex: Ash Ketchum", required=True, max_length=50)

    async def on_submit(self, interaction: discord.Interaction):
        trainer_name = self.trainer_name_input.value
        embed = discord.Embed(title="Escolha sua Região Inicial", description=f"Ótimo nome, **{trainer_name}**! Agora, escolha a região onde sua aventura vai começar.", color=discord.Color.blue())
        await interaction.response.send_message(embed=embed, view=RegionSelectView(trainer_name=trainer_name, supabase_client=self.supabase), ephemeral=True)

class StarterSelectView(ui.View):
    def __init__(self, region: str):
        super().__init__(timeout=180)
        self.region = region
        starters = {
            "Kanto": ["bulbasaur", "charmander", "squirtle"], "Johto": ["chikorita", "cyndaquil", "totodile"],
            "Hoenn": ["treecko", "torchic", "mudkip"], "Sinnoh": ["turtwig", "chimchar", "piplup"],
            "Unova": ["snivy", "tepig", "oshawott"], "Kalos": ["chespin", "fennekin", "froakie"],
            "Alola": ["rowlet", "litten", "popplio"], "Galar": ["grookey", "scorbunny", "sobble"],
            "Paldea": ["sprigatito", "fuecoco", "quaxly"]
        }
        for starter in starters.get(region, []):
            button = ui.Button(label=starter.capitalize(), style=discord.ButtonStyle.primary, custom_id=starter)
            button.callback = self.select_starter
            self.add_item(button)

    async def select_starter(self, interaction: discord.Interaction):
        starter_name = interaction.data['custom_id']
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(view=self)
        
        # Chama a nova função 'add_pokemon_to_player'
        result = await add_pokemon_to_player(
            player_id=interaction.user.id, 
            pokemon_api_name=starter_name, 
            level=5, 
            captured_at=f"Recebido em {self.region}"
        )
        
        if result['success']:
            pokemon_data = result['data']
            is_shiny = pokemon_data.get('is_shiny', False)
            shiny_text = "\n\n✨ **UAU, ELE É SHINY! QUE SORTE!** ✨" if is_shiny else ""
            
            public_embed = discord.Embed(
                title="Uma Nova Jornada Começa!", 
                description=f"{interaction.user.mention} iniciou sua aventura e escolheu **{starter_name.capitalize()}** como seu primeiro parceiro!{shiny_text}", 
                color=discord.Color.green()
            )
            
            # Usando 'pokeapi' para buscar o sprite
            poke_api_data = await pokeapi.get_pokemon_data(starter_name) 
            if poke_api_data:
                sprite_url = poke_api_data['sprites']['front_shiny'] if is_shiny else poke_api_data['sprites']['front_default']
                public_embed.set_thumbnail(url=sprite_url)
            
            await interaction.followup.send(embed=public_embed)
        else:
            await interaction.followup.send(f"Ocorreu um erro ao adicionar seu Pokémon: {result['error']}", ephemeral=True)
        self.stop()

class RegionSelectView(ui.View):
    def __init__(self, trainer_name: str, supabase_client: Client):
        super().__init__(timeout=180)
        self.trainer_name = trainer_name
        self.supabase = supabase_client

    async def select_region(self, interaction: discord.Interaction, region: str):
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(view=self)
        discord_id = interaction.user.id
        player_data = {'discord_id': discord_id, 'trainer_name': self.trainer_name, 'current_region': region}
        try:
            # Verifica se o jogador já existe
            existing = self.supabase.table('players').select('discord_id').eq('discord_id', discord_id).execute()
            if not existing.data:
                self.supabase.table('players').insert(player_data).execute()
            else:
                # Se já existir, apenas atualiza (ou ignora)
                self.supabase.table('players').update(player_data).eq('discord_id', discord_id).execute()

            starter_embed = discord.Embed(title=f"Bem-vindo(a) a {region}!", description="Agora, a escolha mais importante: quem será seu parceiro inicial?", color=discord.Color.blue())
            await interaction.followup.send(embed=starter_embed, view=StarterSelectView(region=region), ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro ao salvar seus dados: {e}", ephemeral=True)
        self.stop()
    
    # ... (Botões de Região - Kanto, Johto, etc.) ...
    @ui.button(label="Kanto", style=discord.ButtonStyle.primary, emoji="1️⃣", row=0)
    async def kanto(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Kanto")
    @ui.button(label="Johto", style=discord.ButtonStyle.primary, emoji="2️⃣", row=0)
    async def johto(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Johto")
    @ui.button(label="Hoenn", style=discord.ButtonStyle.primary, emoji="3️⃣", row=0)
    async def hoenn(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Hoenn")
    @ui.button(label="Sinnoh", style=discord.ButtonStyle.primary, emoji="4️⃣", row=1)
    async def sinnoh(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Sinnoh")
    @ui.button(label="Unova", style=discord.ButtonStyle.primary, emoji="5️⃣", row=1)
    async def unova(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Unova")
    @ui.button(label="Kalos", style=discord.ButtonStyle.primary, emoji="6️⃣", row=1)
    async def kalos(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Kalos")
    @ui.button(label="Alola", style=discord.ButtonStyle.primary, emoji="7️⃣", row=2)
    async def alola(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Alola")
    @ui.button(label="Galar", style=discord.ButtonStyle.primary, emoji="8️⃣", row=2)
    async def galar(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Galar")
    @ui.button(label="Paldea", style=discord.ButtonStyle.primary, emoji="9️⃣", row=2)
    async def paldea(self, interaction: discord.Interaction, button: ui.Button): await self.select_region(interaction, "Paldea")


class ConfirmDeleteView(ui.View):
    def __init__(self, supabase_client: Client):
        super().__init__(timeout=60)
        self.supabase = supabase_client

    @ui.button(label="Sim, excluir tudo!", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(view=self)
        try:
            # Excluir também os Pokémon do jogador
            self.supabase.table('player_pokemon').delete().eq('player_id', interaction.user.id).execute()
            # Excluir o jogador
            self.supabase.table('players').delete().eq('discord_id', interaction.user.id).execute()
            await interaction.followup.send("Sua jornada foi reiniciada. Todo o progresso foi excluído. Use `!start` para começar de novo.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro ao excluir seus dados: {e}", ephemeral=True)
        self.stop()

    @ui.button(label="Não, cancelar.", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send("Ação cancelada. Sua jornada continua!", ephemeral=True)
        self.stop()

# --- Cog Class ---

class PlayerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.supabase: Client = get_supabase_client()

    async def player_exists(self, discord_id: int) -> bool:
        response = self.supabase.table('players').select('discord_id').eq('discord_id', discord_id).execute()
        return bool(response.data)

    # =================================================================
    # NOVA FUNÇÃO HELPER: Processar a Evolução
    # =================================================================
    async def process_evolution(self, ctx: commands.Context, pokemon_db_id: str, current_level: int, evo_result: dict):
        """
        Atualiza o Pokémon no banco de dados para sua nova forma.
        """
        new_name = evo_result["new_name"]
        new_api_id = evo_result["new_api_id"]
        
        await ctx.send(f"O que? {evo_result['old_name'].capitalize()} está evoluindo!")
        
        try:
            # 1. Buscar dados da nova espécie
            new_pokemon_data = await pokeapi.get_pokemon_data(new_name)
            if not new_pokemon_data:
                await ctx.send("Erro: Não foi possível buscar dados da nova evolução.")
                return

            # 2. Recalcular stats para o nível ATUAL
            new_stats = pokeapi.calculate_stats_for_level(new_pokemon_data['stats'], current_level)

            # 3. Montar dados de atualização
            # A evolução cura o Pokémon
            update_data = {
                "pokemon_api_name": new_name,
                "pokemon_pokedex_id": new_api_id,
                "nickname": new_name.capitalize(), # Reseta o nickname (ou podemos mantê-lo)
                "current_hp": new_stats['max_hp'], # Cura total na evolução
                **new_stats # Atualiza todos os stats
            }

            # 4. Atualizar no Supabase
            response = (
                self.supabase.table("player_pokemon")
                .update(update_data)
                .eq("id", pokemon_db_id)
                .execute()
            )

            if response.data:
                old_name_cap = evo_result["old_name"].capitalize()
                new_name_cap = new_name.capitalize()
                await ctx.send(f"🎉 Parabéns, {ctx.author.mention}! Seu {old_name_cap} evoluiu para {new_name_cap}!")
            else:
                await ctx.send("Ocorreu um erro ao salvar a evolução no banco de dados.")

        except Exception as e:
            print(f"Erro em process_evolution: {e}")
            await ctx.send("Ocorreu um erro crítico durante a evolução.")
            
    # --- Comandos do Jogador ---

    @commands.command(name='start')
    async def start_adventure(self, ctx: commands.Context):
        if await self.player_exists(ctx.author.id):
            await ctx.send(f"Olá novamente, {ctx.author.mention}! Você já tem uma jornada em andamento.")
            return
        embed = discord.Embed(title="Bem-vindo ao PokeAdventure!", description="Clique no botão abaixo para criar seu personagem e dar o primeiro passo.", color=discord.Color.gold())
        await ctx.send(embed=embed, view=StartJourneyView(supabase_client=self.supabase))

    @commands.command(name='profile')
    async def profile(self, ctx: commands.Context):
        # ... (código existente do profile) ...
        try:
            player = self.supabase.table('players').select('*').eq('discord_id', ctx.author.id).single().execute().data
            if not player:
                await ctx.send(f"Você ainda não começou sua jornada, {ctx.author.mention}. Use `!start` para iniciar!")
                return
            embed = discord.Embed(title=f"Perfil de: {player['trainer_name']}", color=discord.Color.green())
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url)
            embed.add_field(name="💰 Dinheiro", value=f"${player.get('money', 0):,}", inline=True)
            embed.add_field(name="🏅 Insígnias", value=str(player.get('badges', 0)), inline=True)
            embed.add_field(name="📍 Localização", value=player.get('current_region', 'Desconhecida'), inline=False)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"Ocorreu um erro ao buscar seu perfil: {e}")

    @commands.command(name='delete')
    async def delete_journey(self, ctx: commands.Context):
        if not await self.player_exists(ctx.author.id):
            await ctx.send(f"Você não tem uma jornada para excluir, {ctx.author.mention}.")
            return
        embed = discord.Embed(title="⚠️ Atenção: Excluir Jornada ⚠️", description="Você tem certeza que deseja excluir **todo** o seu progresso? Esta ação é **irreversível**.", color=discord.Color.red())
        await ctx.send(embed=embed, view=ConfirmDeleteView(supabase_client=self.supabase), ephemeral=True)

    @commands.command(name='help')
    async def custom_help(self, ctx: commands.Context):
        # ... (código existente do help) ...
        embed = discord.Embed(title="Ajuda do PokeAdventure", description="Comandos para sua jornada.", color=discord.Color.orange())
        embed.add_field(name="`!start`", value="Inicia sua aventura e cria seu personagem.", inline=False)
        embed.add_field(name="`!profile`", value="Exibe seu perfil de treinador.", inline=False)
        embed.add_field(name="`!team`", value="Mostra sua equipe de Pokémon.", inline=False)
        embed.add_field(name="`!use <item> on <pokemon>`", value="Usa um item em um Pokémon (Ex: !use Fire Stone on Eevee).", inline=False) # NOVO
        embed.add_field(name="`!delete`", value="Apaga seu progresso para começar de novo.", inline=False)
        if await self.bot.is_owner(ctx.author):
            embed.add_field(name="--- Comandos de Administrador ---", value="`!addpokemon <nome> [level]`", inline=False)
        await ctx.send(embed=embed)
        
    # =================================================================
    # NOVO COMANDO: !use
    # =================================================================
    @commands.command(name="use", help="Usa um item em um Pokémon.")
    async def use_item(self, ctx: commands.Context, *, args: str):
        """Usa um item. Formato: !use <item_name> on <pokemon_identifier>"""
        try:
            item_name, pokemon_identifier = args.split(" on ", 1)
            item_name = item_name.strip()
            pokemon_identifier = pokemon_identifier.strip()
        except ValueError:
            await ctx.send("Formato incorreto. Use: `!use <nome do item> on <nome ou apelido do pokémon>`")
            return

        # 1. (LÓGICA DE INVENTÁRIO - PENDENTE)
        # Aqui, você deve verificar se o jogador tem o 'item_name' no inventário.
        # Por enquanto, vamos presumir que ele tem.
        
        # 2. Encontrar o Pokémon (Lidando com o bug de nomes duplicados)
        # Esta busca encontra pelo 'nickname' (que pode ser único) ou 'pokemon_api_name'
        # Se houver duplicatas (2 Pikachu), ele pegará o primeiro.
        # O ideal é forçar o usuário a usar o 'nickname'
        query = self.supabase.table("player_pokemon").select("*").eq("player_id", ctx.author.id)
        query = query.or_(f"nickname.ilike.{pokemon_identifier},pokemon_api_name.ilike.{pokemon_identifier}")
        
        response = query.execute()
        
        if not response.data:
            await ctx.send(f"Não foi possível encontrar um Pokémon chamado '{pokemon_identifier}' no seu time.")
            return
        if len(response.data) > 1:
            await ctx.send(f"Você tem mais de um Pokémon que bate com '{pokemon_identifier}'. Por favor, use o apelido (nickname) único dele.")
            return
            
        pkmn = response.data[0]
        pokemon_db_id = pkmn['id'] # <<< Este é o ID ÚNICO (uuid)
        current_level = pkmn['current_level']

        # 3. Montar o contexto para o 'evolution_utils'
        # Normaliza o nome do item para o padrão da API (ex: "Fire Stone" -> "fire-stone")
        item_api_name = item_name.lower().replace(" ", "-")
        context = {"item_name": item_api_name}
        
        # 4. Chamar o utilitário
        try:
            evo_result = await evolution_utils.check_evolution(
                self.supabase,
                pokemon_db_id=pokemon_db_id,
                trigger_event="item_use",
                context=context
            )
            
            if evo_result:
                # 5. (LÓGICA DE INVENTÁRIO - PENDENTE)
                # (Aqui você deve REMOVER o 'item_name' do inventário do jogador)
                # ...
                
                # 6. Processar a evolução
                await self.process_evolution(ctx, pokemon_db_id, current_level, evo_result)
            else:
                await ctx.send("Não teve efeito.")
                
        except Exception as e:
            await ctx.send(f"Ocorreu um erro ao tentar usar o item: {e}")
            print(f"Erro em !use: {e}")

    # --- Comandos de Admin ---

    @commands.command(name='addpokemon')
    @commands.is_owner()
    async def add_pokemon(self, ctx: commands.Context, pokemon_name: str, level: int = 5):
        if not await self.player_exists(ctx.author.id):
            await ctx.send(f"Você precisa iniciar sua jornada primeiro! Use `!start`.")
            return
        
        # Chama a nova função 'add_pokemon_to_player'
        result = await add_pokemon_to_player(
            player_id=ctx.author.id, 
            pokemon_api_name=pokemon_name, 
            level=level, 
            captured_at="Comando de Admin"
        )
        
        if result['success']:
            await ctx.send(f"✅ {pokemon_name.capitalize()} foi adicionado ao seu time! {result['message']}")
        else:
            await ctx.send(f"❌ Erro: {result['error']}")

async def setup(bot: commands.Bot):
    await bot.add_cog(PlayerCog(bot))