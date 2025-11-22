import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import os

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# ページング用カスタムビュー
class CompanyPaginator(discord.ui.View):
    def __init__(self, companies):
        super().__init__(timeout=None)
        self.companies = companies
        self.page = 0
        self.max_per_page = 10

    def get_embed(self):
        start = self.page * self.max_per_page
        end = start + self.max_per_page
        embed = discord.Embed(title="会社一覧")
        for company in self.companies[start:end]:
            embed.add_field(
                name=f"{company['name']}({company['id']})",
                value=f"資本金 {company['assets']}コイン\n給料 {company['salary']}コイン",
                inline=False
            )
        embed.set_footer(text=f"ページ {self.page+1}/{(len(self.companies)-1)//self.max_per_page + 1}")
        return embed

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if (self.page + 1) * self.max_per_page < len(self.companies):
            self.page += 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

# /company list コマンド
@bot.tree.command(name="company", description="会社情報一覧")
@app_commands.describe(action="list を指定してください")
async def company(interaction: discord.Interaction, action: str):
    if action != "list":
        await interaction.response.send_message("無効なアクションです", ephemeral=True)
        return

    async with aiohttp.ClientSession() as session:
        async with session.get("https://api.takasumibot.com/v3/companylist/") as resp:
            companies = await resp.json()

    view = CompanyPaginator(companies)
    await interaction.response.send_message(embed=view.get_embed(), view=view)

# 起動
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}!")

token = os.getenv("DISCORD_TOKEN")
bot.run(token)
