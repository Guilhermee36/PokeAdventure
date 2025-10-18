import discord
import os
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()
Token = os.getenv('DISCORD_TOKEN')

bot = discord.client(intents=discord.Intents.all())

@bot.event
async def on_ready():   
    print(f'Bot conectado como {bot.user}')
    
    @bot.event
    async def on_message(message):
        if message.author == bot.user:
            return
        
        if message.content.startswith('!ping'):
            await message.channel.send('Pong!')
            
bot.run(Token)