# message_sender.py
import os
import discord
from telegram import Bot, InputFile

class MessageSender:
    def __init__(self, telegram_bot_token, telegram_chat_id):
        self.telegram_bot = Bot(token=telegram_bot_token)
        self.telegram_chat_id = telegram_chat_id

    async def send_to_discord(self, channel, title, img_path, file_hash):
        """디스코드로 이미지 전송"""
        try:
            embed = discord.Embed(
                title=title,
                description=f"hash: {file_hash}",
                color=0xFF5733
            )
            embed.set_image(url=f"attachment://{os.path.basename(img_path)}")

            with open(img_path, 'rb') as f:
                await channel.send(
                    file=discord.File(f, filename=os.path.basename(img_path)),
                    embed=embed
                )
        except Exception as e:
            return None

    async def send_to_telegram(self, image_path, file_hash):
        """텔레그램으로 이미지 전송"""
        try:
            with open(image_path, 'rb') as img_file:
                await self.telegram_bot.send_photo(
                    chat_id=self.telegram_chat_id,
                    photo=img_file
                )
        except Exception as e:
            return None