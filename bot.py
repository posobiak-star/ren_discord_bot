import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
from datetime import datetime, timedelta, timezone
import os

# Intents
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------------
# 会社一覧ビュー
# ---------------------
class CompanyPaginator(discord.ui.View):
    def __init__(self, companies, owner_id):
        super().__init__(timeout=None)
        self.original_companies = list(companies)  # 元の順番（設立順）
        self.companies = list(companies)
        self.page = 0
        self.max_per_page = 5
        self.owner_id = owner_id
        self.sort_mode = "設立日順"

    def get_embed(self):
        start = self.page * self.max_per_page
        end = start + self.max_per_page
        embed = discord.Embed(title=f"会社一覧（{self.sort_mode}）")
        for company in self.companies[start:end]:
            embed.add_field(
                name=f"{company['name']}({company['id']})",
                value=f"資本金 {company['assets']}コイン\n給料 {company['salary']}コイン",
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
        self.page = (self.page - 1) % ((len(self.companies) - 1)//self.max_per_page + 1)
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    # → 右ボタン
    @discord.ui.button(label="➡️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("他のユーザーのボタンは操作できません", ephemeral=True)
            return
        self.page = (self.page + 1) % ((len(self.companies) - 1)//self.max_per_page + 1)
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    # 並び替えセレクト
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

# ---------------------
# /company_list コマンド
# ---------------------
@bot.tree.command(name="company_list", description="会社情報一覧を表示")
async def company_list(interaction: discord.Interaction):
    async with aiohttp.ClientSession() as session:
        async with session.get("https://api.takasumibot.com/v3/companylist/") as resp:
            companies = await resp.json()

    view = CompanyPaginator(companies, interaction.user.id)
    await interaction.response.send_message(embed=view.get_embed(), view=view)

# ---------------------
# /company_data コマンド
# ---------------------
@bot.tree.command(name="company_data", description="会社の収支情報を表示")
@app_commands.describe(
    company_id="会社ID (10文字)",
    period="表示する期間"
)
@app_commands.choices(period=[
    app_commands.Choice(name="7日", value="7d"),
    app_commands.Choice(name="3日", value="3d"),
    app_commands.Choice(name="1日", value="1d"),
    app_commands.Choice(name="24時間", value="12h"),
    app_commands.Choice(name="6時間", value="6h")
])
async def company_data(interaction: discord.Interaction, company_id: str, period: app_commands.Choice[str] = None):
    if len(company_id) != 10:
        await interaction.response.send_message("会社IDは10文字で指定してください", ephemeral=True)
        return

    # 期間設定
    now = datetime.now(timezone.utc)
    if period is None:
        delta = timedelta(days=1)
        period_text = "1日"
    else:
        val = period.value
        if val.endswith("d"):
            delta = timedelta(days=int(val[:-1]))
            period_text = val[:-1] + "日"
        elif val.endswith("h"):
            delta = timedelta(hours=int(val[:-1]))
            period_text = val[:-1] + "時間"
    since_time = now - delta

    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.takasumibot.com/v3/company/{company_id}") as resp:
            if resp.status != 200:
                await interaction.response.send_message("会社情報を取得できませんでした", ephemeral=True)
                return
            company = await resp.json()

        async with session.get(f"https://api.takasumibot.com/v3/companyHistory/{company_id}") as resp:
            if resp.status != 200:
                await interaction.response.send_message("会社履歴を取得できませんでした", ephemeral=True)
                return
            history = await resp.json()

    # 期間内の履歴を抽出（UTC aware）
    filtered_history = [
        h for h in history
        if datetime.fromisoformat(h["tradedAt"].replace("Z", "+00:00")) >= since_time
    ]

    total_income = sum(h["amount"] for h in filtered_history if h["amount"] > 0)
    total_expense = -sum(h["amount"] for h in filtered_history if h["amount"] < 0)

    # ユーザー別集計
    user_summary = {}
    for h in filtered_history:
        uid = h.get("userId")
        if uid:
            if uid not in user_summary:
                user_summary[uid] = {"total": 0, "count": 0}
            if h["amount"] > 0:
                user_summary[uid]["total"] += h["amount"]
                user_summary[uid]["count"] += 1

    # 埋め込み作成
    embed = discord.Embed(
        title=f"💮 {company['name']} 会社の収支情報 ({period_text})",
        color=discord.Color.blue()
    )
    embed.add_field(name="会社ID", value=company["id"], inline=False)
    embed.add_field(name="資本金", value=company["assets"], inline=True)
    embed.add_field(name="時給", value=company["salary"], inline=True)
    embed.add_field(name="収入", value=total_income, inline=True)
    embed.add_field(name="支出", value=total_expense, inline=True)

    if user_summary:
        lines = [f"{uid}　{info['total']}　{info['count']}" for uid, info in user_summary.items()]
        embed.add_field(name="ユーザー別収入", value="\n".join(lines), inline=False)

    await interaction.response.send_message(embed=embed)

# ---------------------
# 起動
# ---------------------
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}!")

token = os.getenv("DISCORD_TOKEN")
if not token:
    raise ValueError("環境変数 DISCORD_TOKEN が設定されていません")
bot.run(token)
