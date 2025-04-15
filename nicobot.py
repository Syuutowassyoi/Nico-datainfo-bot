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
                view = thumb.find("view_counter").text
                comment = thumb.find("comment_num").text
                return title, view, comment
            except Exception as e:
                print(f"データ解析エラー: {e}")
                return None

async def send_periodic_update():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)
    while not client.is_closed():
        data = await fetch_nicovideo_data(VIDEO_ID)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if data:
            title, view, comment = data
            await channel.send(
                f"📺 **{title}**\n🕒 {now} 現在\n"
                f"▶️ 再生数: {int(view):,} 回\n💬 コメント数: {int(comment):,} 件"
            )
        else:
            await channel.send(f"⚠️ {now}：動画データの取得に失敗しました。")
        await asyncio.sleep(60)  # 15分（900秒）

@client.event
async def on_ready():
    print(f"Botがログインしました: {client.user}")
    client.loop.create_task(send_periodic_update())

client.run(TOKEN)