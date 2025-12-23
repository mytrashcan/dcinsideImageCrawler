import os
import asyncio
import random
import discord
from Module.crawler import DCInsideCrawler
from Module.image_handler import ImageHandler
from Module.message_sender import MessageSender


class DCBot(discord.Client):
    def __init__(self, token, base_url, channel_ids, telegram_token, telegram_chat_id, intents):
        super().__init__(intents=intents)
        self.token = token
        self.base_url = base_url
        self.channel_ids = channel_ids
        self.crawler = DCInsideCrawler(base_url)
        self.image_handler = ImageHandler()
        self.message_sender = MessageSender(telegram_token, telegram_chat_id)

    async def on_ready(self):
        print(f"Logged in as {self.user}")
        await self.start_crawling()

    async def start_crawling(self):
        while True:
            try:
                post = await self.crawler.get_latest_post()
                if post and post['has_image']:
                    await self.process_post(post)
            except Exception as e:
                print(f"Error during crawling: {e}")
            delay = random.uniform(20, 40)
            await asyncio.sleep(delay)

    async def process_post(self, post):
        # 여러 이미지 처리
        images = self.image_handler.download_images(post['link'])
        if not images:
            return

        for i, (discord_buffer, telegram_buffer, filename, is_gif) in enumerate(images):
            # 첫 번째 이미지에만 제목 표시
            title = post['title'] if i == 0 else ""

            # 디스코드 채널들에 전송
            for channel_id in self.channel_ids:
                channel = self.get_channel(int(channel_id))
                if channel:
                    await self.message_sender.send_to_discord(
                        channel, title, discord_buffer, filename
                    )
                    discord_buffer.seek(0)  # 다음 채널을 위해 리셋

            # 텔레그램에 전송
            await self.message_sender.send_to_telegram(telegram_buffer, filename, is_gif)

            # 이미지 간 약간의 딜레이 (API 제한 방지)
            if len(images) > 1:
                await asyncio.sleep(1)

    async def on_message(self, message):
        if message.author == self.user:
            return

        if message.content.strip() == "!쓰담쓰담":
            self.image_handler.clear_seen_hashes()

            file = discord.File("gaki.png", filename="gaki.png")
            embed = discord.Embed(
                title="🧹 이미지 캐시를 싹~ 다 초기화했어!♡",
                description="이제 새로운 이미지들을 받을 준비 완료!",
                color=0xFF69B4
            )
            embed.set_image(url="attachment://gaki.png")
            await message.channel.send(embed=embed, file=file)

    async def run_bot(self):
        async with self:
            await self.start(self.token)