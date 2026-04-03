import asyncio
import random
import logging
import discord
from Module.crawler import DCInsideCrawler
from Module.image_handler import ImageHandler
from Module.message_sender import MessageSender

logger = logging.getLogger(__name__)


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
        logger.info(f"Logged in as {self.user}")
        await self.start_crawling()

    async def start_crawling(self):
        while True:
            try:
                # 동기 크롤러를 별도 스레드에서 실행하여 이벤트 루프 블로킹 방지
                post = await asyncio.to_thread(self.crawler.get_latest_post)
                if post and post['has_image']:
                    await self.process_post(post)
            except discord.ConnectionClosed:
                logger.warning("Discord 연결이 끊어졌습니다. 재연결 대기 중...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"크롤링 중 오류: {e}", exc_info=True)
            delay = random.uniform(20, 40)
            await asyncio.sleep(delay)

    async def process_post(self, post):
        # blocking I/O를 별도 스레드에서 실행
        images = await asyncio.to_thread(self.image_handler.download_images, post['link'])
        if not images:
            return

        for i, (discord_buffer, telegram_buffer, filename, is_gif) in enumerate(images):
            title = post['title'] if i == 0 else ""

            for channel_id in self.channel_ids:
                channel = self.get_channel(int(channel_id))
                if channel:
                    await self.message_sender.send_to_discord(
                        channel, title, discord_buffer, filename
                    )
                    discord_buffer.seek(0)

            await self.message_sender.send_to_telegram(telegram_buffer, filename, is_gif)

            if len(images) > 1:
                await asyncio.sleep(1)

    async def on_message(self, message):
        if message.author == self.user:
            return

        if message.content.strip() == "!쓰담쓰담":
            self.image_handler.clear_seen_hashes()

            file = discord.File("gaki.png", filename="gaki.png")
            embed = discord.Embed(
                title="이미지 캐시를 초기화했습니다!",
                description="이제 새로운 이미지들을 받을 준비 완료!",
                color=0xFF69B4
            )
            embed.set_image(url="attachment://gaki.png")
            await message.channel.send(embed=embed, file=file)

    async def run_bot(self):
        async with self:
            await self.start(self.token)
