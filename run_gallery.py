"""Single gallery runner — routes to DCInside (DCBot) or Arcalive (ArcaBot) based on galleries.json type."""
from __future__ import annotations
import asyncio
import json
import os
import sys

# config는 arca_crawler보다 먼저 import해야 함 (arca_crawler._ARCA_SOCKS_PROXY가 모듈 로드 시점에 env를 읽음)
from Module.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TOKEN, get_discord_intents, validate_required_env  # isort: skip
from Module.arca_bot import ArcaBot
from Module.dcbot import DCBot


def load_gallery_config(gallery_name: object) -> object:
    with open("galleries.json", encoding="utf-8") as f:
        galleries = json.load(f)

    if gallery_name not in galleries:
        print(f"알 수 없는 갤러리: {gallery_name}")
        print(f"사용 가능: {', '.join(galleries.keys())}")
        sys.exit(1)

    return galleries[gallery_name]


async def main(gallery_name: object) -> object:
    config = load_gallery_config(gallery_name)
    intents = get_discord_intents()

    if config.get("type") == "arca":
        # ArcaBot은 Telegram을 쓰지 않으므로 DISCORD_TOKEN만 확인한다.
        if not TOKEN:
            print("필수 환경변수가 없습니다: DISCORD_TOKEN")
            sys.exit(1)
        # WEB_GALLERY=1 처리는 ArcaBot 내부에서 수행
        bot = ArcaBot(
            token=TOKEN,
            base_url=config["base_url"],
            channel_ids=config["channel_ids"],
            intents=intents,
            gallery_name=gallery_name,
        )
    else:
        validate_required_env()
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
        print("  WEB_GALLERY=1 로 웹 갤러리 연동")
        sys.exit(1)

    asyncio.run(main(sys.argv[1]))
