# main.py

import os
import discord
import asyncio
from discord.ext import commands  # Importa a extensão de comandos
from discord import ui           # Importa a biblioteca de UI (botões, menus, etc.)
from dotenv import load_dotenv
from supabase import create_client, Client

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# --- Configuração das Conexões ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not all([DISCORD_TOKEN, SUPABASE_URL, SUPABASE_KEY]):
    print("Erro: Uma ou mais variáveis de ambiente não foram definidas.")
    exit()

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("Conexão com a Supabase estabelecida com sucesso.")
except Exception as e:
    print(f"Falha ao conectar com a Supabase: {e}")
    exit()

# --- Configuração do Bot do Discord ---

# Define as "intenções" do bot
intents = discord.Intents.default()
intents.message_content = True

# Cria a instância do bot com um prefixo de comando '!'
# Usar commands.Bot é a prática recomendada para bots com comandos
bot = commands.Bot(command_prefix='!', intents=intents)

# --- Componentes de UI para Teste ---

# Uma 'View' é um container para componentes de UI como botões e menus.
# Ela gerencia as interações dos usuários com esses componentes.
class TestUIView(ui.View):
    def __init__(self):
        # O timeout define por quanto tempo os botões ficarão ativos (em segundos).
        super().__init__(timeout=180) 

    # Decorador para criar um botão.
    # 'label' é o texto do botão, 'style' é a cor, 'emoji' é opcional.
    @ui.button(label="Sucesso", style=discord.ButtonStyle.success, emoji="✅")
    async def success_button(self, interaction: discord.Interaction, button: ui.Button):
        # interaction.response.send_message envia uma resposta à interação.
        # 'ephemeral=True' faz com que a mensagem seja visível apenas para quem clicou.
        await interaction.response.send_message("Você clicou no botão de sucesso!", ephemeral=True)

    @ui.button(label="Perigo", style=discord.ButtonStyle.danger, emoji="❌")
    async def danger_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("Você clicou no botão de perigo!", ephemeral=True)

    @ui.button(label="Link", style=discord.ButtonStyle.link, emoji="🔗")
    async def link_button(self, interaction: discord.Interaction, button: ui.Button):
        # Botões de link não precisam de uma resposta, eles simplesmente abrem a URL.
        # O Discord não envia um evento de 'interaction' para o bot quando um botão de link é clicado.
        pass
        
    # Decorador para criar um menu de seleção (dropdown).
    # 'placeholder' é o texto que aparece antes de uma opção ser escolhida.
    @ui.select(
        placeholder="Escolha uma opção no menu...",
        options=[
            discord.SelectOption(label="Ver Pokédex", description="Abre a sua Pokédex.", emoji="📚"),
            discord.SelectOption(label="Abrir Mochila", description="Acessa os seus itens.", emoji="🎒"),
            discord.SelectOption(label="Escolher Pokémon", description="Seleciona um Pokémon da sua equipe.", emoji="🐾")
        ]
    )
    async def select_menu(self, interaction: discord.Interaction, select: ui.Select):
        # 'select.values[0]' pega o 'label' da opção que o usuário escolheu.
        chosen_option = select.values[0]
        await interaction.response.send_message(f"Você escolheu: **{chosen_option}**", ephemeral=True)


# --- Eventos e Comandos do Bot ---

# Evento que é disparado quando o bot fica online
@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user}')
    print('------')

# Comando de teste simples, agora usando o decorador @bot.command()
@bot.command(name='hello')
async def hello_command(ctx):
    # 'ctx' (contexto) contém informações sobre a mensagem, autor, canal, etc.
    await ctx.send(f'Olá, {ctx.author.name}!')

# Comando para testar os componentes de UI (botões e menu)
@bot.command(name='test_ui')
async def test_ui_command(ctx):
    # Cria uma mensagem Embed para uma aparência mais agradável
    embed = discord.Embed(
        title="Painel de Teste de Interface",
        description="Aqui estão alguns exemplos de componentes de UI que podemos usar no jogo. Interaja com eles!",
        color=discord.Color.blue()
    )
    
    # Cria uma instância da nossa View
    view = TestUIView()
    
    # Envia a mensagem com o Embed e a View (que contém os botões/menu)
    await ctx.send(embed=embed, view=view)


# Inicia a execução do bot usando o token
bot.run(DISCORD_TOKEN)