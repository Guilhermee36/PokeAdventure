# main.py

import os
import random
import discord
from dotenv import load_dotenv
from supabase import create_client, Client
import openai # A importação pode ficar aqui para uso futuro, sem inicializar o cliente.

# Carrega as variáveis de ambiente do arquivo .env para o ambiente de execução
load_dotenv()

# --- Configuração das Conexões ---

# Busca as credenciais das variáveis de ambiente
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Validação para garantir que as variáveis essenciais foram carregadas
if not all([DISCORD_TOKEN, SUPABASE_URL, SUPABASE_KEY]):
    print("Erro: Uma ou mais variáveis de ambiente (DISCORD_TOKEN, SUPABASE_URL, SUPABASE_KEY) não foram definidas.")
    exit()

# Inicializa o cliente Supabase para interagir com seu banco de dados
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("Conexão com a Supabase estabelecida com sucesso.")
except Exception as e:
    print(f"Falha ao conectar com a Supabase: {e}")
    exit()


# --- Configuração do Bot do Discord ---

# Define as "intenções" do bot (quais eventos ele deve escutar)
intents = discord.Intents.default()
intents.message_content = True  # Permite que o bot leia o conteúdo das mensagens

# Cria a instância do cliente do bot
client = discord.Client(intents=intents)

# Evento que é disparado quando o bot fica online
@client.event
async def on_ready():
    print(f'Bot conectado como {client.user}')
    print('------')

# Evento que é disparado a cada nova mensagem em um canal que o bot pode ver
@client.event
async def on_message(message):
    # Impede que o bot responda às suas próprias mensagens
    if message.author == client.user:
        return

    # Comando de exemplo para testar o bot
    if message.content.startswith('$hello'):
        await message.channel.send(f'Olá, {message.author.name}!')

# Inicia a execução do bot usando o token
client.run(DISCORD_TOKEN)