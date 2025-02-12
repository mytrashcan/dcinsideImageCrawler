# main.py
import asyncio
import random
import discord
from Module.config import (
    TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, get_discord_intents
)
from Module.crawler import DCInsideCrawler
from Module.image_handler import ImageHandler
from Module.message_sender import MessageSender

CHANNEL_IDS = ['1337598015103438980', '1337336259605037096']  # 여러 채널 ID를 리스트로 설정
BASE_URL = "https://gall.dcinside.com/mgallery/board/lists/?id=stellive"

class DCBot(discord.Client):
    def __init__(self):
        super().__init__(intents=get_discord_intents())
        self.crawler = DCInsideCrawler(BASE_URL)
        self.image_handler = ImageHandler()
        self.message_sender = MessageSender(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

    async def on_ready(self):
        print(f'Logged in as {self.user}')
        await self.start_crawling()

    async def start_crawling(self):
        while True:
            try:
                post = await self.crawler.get_latest_post()
                if post and post['has_image']:
                    await self.process_post(post)
            except Exception as e:
                return None
            delay = random.uniform(20, 40)
            await asyncio.sleep(delay)

    async def process_post(self, post):
        img_path = self.image_handler.download_image(post['link'])
        if img_path:
            file_hash = self.image_handler.calculate_hash(img_path)

            # 디스코드 채널들에 전송
            for channel_id in CHANNEL_IDS:
                channel = self.get_channel(int(channel_id))
                if channel:
                    await self.message_sender.send_to_discord(
                        channel, post['title'], img_path, file_hash
                    )

            # 텔레그램에 전송
            await self.message_sender.send_to_telegram(img_path, file_hash)

def main():
    client = DCBot()
    client.run(TOKEN)

if __name__ == "__main__":
    main()