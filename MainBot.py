import discord
import os
import asyncio
from dotenv import load_dotenv
from discord.ext import commands # <--- Importante ter 'commands'

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()
Token = os.getenv('DISCORD_TOKEN')

# Define as intents que seu bot precisa
intents = discord.Intents.default()
intents.message_content = True 

# AQUI ESTÁ A CORREÇÃO: Usar commands.Bot em vez de discord.Client
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user}')
    print('------')

async def load_cogs():
    """Encontra e carrega todas as extensões (cogs) na pasta /cogs."""
    # O caminho é relativo a onde o main.py está.
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py'):
            try:
                # O nome da extensão é 'cogs.' + nome do arquivo sem '.py'
                await bot.load_extension(f'cogs.{filename[:-3]}')
                print(f'Cog {filename} carregado com sucesso.')
            except Exception as e:
                print(f'Falha ao carregar o cog {filename}. Erro: {e}')

async def main():
    """Função principal para carregar os cogs e iniciar o bot."""
    async with bot:
        await load_cogs()
        await bot.start(Token)

# Ponto de entrada para executar o bot
if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot desligado.")