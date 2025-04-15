import discord
import aiohttp
import asyncio
import xml.etree.ElementTree as ET
import datetime
import os
import json
import gspread
from google.oauth2.service_account import Credentials

TOKEN = os.getenv("TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ALERT_BOT_TOKEN = os.getenv("ALERT_BOT_TOKEN")
ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID"))
VIDEO_ID = os.getenv("VIDEO_ID")
SHEET_ID = os.getenv("SHEET_ID")
SHEET_NAME = "シート1"

MILESTONE_FILE = "milestone.json"

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
alert_client = discord.Client(intents=intents)

startup_flag = True

def log_to_sheet(milestone, timestamp):
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_env = os.getenv("GOOGLE_CREDENTIALS")
    if creds_env is None:
        raise ValueError("GOOGLE_CREDENTIALS が設定されていません。スプレッドシートにアクセスできません。")
    creds_dict = json.loads(creds_env)
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    worksheet = sh.worksheet(SHEET_NAME)
    worksheet.append_row([milestone, timestamp])

async def fetch_nicovideo_data(video_id):
    url = f"https://ext.nicovideo.jp/api/getthumbinfo/{video_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                print(f"HTTPエラー: {response.status}")
                return None
            text = await response.text()
            try:
                root = ET.fromstring(text)
                thumb = root.find("thumb")
                title = thumb.find("title").text
                view = int(thumb.find("view_counter").text)
                comment = int(thumb.find("comment_num").text)
                return title, view, comment
            except Exception as e:
                print(f"データ解析エラー: {e}")
                return None

def load_last_milestone():
    if not os.path.exists(MILESTONE_FILE):
        return None
    with open(MILESTONE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_milestone(milestone, now_dt):
    with open(MILESTONE_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "last_milestone": milestone,
            "timestamp": now_dt.isoformat()
        }, f)

async def alert_if_needed(remaining, next_milestone):
    if remaining <= 5000:
        await alert_client.wait_until_ready()
        channel = alert_client.get_channel(ALERT_CHANNEL_ID)
        if channel:
            await channel.send(f"🚨 キリ番接近！{next_milestone:,} コメントまで残り {remaining:,} コメントです！")

async def send_update_once(is_startup=False):
    channel = client.get_channel(CHANNEL_ID)
    data = await fetch_nicovideo_data(VIDEO_ID)
    now_dt = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    now = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    if data:
        title, view, comment = data
        next_milestone = ((comment // 1_000_000) + 1) * 1_000_000
        previous_milestone = (comment // 1_000_000) * 1_000_000
        remaining = next_milestone - comment

        milestone_data = load_last_milestone()
        elapsed_text = " - "
        if milestone_data:
            last_milestone = milestone_data["last_milestone"]
            ts = milestone_data["timestamp"]
            if previous_milestone == last_milestone:
                prev_time = datetime.datetime.fromisoformat(ts)
                elapsed = now_dt - prev_time
                days = elapsed.days
                hours, remainder = divmod(elapsed.seconds, 3600)
                minutes = remainder // 60
                elapsed_text = f"{previous_milestone:,} コメントから：{days}日{hours}時間{minutes}分 経過"

        if milestone_data is None or previous_milestone > milestone_data["last_milestone"]:
            save_milestone(previous_milestone, now_dt)
            log_to_sheet(previous_milestone, now_dt.strftime("%Y-%m-%d %H:%M:%S"))

        milestone_text = f"{next_milestone:,} コメントまで：{remaining:,} コメント"
        prefix = "✅ 起動時チェック\n" if is_startup else ""
        await channel.send(
            f"{prefix}📺 **{title}**\n🕒 {now} 現在\n"
            f"▶️ 再生数: {view:,} 回\n💬 コメント数: {comment:,} 件\n"
            f"🏁 {milestone_text}\n"
            f"⏳ {elapsed_text}"
        )

        await alert_if_needed(remaining, next_milestone)
    else:
        await channel.send(f"⚠️ {now}：動画データの取得に失敗しました。")

async def send_periodic_update():
    global startup_flag
    await client.wait_until_ready()
    if startup_flag:
        await send_update_once(is_startup=True)
        startup_flag = False

    short_interval = False

    while not client.is_closed():
        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
        data = await fetch_nicovideo_data(VIDEO_ID)

        if data:
            _, _, comment = data
            next_milestone = ((comment // 1_000_000) + 1) * 1_000_000
            remaining = next_milestone - comment
            short_interval = remaining <= 5000

        interval = 5 if short_interval else 15
        next_minute = ((now.minute // interval + 1) * interval) % 60
        next_time = now.replace(minute=next_minute, second=0, microsecond=0)
        if next_minute == 0:
            next_time += datetime.timedelta(hours=1)
        wait_seconds = (next_time - now).total_seconds()

        await asyncio.sleep(wait_seconds)
        await send_update_once()

@client.event
async def on_ready():
    print(f"Botがログインしました: {client.user}")
    client.loop.create_task(send_periodic_update())
    client.loop.create_task(send_daily_ranking())

@alert_client.event
async def on_ready():
    print(f"アラートBotがログインしました: {alert_client.user}")

@client.event
async def on_message(message):
    if message.channel.id != CHANNEL_ID:
        return
    if message.content == "help info":
        help_text = (
            "📖 **Botコマンド一覧**
"
            "- `/test`：現在の再生数・コメント数を即時表示
"
            "- `infoconfig day-ranking YYYY-MM-DD`：指定日の支援者ランキングを表示
"
            "（例: infoconfig day-ranking 2025-04-14）"
        )
        await message.channel.send(help_text)
    elif message.content == "/test":
        await send_update_once()
    if message.content.startswith("infoconfig day-ranking"):
        try:
            _, _, date_str = message.content.strip().split()
            dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            y, m, d = dt.year, dt.month, dt.day
            rankings = await fetch_supporter_ranking(y, m, d)
            if rankings:
                text = "\n".join([f"{i+1}位: {name} - {count:,}コメント" for i, (name, count) in enumerate(rankings)])
                await message.channel.send(f"📊 支援者ランキング（{dt.strftime('%Y/%m/%d')}）\n{text}")
            else:
                await message.channel.send(f"⚠️ 指定された日のランキングが見つかりませんでした。")
        except Exception as e:
            await message.channel.send(f"⚠️ 日付形式が間違っています。例: infoconfig day-ranking 2025-04-14")

@alert_client.event
async def on_message(message):
    if message.content == "/test" and message.channel.id == ALERT_CHANNEL_ID:
        await message.channel.send("✅ 生きてるよ！")

async def fetch_supporter_ranking(y=None, m=None, d=None):
    tz = datetime.timezone(datetime.timedelta(hours=9))
    if y is None or m is None or d is None:
        today = datetime.datetime.now(tz)
        yesterday = today - datetime.timedelta(days=1)
        y, m, d = yesterday.year, yesterday.month, yesterday.day

    date_path = f"{y:04d}-{m:02d}/{y:04d}-{m:02d}-{d:02d}.txt"
    url = f"https://sosuteno.com/jien/STLog/{date_path}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                print(f"支援者ランキングの取得失敗: {response.status}")
                return None
            text = await response.text(encoding='utf-8')

    in_ranking = False
    rankings = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[支援者内訳]"):
            in_ranking = True
            continue
        if in_ranking:
            if line == "" or line.startswith("集計終"):
                break
            if " さん " in line:
                name, rest = line.split(" さん ", 1)
                comments = rest.split("コメ")[0].strip()
                rankings.append((name + " さん", int(comments.replace(",", ""))))
    rankings.sort(key=lambda x: x[1], reverse=True)
    return rankings

async def send_daily_ranking():
    await client.wait_until_ready()
    while True:
        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
        target = now.replace(hour=0, minute=1, second=0, microsecond=0)
        if now >= target:
            target += datetime.timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        rankings = await fetch_supporter_ranking()
        if rankings:
            channel = client.get_channel(CHANNEL_ID)
            text = "\n".join([f"{i+1}位: {name} - {count:,}コメント" for i, (name, count) in enumerate(rankings)])
            yesterday = now - datetime.timedelta(days=1)
            url = f"https://sosuteno.com/jien/STLog/{yesterday.strftime('%Y-%m')}/{yesterday.strftime('%Y-%m-%d')}.txt"
            await channel.send(f"📝 {yesterday.strftime('%Y年%m月%d日')}支援者ランキング
{text}
🔗 {url}")

loop = asyncio.get_event_loop()
loop.create_task(client.start(TOKEN))
loop.create_task(alert_client.start(ALERT_BOT_TOKEN))
loop.run_forever()
