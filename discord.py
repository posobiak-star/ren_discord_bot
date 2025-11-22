# bot.py
import os
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

intents = commands.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Bot logged in as: {bot.user}")

@bot.command()
async def ping(ctx):
    await ctx.send("pong!")

bot.run(TOKEN)

