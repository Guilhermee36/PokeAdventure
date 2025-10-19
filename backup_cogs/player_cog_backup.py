"""
import discord
import os
from discord.ext import commands
from supabase import create_client, Client

class PlayerCog(commands.Cog):
    Cog para gerenciar todas as interações e comandos dos jogadores.

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Inicializa a conexão com o Supabase
        url: str = os.environ.get("SUPABASE_URL")
        key: str = os.environ.get("SUPABASE_KEY")
        self.supabase: Client = create_client(url, key)
        print("PlayerCog carregado e conectado ao Supabase.")

    @commands.command(name='start', help='Inicia sua aventura Pokémon. Ex: !start Ash')
    async def start_adventure(self, ctx: commands.Context, *, trainer_name: str):
       
        Registra um novo treinador no banco de dados.
        Este comando é o ponto de entrada para qualquer novo jogador.
        
        discord_id = ctx.author.id

        # 1. Verificar se o jogador já existe
        try:
            response = self.supabase.table('players').select('discord_id').eq('discord_id', discord_id).execute()
            if response.data:
                await ctx.send(f"Olá novamente, {ctx.author.mention}! Você já iniciou sua jornada.")
                return
        except Exception as e:
            await ctx.send(f"Ocorreu um erro ao verificar seus dados. Por favor, tente novamente. Detalhe: {e}")
            return

        # 2. Se não existe, criar o novo jogador com dados iniciais
        player_data = {
            'discord_id': discord_id,
            'trainer_name': trainer_name,
            'money': 1000,  # Dinheiro inicial
            'badges': 0,
            'current_region': 'Pallet Town',
            'masterballs_owned': 0
        }

        try:
            insert_response = self.supabase.table('players').insert(player_data).execute()
            
            # Verifica se a inserção foi bem-sucedida
            if insert_response.data:
                await ctx.send(f"🎉 Bem-vindo ao mundo Pokémon, Treinador(a) **{trainer_name}**! 🎉\nSua aventura começa agora em Pallet Town. Use `!help` para ver os comandos disponíveis.")
            else:
                 await ctx.send("Houve um problema ao criar seu personagem. A resposta do banco de dados estava vazia.")

        except Exception as e:
            await ctx.send(f"Não foi possível registrar sua aventura. Ocorreu um erro de banco de dados. Detalhe: {e}")
            print(f"Erro ao inserir jogador: {e}")


async def setup(bot: commands.Bot):
    Função de setup para carregar o Cog no bot principal.
    await bot.add_cog(PlayerCog(bot))
    
"""    