import discord
import os
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# Cria a instância do bot
# Usamos Intents para garantir que o bot receba os eventos que precisa
intents = discord.Intents.default()
bot = discord.Bot(intents=intents)

# Carrega todas as Cogs da pasta /cogs
# O bot irá procurar por arquivos .py na pasta especificada
for filename in os.listdir('./cogs'):
    if filename.endswith('.py'):
        # O formato para carregar é 'pasta.nome_do_arquivo' sem o .py
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