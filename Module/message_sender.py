import os
import logging
from PIL import Image
import discord
from telegram import Bot

logger = logging.getLogger(__name__)


class MessageSender:
    def __init__(self, telegram_bot_token, telegram_chat_id):
        self.telegram_bot = Bot(token=telegram_bot_token)
        self.telegram_chat_id = telegram_chat_id

    def validate_image(self, img_path):
        """이미지 파일 유효성 검증"""
        try:
            # 파일 존재 확인
            if not os.path.exists(img_path):
                logger.error(f"파일이 존재하지 않음: {img_path}")
                return False

            # 파일 크기 확인 (0바이트 체크)
            file_size = os.path.getsize(img_path)
            if file_size == 0:
                logger.error(f"파일 크기가 0바이트: {img_path}")
                return False

            # 이미지 파일 열어보기 (손상 여부 확인)
            try:
                with Image.open(img_path) as img:
                    img.verify()  # 이미지 무결성 검증

                # verify() 후에는 이미지를 다시 열어야 함
                with Image.open(img_path) as img:
                    img.load()  # 실제로 데이터 로드 시도

                logger.info(f"이미지 검증 성공: {img_path} ({file_size} bytes)")
                return True

            except Exception as e:
                logger.error(f"이미지 파일 손상됨: {img_path} - {e}")
                return False

        except Exception as e:
            logger.error(f"이미지 검증 실패: {img_path} - {e}")
            return False

    async def send_to_discord(self, channel, title, img_path):
        """디스코드로 이미지 전송"""
        try:
            # 이미지 검증
            if not self.validate_image(img_path):
                logger.error(f"Discord 전송 취소: 이미지 검증 실패 - {img_path}")
                return False

            embed = discord.Embed(
                title=title,
                color=0xFF5733
            )
            embed.set_image(url=f"attachment://{os.path.basename(img_path)}")

            with open(img_path, 'rb') as f:
                await channel.send(
                    file=discord.File(f, filename=os.path.basename(img_path)),
                    embed=embed
                )

            logger.info(f"Discord 전송 성공: {img_path}")
            return True

        except discord.HTTPException as e:
            logger.error(f"Discord HTTP 에러: {e.status} - {e.text}")
            return False
        except Exception as e:
            logger.error(f"Discord 전송 실패: {type(e).__name__}: {str(e)}")
            return False

    async def send_to_telegram(self, image_path):
        """텔레그램으로 이미지 전송"""
        try:
            # 이미지 검증
            if not self.validate_image(image_path):
                logger.error(f"Telegram 전송 취소: 이미지 검증 실패 - {image_path}")
                return False

            with open(image_path, 'rb') as img_file:
                await self.telegram_bot.send_photo(
                    chat_id=self.telegram_chat_id,
                    photo=img_file
                )

            logger.info(f"Telegram 전송 성공: {image_path}")
            return True

        except Exception as e:
            logger.error(f"Telegram 전송 실패: {type(e).__name__}: {str(e)}")
            return False