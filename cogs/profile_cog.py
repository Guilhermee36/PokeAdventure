import discord
# A correção está nesta linha 👇
from discord.commands import SlashCommandGroup, Option 
from discord.ext import commands
import os
from supabase import create_client, Client

# --- Conexão com o Supabase ---
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)


class ProfileCog(commands.Cog):
    """Cog para gerenciar o perfil e o registro dos jogadores."""

    def __init__(self, bot):
        self.bot = bot

    profile = SlashCommandGroup("profile", "Comandos relacionados ao seu perfil de treinador.")

    @profile.command(name="start", description="Comece sua aventura Pokémon e crie seu perfil de treinador!")
    async def start(
        self,
        ctx: discord.ApplicationContext,
        # Agora o "Option" aqui será reconhecido
        trainer_name: Option(str, "Escolha um nome para o seu treinador Pokémon.")
        
        
    ):
        """
        Registra um novo jogador no banco de dados.
        Este comando insere uma nova linha na tabela 'players'.
        """
        discord_id = ctx.author.id

        try:
            # --- 1. VERIFICAR SE O JOGADOR JÁ EXISTE ---
            response = supabase.table('players').select('discord_id').eq('discord_id', discord_id).execute()
            
            if response.data:
                await ctx.respond(f"Olá, {trainer_name}! Parece que você já começou sua jornada. Use `/profile view` para ver seu perfil.", ephemeral=True)
                return

            # --- 2. CRIAR O NOVO JOGADOR ---
            new_player_data = {
                'discord_id': discord_id,
                'trainer_name': trainer_name,
                'money': 1000,
                'badges': 0,
                'current_region': 'Pallet Town',
                'masterballs_owned': 0
            }

            insert_response = supabase.table('players').insert(new_player_data).execute()

            # --- 3. ENVIAR FEEDBACK PARA O USUÁRIO ---
            if insert_response.data:
                embed = discord.Embed(
                    title=f"Bem-vindo(a) à Aventura, {trainer_name}!",
                    description=(
                        "Seu perfil de treinador foi criado com sucesso!\n"
                        "O mundo Pokémon te espera. Use os comandos do bot para explorar, "
                        "capturar e batalhar."
                    ),
                    color=discord.Color.green()
                )
                embed.set_footer(text="Dica: Use /help para ver a lista de comandos disponíveis.")
                
                await ctx.respond(embed=embed)
            else:
                raise Exception("Falha ao inserir dados no Supabase.")

        except Exception as e:
            print(f"Ocorreu um erro no comando /start: {e}")
            error_embed = discord.Embed(
                title="❌ Erro ao Criar Perfil",
                description="Não foi possível criar seu perfil. Por favor, tente novamente mais tarde. Se o problema persistir, contate um administrador.",
                color=discord.Color.red()
            )
            await ctx.respond(embed=error_embed, ephemeral=True)


def setup(bot):
    """Função necessária para que o bot carregue esta Cog."""
    bot.add_cog(ProfileCog(bot))