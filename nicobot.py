import discord
import aiohttp
import asyncio
import xml.etree.ElementTree as ET
import datetime
import os

TOKEN = os.getenv("TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
VIDEO_ID = os.getenv("VIDEO_ID")

intents = discord.Intents.default()
client = discord.Client(intents=intents)

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

async def send_periodic_update():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)
    while not client.is_closed():
        data = await fetch_nicovideo_data(VIDEO_ID)
        now_dt = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
        now = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        if data:
            title, view, comment = data

            # キリ番計算
            next_milestone = ((comment // 1_000_000) + 1) * 1_000_000
            previous_milestone = (comment // 1_000_000) * 1_000_000
            remaining = next_milestone - comment

            # 仮の前回キリ番到達時間（本番ではファイル等で保存してね）
            previous_milestone_time = now_dt - datetime.timedelta(hours=30, minutes=42)

            # 経過時間
            elapsed = now_dt - previous_milestone_time
            days = elapsed.days
            hours, remainder = divmod(elapsed.seconds, 3600)
            minutes = remainder // 60

            # メッセージ作成
            milestone_text = f"{next_milestone:,} コメントまで：{remaining:,} コメント"
            elapsed_text = f"{previous_milestone:,} コメントから：{days}日{hours}時間{minutes}分 経過"

            await channel.send(
                f"📺 **{title}**\n🕒 {now} 現在\n"
                f"▶️ 再生数: {view:,} 回\n💬 コメント数: {comment:,} 件\n"
                f"🏁 {milestone_text}\n"
                f"⏳ {elapsed_text}"
            )
        else:
            await channel.send(f"⚠️ {now}：動画データの取得に失敗しました。")

        await asyncio.sleep(900)  # 15分おき

@client.event
async def on_ready():
    print(f"Botがログインしました: {client.user}")
    client.loop.create_task(send_periodic_update())

client.run(TOKEN)
