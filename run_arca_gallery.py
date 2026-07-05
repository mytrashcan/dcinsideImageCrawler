"""
아카라이브 전용 갤러리 크롤러 실행 스크립트.

DCInsideImageCrawler의 run_gallery.py와 동일한 패턴:
- WEB_GALLERY=1 환경변수로 웹 갤러리 연동 가능
- Telegram 전송 없음 (Discord 전용)
"""
import asyncio
import json
import os
import sys

from Module.arca_bot import ArcaBot
from Module.config import TOKEN, get_discord_intents


def load_gallery_config(gallery_name):
    with open("galleries.json", encoding="utf-8") as f:
        galleries = json.load(f)
    if gallery_name not in galleries:
        print(f"알 수 없는 갤러리: {gallery_name}")
        print(f"사용 가능: {', '.join(galleries.keys())}")
        sys.exit(1)
    return galleries[gallery_name]


async def main(gallery_name):
    config = load_gallery_config(gallery_name)
    intents = get_discord_intents()
    bot = ArcaBot(
        token=TOKEN,
        base_url=config["base_url"],
        channel_ids=config["channel_ids"],
        intents=intents,
    )
    # WEB_GALLERY=1 이면 공유 웹 갤러리에 적재
    if os.getenv("WEB_GALLERY") == "1":
        from web_app import attach_web_gallery
        attach_web_gallery(
            bot.message_sender,
            gallery=gallery_name,
        )

    await bot.run_bot()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python run_arca_gallery.py <gallery_name>")
        print("  WEB_GALLERY=1 로 웹 갤러리 연동")
        sys.exit(1)

    asyncio.run(main(sys.argv[1]))
