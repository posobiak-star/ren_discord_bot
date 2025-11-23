import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
from datetime import datetime, timedelta, timezone
import os

ADMIN_ID = 1250410219662606437

# ==================== 環境変数の読み込み ====================
if os.environ.get("RENDER") != "true":
    from dotenv import load_dotenv
    load_dotenv()

token = os.environ.get("DISCORD_TOKEN")
if token is None:
    raise RuntimeError("DISCORD_TOKEN が設定されていません。ローカルなら .env に、Render なら環境変数に追加してください。")

# ==================== Intents ====================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ==================== CompanyPaginator ====================
class CompanyPaginator(discord.ui.View):
    def __init__(self, companies, owner_id):
        super().__init__(timeout=180)
        self.original_companies = list(companies)
        self.companies = list(companies)
        self.page = 0
        self.max_per_page = 5
        self.owner_id = owner_id
        self.sort_mode = "設立日順"

    def get_embed(self):
        start = self.page * self.max_per_page
        end = start + self.max_per_page
        embed = discord.Embed(
            title=f"会社一覧（{self.sort_mode}）",
            color=discord.Color.red()
        )
        for company in self.companies[start:end]:
            embed.add_field(
                name=f"{company['name']} ({company['id']})",
                value=f"資本金: {company['assets']}コイン\n時給: {company['salary']}コイン",
                inline=False
            )
        total_pages = (len(self.companies) - 1) // self.max_per_page + 1
        embed.set_footer(text=f"ページ {self.page + 1}/{total_pages}")
        return embed

# ==================== /company_list コマンド ====================
@bot.tree.command(name="company_list", description="会社情報一覧を表示")
async def company_list(interaction: discord.Interaction):
    async with aiohttp.ClientSession() as session:
        async with session.get("https://api.takasumibot.com/v3/companylist/") as resp:
            companies = await resp.json()

    view = CompanyPaginator(companies, interaction.user.id)
    await interaction.response.send_message(embed=view.get_embed(), view=view)

# ==================== /company_money コマンド ====================
@bot.tree.command(name="company_money", description="会社の収支情報を表示")
@app_commands.describe(
    company_id="会社ID（10文字）",
    period="表示する期間"
)
@app_commands.choices(period=[
    app_commands.Choice(name="7日", value="7d"),
    app_commands.Choice(name="3日", value="3d"),
    app_commands.Choice(name="1日", value="1d"),
    app_commands.Choice(name="12時間", value="12h"),
    app_commands.Choice(name="6時間", value="6h"),
])
async def company_data(interaction: discord.Interaction, company_id: str, period: app_commands.Choice[str] = None):
    if len(company_id) != 10:
        return await interaction.response.send_message("会社IDは10文字で指定してください", ephemeral=True)

    delta = timedelta(days=1)
    period_text = "1日"
    if period:
        val = period.value
        if val.endswith("d"):
            delta = timedelta(days=int(val[:-1]))
            period_text = f"{val[:-1]}日"
        elif val.endswith("h"):
            delta = timedelta(hours=int(val[:-1]))
            period_text = f"{val[:-1]}時間"

    now = datetime.now(timezone.utc)
    since_time = now - delta

    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.takasumibot.com/v3/company/{company_id}") as resp:
            if resp.status != 200:
                return await interaction.response.send_message("会社情報の取得に失敗しました", ephemeral=True)
            company = await resp.json()

        async with session.get(f"https://api.takasumibot.com/v3/companyHistory/{company_id}") as resp:
            if resp.status != 200:
                return await interaction.response.send_message("会社履歴の取得に失敗しました", ephemeral=True)
            history = await resp.json()

    filtered_history = []
    for h in history:
        try:
            traded_at = datetime.fromisoformat(h["tradedAt"].replace("Z", "+00:00"))
            if traded_at >= since_time:
                filtered_history.append(h)
        except:
            continue

    total_income = sum(h["amount"] for h in filtered_history if h["amount"] > 0)
    total_expense = -sum(h["amount"] for h in filtered_history if h["amount"] < 0)

    user_summary = {}
    for h in filtered_history:
        uid = h.get("userId")
        if uid:
            if uid not in user_summary:
                user_summary[uid] = {"total": 0, "count": 0}
            if h["amount"] > 0:
                user_summary[uid]["total"] += h["amount"]
                user_summary[uid]["count"] += 1

    embed = discord.Embed(
        title=f"💮 {company['name']} の収支情報（{period_text}）",
        color=discord.Color.red()
    )
    embed.add_field(name="会社ID", value=company["id"], inline=False)
    embed.add_field(name="資本金", value=f"{company['assets']}コイン", inline=False)
    embed.add_field(name="時給", value=f"{company['salary']}コイン", inline=False)
    embed.add_field(name="収入", value=f"{total_income}コイン", inline=True)
    embed.add_field(name="支出", value=f"{total_expense}コイン", inline=True)

    if user_summary:
        lines = [f"<@{uid}> {info['total']}コイン {info['count']}回" 
                 for uid, info in sorted(user_summary.items(), key=lambda x: x[1]["count"], reverse=True)]
        embed.add_field(name="ユーザー別収入", value="\n".join(lines), inline=False)

    await interaction.response.send_message(embed=embed)

# ==================== /forms コマンド ====================
@bot.tree.command(name="forms", description="意見や要望を送信します")
async def forms(interaction: discord.Interaction):
    modal = OpinionModalHandler(interaction.user.id)
    await interaction.response.send_modal(modal)

# ==================== Bot Ready ====================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

bot.run(token)
