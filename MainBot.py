import discord
from supabase import create_client, Client
import os
from dotenv import load_dotenv # 1. Importar a biblioteca

# 2. Carregar as variáveis do arquivo .env
load_dotenv()

# --- CONFIGURAÇÃO SEGURA DAS CREDENCIAIS ---
# 3. Pegar as credenciais do ambiente (carregadas do .env)
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Verificação de segurança: Confirma se as variáveis foram carregadas
if not all([DISCORD_TOKEN, SUPABASE_URL, SUPABASE_KEY]):
    print("ERRO CRÍTICO: As credenciais (DISCORD_TOKEN, SUPABASE_URL, SUPABASE_KEY) não foram encontradas.")
    print("Verifique se você criou o arquivo .env e preencheu as variáveis corretamente.")
    exit()

# --- CONFIGURAÇÃO DO SUPABASE ---
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("Conexão com Supabase bem-sucedida!")
except Exception as e:
    print(f"Erro ao conectar com Supabase: {e}")
    exit()

# --- CONFIGURAÇÃO DO BOT DISCORD ---
intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'Bot conectado como {client.user}')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.content.lower() == '!treinadores':
        try:
            response = supabase.table('players').select('*').execute()

            if response.data:
                embed = discord.Embed(
                    title="🏆 Lista de Treinadores 🏆",
                    description="Aqui estão todos os treinadores registrados no banco de dados:",
                    color=discord.Color.blue()
                )
                for trainer in response.data:
                    trainer_name = trainer.get('trainer_name', 'Nome não encontrado')
                    current_region = trainer.get('current_region', 'Região não definida')
                    embed.add_field(
                        name=f"👤 {trainer_name}",
                        value=f"📍 Região Atual: {current_region}",
                        inline=False
                    )
                await message.channel.send(embed=embed)
            else:
                await message.channel.send("Nenhum treinador encontrado no banco de dados.")

        except Exception as e:
            print(f"Erro ao buscar dados no Supabase: {e}")
            await message.channel.send("Ocorreu um erro ao buscar os dados dos treinadores.")

# --- INICIALIZAÇÃO DO BOT ---
client.run(DISCORD_TOKEN)