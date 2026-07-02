import asyncio
import json
import os
import sys

from Module.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TOKEN, get_discord_intents, validate_required_env
from Module.dcbot import DCBot


def load_gallery_config(gallery_name):
    with open("galleries.json", encoding="utf-8") as f:
        galleries = json.load(f)

    if gallery_name not in galleries:
        print(f"알 수 없는 갤러리: {gallery_name}")
        print(f"사용 가능: {', '.join(galleries.keys())}")
        sys.exit(1)

    return galleries[gallery_name]

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

    # WEB_GALLERY=1 이면 보낸 이미지를 공유 웹 갤러리 디렉터리에도 적재한다.
    # (run_web_server.py가 이 디렉터리를 읽어 한 페이지에 모아 보여줌)
    if os.getenv("WEB_GALLERY") == "1":
        from web_app import attach_web_gallery

        attach_web_gallery(bot.message_sender, gallery_name)

    await bot.run_bot()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python run_gallery.py <gallery_name>")
        sys.exit(1)

    asyncio.run(main(sys.argv[1]))
