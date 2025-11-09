# MainBot.py (trecho essencial)
import os, asyncio, discord
from discord.ext import commands
from dotenv import load_dotenv

from supabase import create_client, Client  # pip install supabase

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command("help")

async def load_cogs():
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py"):
            try:
                await bot.load_extension(f"cogs.{filename[:-3]}")
                print(f"Cog {filename} carregado com sucesso.")
            except Exception as e:
                print(f"Falha ao carregar o cog {filename}. Erro: {e}")

async def main():
    async with bot:
        # >>> injeta o client do Supabase aqui <<<
        bot.supabase = create_client(SUPABASE_URL, SUPABASE_KEY)  # síncrono, mas ok

        await load_cogs()
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
