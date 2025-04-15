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

    while not client.is_closed():
        await send_update_once()
        await asyncio.sleep(900)  # 15分ごとに定期送信  # 5秒ごとにチェック

@client.event
async def on_ready():
    print(f"Botがログインしました: {client.user}")
    client.loop.create_task(send_periodic_update())

@alert_client.event
async def on_ready():
    print(f"アラートBotがログインしました: {alert_client.user}")

@client.event
async def on_message(message):
    if message.content == "/test" and message.channel.id == CHANNEL_ID:
        await send_update_once()

@alert_client.event
async def on_message(message):
    if message.content == "/test" and message.channel.id == ALERT_CHANNEL_ID:
        await message.channel.send("✅ 生きてるよ！")

loop = asyncio.get_event_loop()
loop.create_task(client.start(TOKEN))
loop.create_task(alert_client.start(ALERT_BOT_TOKEN))
loop.run_forever()
