import discord
import os
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()
Token = os.getenv('DISCORD_TOKEN')

# Correção 1: 'discord.Client' com 'C' maiúsculo
# Correção 2: Ativar as intents necessárias explicitamente é uma boa prática
intents = discord.Intents.default()
intents.message_content = True # Habilita a intent para ler o conteúdo das mensagens

bot = discord.Client(intents=intents)

@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user}')

# Correção 3: O evento 'on_message' deve estar fora do 'on_ready'
@bot.event
async def on_message(message):
    # Ignora mensagens do próprio bot
    if message.author == bot.user:
        return
    
    # Responde ao comando !ping
    if message.content.startswith('!ping'):
        await message.channel.send('Pong!')
        
bot.run(Token)