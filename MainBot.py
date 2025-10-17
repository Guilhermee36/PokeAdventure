# main.py

import discord
import os
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURAÇÃO (como você já tem) ---
intents = discord.Intents.default()
intents.message_content = True  # Essencial para ler o conteúdo das mensagens
client = discord.Client(intents=intents)

# --- EVENTO DE CONEXÃO ---
@client.event
async def on_ready():
    print(f'Logado com sucesso como {client.user.name}')
    print('------')

# --- EVENTO DE MENSAGEM (NOVO) ---
# Esta função é chamada toda vez que uma mensagem é enviada em um canal
# que o bot consegue ver.
@client.event
async def on_message(message):
    """
    Processa mensagens recebidas.
    """
    # 1. Ignorar mensagens do próprio bot
    # Isso previne que o bot entre em um loop infinito de respostas.
    if message.author == client.user:
        return

    # 2. Comando de teste !ping
    # Verifica se a mensagem é exatamente '!ping'.
    if message.content.lower() == '!ping':
        # Envia a mensagem 'Pong!' de volta para o mesmo canal.
        await message.channel.send('Pong!')

# --- INICIALIZAÇÃO DO BOT ---
client.run(os.getenv('TOKEN'))