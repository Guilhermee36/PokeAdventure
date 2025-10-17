# main.py

import discord
from discord.ext import commands  # Importa a extensão de comandos
import os
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURAÇÃO ---
# Define as permissões (intents) que o bot precisa.
intents = discord.Intents.default()
intents.message_content = True  # Essencial para ler o conteúdo das mensagens

# Cria uma instância do Bot, em vez de um Client.
# O command_prefix define o caractere que ativa um comando (ex: '!')
bot = commands.Bot(command_prefix='!', intents=intents)

# --- EVENTO DE CONEXÃO ---
# Este evento é chamado quando o bot se conecta com sucesso ao Discord.
@bot.event
async def on_ready():
    print(f'Logado com sucesso como {bot.user.name}')
    print(f'ID do Bot: {bot.user.id}')
    print('------')

# --- COMANDO DE TESTE ---
# Usamos o decorador @bot.command() para registrar um novo comando.
# O nome da função vira o nome do comando.
@bot.command(name='ping')
async def ping_command(ctx):
    """
    Comando de teste que responde com 'Pong!'.
    'ctx' é o contexto, contendo informações como o canal, autor, etc.
    """
    await ctx.send('Pong!')

# --- INICIALIZAÇÃO DO BOT ---
# Usa o token do arquivo .env para iniciar o bot.
bot.run(os.getenv('DISCORD_TOKEN'))