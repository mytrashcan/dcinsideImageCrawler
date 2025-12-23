import io
import logging
import asyncio
from PIL import Image
import discord
from telegram import Bot
from telegram.request import HTTPXRequest

logger = logging.getLogger(__name__)


class MessageSender:
    def __init__(self, telegram_bot_token, telegram_chat_id):
        # 타임아웃 설정 증가 (기본 5초 -> 30초)
        request = HTTPXRequest(
            connect_timeout=30.0,
            read_timeout=30.0,
            write_timeout=30.0
        )
        self.telegram_bot = Bot(token=telegram_bot_token, request=request)
        self.telegram_chat_id = telegram_chat_id

    def validate_image_buffer(self, image_buffer):
        """메모리 버퍼의 이미지 유효성 검증"""
        try:
            image_buffer.seek(0, 2)
            file_size = image_buffer.tell()
            image_buffer.seek(0)

            if file_size == 0:
                logger.error("이미지 버퍼 크기가 0바이트")
                return False

            try:
                with Image.open(image_buffer) as img:
                    img.verify()

                image_buffer.seek(0)

                with Image.open(image_buffer) as img:
                    img.load()

                image_buffer.seek(0)

                logger.info(f"이미지 검증 성공 ({file_size} bytes)")
                return True

            except Exception as e:
                logger.error(f"이미지 버퍼 손상됨: {e}")
                return False

        except Exception as e:
            logger.error(f"이미지 검증 실패: {e}")
            return False

    async def send_to_discord(self, channel, title, image_buffer, filename):
        """디스코드로 이미지 전송"""
        try:
            if not self.validate_image_buffer(image_buffer):
                logger.error("Discord 전송 취소: 이미지 검증 실패")
                return False

            embed = discord.Embed(
                title=title,
                color=0xFF5733
            )
            embed.set_image(url=f"attachment://{filename}")

            await channel.send(
                file=discord.File(image_buffer, filename=filename),
                embed=embed
            )

            logger.info(f"Discord 전송 성공: {filename}")
            return True

        except discord.HTTPException as e:
            logger.error(f"Discord HTTP 에러: {e.status} - {e.text}")
            return False
        except Exception as e:
            logger.error(f"Discord 전송 실패: {type(e).__name__}: {str(e)}")
            return False

    async def send_to_telegram(self, image_buffer, filename=None, is_gif=False, max_retries=3):
        """텔레그램으로 이미지 전송 (GIF는 animation으로, 재시도 포함)"""

        if not self.validate_image_buffer(image_buffer):
            logger.error("Telegram 전송 취소: 이미지 검증 실패")
            return False

        for attempt in range(max_retries):
            try:
                image_buffer.seek(0)  # 재시도 시 버퍼 위치 리셋

                if is_gif:
                    await self.telegram_bot.send_animation(
                        chat_id=self.telegram_chat_id,
                        animation=image_buffer,
                        filename=filename
                    )
                else:
                    await self.telegram_bot.send_photo(
                        chat_id=self.telegram_chat_id,
                        photo=image_buffer,
                        filename=filename
                    )

                logger.info(f"Telegram 전송 성공: {filename}")
                return True

            except Exception as e:
                error_name = type(e).__name__
                if "TimedOut" in error_name or "Timed out" in str(e):
                    logger.warning(f"Telegram 타임아웃 (시도 {attempt + 1}/{max_retries}): {filename}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 * (attempt + 1))  # 점진적 대기 (2초, 4초, 6초)
                        continue

                logger.error(f"Telegram 전송 실패: {error_name}: {str(e)}")
                return False

        return False