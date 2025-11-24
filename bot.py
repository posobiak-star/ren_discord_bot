import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
from datetime import datetime, timedelta, timezone
import os
import json
from functools import wraps

ADMIN_ID = 1250410219662606437

# ==================== 環境変数の読み込み ====================
if os.environ.get("RENDER") != "true":
    from dotenv import load_dotenv
    load_dotenv()

token = os.environ.get("DISCORD_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if token is None:
    raise RuntimeError("DISCORD_TOKEN が設定されていません。")
if SUPABASE_URL is None or SUPABASE_KEY is None:
    raise RuntimeError("SUPABASE_URL または SUPABASE_KEY が設定されていません。")

# ==================== Intents ====================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ==================== 購入チェック（Supabase + API） ====================

async def check_user_access(user_id: int) -> bool:
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

    # --- Supabase で購入チェック ---
    async with aiohttp.ClientSession() as session:
        url = f"{SUPABASE_URL}/rest/v1/users?user_id=eq.{user_id}&select=*"
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data and data[0].get("has_access"):
                    return True

    # --- Supabaseに無ければ API から確認 ---
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.takasumibot.com/v3/history/{user_id}") as resp:
            if resp.status != 200:
                return False
            api_data = await resp.json()

    owns_ren = any(
        h.get("amount") == -50000 and "REN+" in h.get("reason", "")
        for h in api_data
    )

    # --- 購入済みなら Supabase に自動保存 ---
    if owns_ren:
        payload = [{"user_id": user_id, "has_access": True}]
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{SUPABASE_URL}/rest/v1/users",
                                     headers={**headers, "Prefer": "resolution=merge-duplicates"},
                                     data=json.dumps(payload)) as resp:
                if resp.status not in (200, 201):
                    print(f"Supabase への自動保存に失敗しました: {resp.status}")
        return True

    return False

# ==================== デコレータ修正 ====================
# defer_ephemeral パラメータを追加し、deferの公開・非公開を制御できるようにしました。
def require_purchase(ignore_modal: bool = False, defer_ephemeral: bool = False):
    """購入チェックデコレータ。まず購入チェック → 成功したら defer"""
    def decorator(func):
        @wraps(func)
        async def wrapper(interaction: discord.Interaction, *args, **kwargs):
            # --- まず購入チェックだけ実行 ---
            ok = await check_user_access(interaction.user.id)
            if not ok:
                # 失敗時は必ず response で ephemeral 送信
                return await interaction.response.send_message(
                    "Takasumi botで購入してからご利用ください",
                    ephemeral=True
                )

            # --- 購入済みなら defer（後続処理用） ---
            if not ignore_modal:
                try:
                    # defer_ephemeral パラメータで defer の公開・非公開を設定
                    await interaction.response.defer(ephemeral=defer_ephemeral)
                except Exception:
                    pass  # まれに既に defer 済みの場合あり

            return await func(interaction, *args, **kwargs)
        return wrapper
    return decorator

# ==================== UI クラス（会社一覧表示用） ====================

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

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("他のユーザーのボタンは使えません", ephemeral=True)
        total_pages = (len(self.companies) - 1) // self.max_per_page + 1
        self.page = (self.page - 1) % total_pages
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("他のユーザーのボタンは使えません", ephemeral=True)
        total_pages = (len(self.companies) - 1) // self.max_per_page + 1
        self.page = (self.page + 1) % total_pages
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

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
            return await interaction.response.send_message("他のユーザーのボタンは使えません", ephemeral=True)
        v = select.values[0]
        if v == "created":
            self.companies = list(self.original_companies)
            self.sort_mode = "設立日順"
        elif v == "assets":
            self.companies.sort(key=lambda x: x["assets"], reverse=True)
            self.sort_mode = "資本金順"
        elif v == "salary":
            self.companies.sort(key=lambda x: x["salary"], reverse=True)
            self.sort_mode = "給料順"
        self.page = 0
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

# ==================== /company_list ====================

# /company_list は結果が公開で問題ないため、defer_ephemeral=False (デフォルト) のまま
@bot.tree.command(name="company_list", description="会社情報一覧を表示")
@require_purchase()
async def company_list(interaction: discord.Interaction):
    async with aiohttp.ClientSession() as session:
        async with session.get("https://api.takasumibot.com/v3/companylist/") as resp:
            companies = await resp.json()

    view = CompanyPaginator(companies, interaction.user.id)
    # デコレータで既に defer 済みなので followup.send を使用 (ephemeral=Falseで公開)
    await interaction.followup.send(embed=view.get_embed(), view=view, ephemeral=False)

# ==================== /company_money ====================

@bot.tree.command(name="company_money", description="会社の収支情報を表示")
# defer_ephemeral=False に変更し、処理中のメッセージを公開にする
@require_purchase(defer_ephemeral=False)
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
    # --- バリデーション（エラーメッセージは常に使用者のみに表示） ---
    if len(company_id) != 10:
        # 公開の 'Bot is thinking...' を削除
        await interaction.delete_original_response() 
        
        # defer後: 非公開のフォローアップでエラーを送信
        return await interaction.followup.send("会社IDは10文字で指定してください", ephemeral=True)

    # --- 期間計算 ---
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

    # --- API取得 ---
    async with aiohttp.ClientSession() as session:
        # 会社情報の取得
        async with session.get(f"https://api.takasumibot.com/v3/company/{company_id}") as resp:
            if resp.status != 200:
                # 公開の 'Bot is thinking...' を削除
                await interaction.delete_original_response()
                
                # APIエラーが発生した場合、フォローアップメッセージを ephemeral=True で送信
                return await interaction.followup.send("会社情報の取得に失敗しました", ephemeral=True)
            company = await resp.json()

        # 会社履歴の取得
        async with session.get(f"https://api.takasumibot.com/v3/companyHistory/{company_id}") as resp:
            if resp.status != 200:
                # 公開の 'Bot is thinking...' を削除
                await interaction.delete_original_response()

                # APIエラーが発生した場合、フォローアップメッセージを ephemeral=True で送信
                return await interaction.followup.send("会社履歴の取得に失敗しました", ephemeral=True)
            history = await resp.json()

    # --- 履歴フィルタ (集計処理は省略) ---
    filtered_history = [
        h for h in history
        if datetime.fromisoformat(h["tradedAt"].replace("Z", "+00:00")) >= since_time
    ]

    total_income = sum(h["amount"] for h in filtered_history if h["amount"] > 0)
    total_expense = -sum(h["amount"] for h in filtered_history if h["amount"] < 0)

    # --- ユーザー別集計 ---
    user_summary = {}
    for h in filtered_history:
        uid = h.get("userId")
        if uid:
            if uid not in user_summary:
                user_summary[uid] = {"total": 0, "count": 0}
            if h["amount"] > 0:
                user_summary[uid]["total"] += h["amount"]
                user_summary[uid]["count"] += 1

    # --- Embed作成 ---
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
        lines = [
            f"<@{uid}>　{info['total']}コイン　{info['count']}回"
            for uid, info in sorted(user_summary.items(), key=lambda x: x[1]["count"], reverse=True)
        ]
        embed.add_field(name="ユーザー別収入", value="\n".join(lines), inline=False)

    # 成功時: 最初の公開 defer メッセージを編集し、結果を公開返信として表示します。
    await interaction.edit_original_response(embed=embed)


# ==================== /forms ====================

class OpinionModalHandler(discord.ui.Modal, title="意見フォーム"):
    opinion = discord.ui.TextInput(
        label="意見を入力してください",
        style=discord.TextStyle.paragraph,
        placeholder="ここに意見を書いてください",
        required=True,
        max_length=500
    )

    def __init__(self, author_id):
        super().__init__()
        self.author_id = author_id

    async def on_submit(self, interaction: discord.Interaction):
        content = str(self.opinion.value)
        target_user = interaction.client.get_user(ADMIN_ID) or await interaction.client.fetch_user(ADMIN_ID)
        try:
            await target_user.send(
                f"📩 **新しい意見が届きました！**\n送信者: <@{self.author_id}>\n内容:\n```\n{content}\n```"
            )
        except:
            pass
        await interaction.response.send_message("送信しました！ありがとうございます！", ephemeral=True)


@bot.tree.command(name="forms", description="意見や要望を送信します")
@require_purchase(ignore_modal=True)
async def forms(interaction: discord.Interaction):
    modal = OpinionModalHandler(interaction.user.id)
    await interaction.response.send_modal(modal)

# ==================== Bot Ready ====================

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

bot.run(token)
