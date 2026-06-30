import asyncio
import os
import sys
from threading import Thread

from Module.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TOKEN, get_discord_intents, validate_required_env
from Module.dcbot import DCBot

from web_app import save_bytes_to_gallery

import logging
logger = logging.getLogger(__name__)


def load_gallery_config(gallery_name):
    with open("galleries.json", encoding="utf-8") as f:
        galleries = __import__("json").load(f)
    if gallery_name not in galleries:
        print(f"알 수 없는 갤러리: {gallery_name}")
        print(f"사용 가능: {', '.join(galleries.keys())}")
        sys.exit(1)
    return galleries[gallery_name]


def start_web_gallery():
    import uvicorn
    from web_app import create_app
    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "8000"))
    cfg = uvicorn.Config(create_app(), host=host, port=port, log_level="info")
    uvicorn.Server(cfg).run()


async def main(gallery_name):
    validate_required_env()
    config = load_gallery_config(gallery_name)
    intents = get_discord_intents()
    bot = DCBot(
        token=TOKEN,
        base_url=config["base_url"],
        channel_ids=config["channel_ids"],
        telegram_token=TELEGRAM_BOT_TOKEN,
        telegram_chat_id=TELEGRAM_CHAT_ID,
        intents=intents,
    )

    web_thread = Thread(target=start_web_gallery, daemon=True)
    web_thread.start()

    # attach web upload to discord/telegram senders without touching dcbot
    original_discord = bot.message_sender.send_to_discord

    async def discord_with_web(channel, title, image_buffer, filename):
        try:
            await original_discord(channel, title, image_buffer, filename)
        finally:
            image_buffer.seek(0)
            data = image_buffer.read()
            if data:
                save_bytes_to_gallery(data, filename or "", title or "")

    original_telegram = bot.message_sender.send_to_telegram

    async def telegram_with_web(image_buffer, filename=None, is_gif=False, max_retries=3):
        buf_copy = None
        try:
            buf_copy = image_buffer.getvalue()
            await original_telegram(image_buffer, filename, is_gif, max_retries)
        finally:
            if buf_copy:
                save_bytes_to_gallery(buf_copy, filename or "", "")

    bot.message_sender.send_to_discord = discord_with_web
    bot.message_sender.send_to_telegram = telegram_with_web

    await bot.run_bot()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python run_web_gallery.py <gallery_name>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
