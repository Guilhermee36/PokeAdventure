import discord
import os
from dotenv import load_dotenv
from discord.ext import commands # <--- 1. Importe 'commands'

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()
Token = os.getenv('DISCORD_TOKEN')

# Define as intents que seu bot precisa
intents = discord.Intents.default()
intents.message_content = True 

# 2. Use commands.Bot e defina um prefixo para os comandos
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user}')
    
# Com commands.Bot, você pode criar comandos assim:
@bot.command()
async def ping(ctx): # 'ctx' é o contexto, que inclui a mensagem, o canal, etc.
    await ctx.send('Pong!')

bot.run(Token)