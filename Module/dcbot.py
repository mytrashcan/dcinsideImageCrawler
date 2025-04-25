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
        img_path = self.image_handler.download_image(post['link'])
        if img_path:
            file_hash = self.image_handler.calculate_hash(img_path)

            # 디스코드 채널들에 전송
            for channel_id in self.channel_ids:
                channel = self.get_channel(int(channel_id))
                if channel:
                    await self.message_sender.send_to_discord(
                        channel, post['title'], img_path, file_hash
                    )

            # 텔레그램에 전송
            await self.message_sender.send_to_telegram(img_path, file_hash)

    async def on_message(self, message):
        # 봇 자신이 보낸 메시지는 무시
        if message.author == self.user:
            return

        # '!쓰담쓰담' 명령어 처리
        if message.content.strip() == "!쓰담쓰담":
            # Image 폴더 내 파일 삭제
            image_folder = os.path.join(os.getcwd(), "Image")
            if not os.path.exists(image_folder):
                await message.channel.send("Image 폴더가 존재하지 않습니다!")
                return

            deleted_files = []
            for file_name in os.listdir(image_folder):
                file_path = os.path.join(image_folder, file_name)
                if os.path.isfile(file_path):
                    os.remove(file_path)  # 파일 삭제
                    deleted_files.append(file_name)

            if deleted_files:
                file = discord.File("gaki.png", filename="gaki.png")

                embed = discord.Embed(
                    title="🧹 Image 폴더의 모든 파일을 싹~ 다 삭제해버릴게!♡",
                    description="오빠의 흑역사는 이제 없어졌어! ㅋㅋㅋ",
                    color=0xFF69B4
                )
                embed.set_image(url="attachment://gaki.png")

                await message.channel.send(embed=embed, file=file)

            else:
                await message.channel.send("Image 폴더가 비어 있습니다!")

    async def run_bot(self):
        async with self:
            await self.start(self.token)