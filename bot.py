import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import os

# Intents
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# ページング用ビュー
class CompanyPaginator(discord.ui.View):
    def __init__(self, companies, owner_id):
        super().__init__(timeout=None)
        self.companies = companies
        self.original_companies = list(companies)  # 元の順番（設立順）
        self.page = 0
        self.max_per_page = 5
        self.owner_id = owner_id
        self.sort_mode = "設立日順"  # 現在の並び順をタイトルに表示
        
    def get_embed(self):
        start = self.page * self.max_per_page
        end = start + self.max_per_page
        
        # 並び順をタイトルに表示
        embed = discord.Embed(title=f"会社一覧（{self.sort_mode}）")
        for company in self.companies[start:end]:
            embed.add_field(
                name=f"{company['name']}({company['id']})",
                value=(
                    f"資本金 {company['assets']}コイン\n"
                    f"給料 {company['salary']}コイン"
                ),
                inline=False
            )
        embed.set_footer(
            text=f"ページ {self.page+1}/{(len(self.companies)-1)//self.max_per_page + 1}"
        )
        return embed

    # ← 左ボタン
    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("他のユーザーのボタンは操作できません", ephemeral=True)
            return
        if self.page > 0:
            self.page -= 1
        else:
            self.page = (len(self.companies) - 1) // self.max_per_page  # 最後
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    # → 右ボタン
    @discord.ui.button(label="➡️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("他のユーザーのボタンは操作できません", ephemeral=True)
            return
        if (self.page + 1) * self.max_per_page < len(self.companies):
            self.page += 1
        else:
            self.page = 0  # 最初

        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    # ▼ 並び替えセレクト（矢印の右側に出る）
    @discord.ui.select(
        placeholder="並び替えを選択",
        options=[
            discord.SelectOption(label="設立日順（デフォルト）", value="created"),
            discord.SelectOption(label="資本金が高い順", value="assets"),
            discord.SelectOption(label="給料が高い順", value="salary"),
        ]
    )
    async def sort_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("他のユーザーのボタンは操作できません", ephemeral=True)
            return
        selected = select.values[0]
        if selected == "created":
            self.companies = list(self.original_companies)
            self.sort_mode = "設立日順"
        elif selected == "assets":
            self.companies.sort(key=lambda x: x["assets"], reverse=True)
            self.sort_mode = "資本金順"
        elif selected == "salary":
            self.companies.sort(key=lambda x: x["salary"], reverse=True)
            self.sort_mode = "給料順"
        self.page = 0
        await interaction.response.edit_message(embed=self.get_embed(), view=self)


# /company list コマンド
@bot.tree.command(name="company_list", description="会社情報一覧を表示")
async def company_list(interaction: discord.Interaction):
    async with aiohttp.ClientSession() as session:
        async with session.get("https://api.takasumibot.com/v3/companylist/") as resp:
            companies = await resp.json()
    # ← ここが関数内に入っていなかったのがエラーの原因！
    view = CompanyPaginator(companies, interaction.user.id)
    await interaction.response.send_message(
        embed=view.get_embed(),
        view=view
    )


# 起動
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}!")

token = os.getenv("DISCORD_TOKEN")
if not token:
    raise ValueError("環境変数 DISCORD_TOKEN が設定されていません")
bot.run(token)
