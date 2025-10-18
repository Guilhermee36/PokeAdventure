import discord
import os
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# --- CORREÇÃO AQUI ---
# 1. Primeiro, defina quais "intenções" o seu bot terá.
#    'default()' é uma boa configuração inicial.
intents = discord.Intents.default()

# 2. Agora, crie a instância do bot, passando as 'intents' que você acabou de definir.
bot = discord.Bot(intents=intents)
# --------------------

# Carrega todas as Cogs da pasta /cogs
for filename in os.listdir('./cogs'):
    if filename.endswith('.py'):
        bot.load_extension(f'cogs.{filename[:-3]}')
        print(f"✅ Cog '{filename[:-3]}' carregada com sucesso.")

@bot.event
async def on_ready():
    """Evento que é acionado quando o bot está online e pronto."""
    print(f'🤖 {bot.user} está online e pronto para a aventura!')
    print(f'ID do Bot: {bot.user.id}')
    print('------')

# Inicia o bot usando o token do arquivo .env
bot.run(os.getenv('DISCORD_TOKEN'))