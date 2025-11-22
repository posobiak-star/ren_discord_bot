import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import os

# Intentsの設定
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


# ページング用カスタムビュー
class CompanyPaginator(discord.ui.View):
    def __init__(self, companies, owner_id):
        super().__init__(timeout=None)
        self.companies = companies
        self.page = 0
        self.max_per_page = 10
        self.owner_id = owner_id  # ← 追加：コマンド実行者のIDを保持

    def get_embed(self):
        start = self.page * self.max_per_page
        end = start + self.max_per_page
        embed = discord.Embed(title="会社一覧")
        for company in self.companies[start:end]:
            embed.add_field(
                name=f"{company['name']}({company['id']})",
                value=(
                    f"{company['description']}\n\n"  # ← 説明追加
                    f"資本金 {company['assets']}コイン\n"
                    f"給料 {company['salary']}コイン"
                ),
                inline=False
            )
        embed.set_footer(text=f"ページ {self.page+1}/{(len(self.companies)-1)//self.max_per_page + 1}")
        return embed

    
    # 戻るボタン
    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        # ← 追加：他のユーザーが触ったら拒否
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("他のユーザのコマンドは操作できません", ephemeral=True)
            return
        if self.page > 0:
            self.page -= 1
        else:
            self.page = (len(self.companies) - 1) // self.max_per_page
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    # 次へボタン
    @discord.ui.button(label="➡️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        # ← 追加：他のユーザーが触ったら拒否
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("他のユーザのコマンドは操作できません", ephemeral=True)
            return
        if (self.page + 1) * self.max_per_page < len(self.companies):
            self.page += 1
        else:
            self.page = 0
        await interaction.response.edit_message(embed=self.get_embed(), view=self)


# /company list コマンド
@bot.tree.command(name="company_list", description="会社情報一覧")
async def company_list(interaction: discord.Interaction):
    async with aiohttp.ClientSession() as session:
        async with session.get("https://api.takasumibot.com/v3/companylist/") as resp:
            companies = await resp.json()
view = CompanyPaginator(companies, interaction.user.id)
    await interaction.response.send_message(embed=view.get_embed(), view=view)


# 起動イベント
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}!")

# トークン取得と起動
token = os.getenv("DISCORD_TOKEN")
if not token:
    raise ValueError("環境変数 DISCORD_TOKEN が設定されていません")
bot.run(token)
