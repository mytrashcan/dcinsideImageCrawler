"""단일 갤러리 크롤러 + 메모리 전용 웹 갤러리를 한 프로세스에서 실행한다.

여러 갤러리를 한 웹 페이지에 모으려면 이 파일 대신:
  - launcher.py  (WEB_GALLERY=1 환경변수로 각 크롤러가 웹에 적재)
  - run_web_server.py  (웹 서버 1개)
를 따로 실행한다. (README의 "web gallery" 절 참고)
"""
import asyncio
import json
import secrets
import sys
from threading import Thread

import uvicorn

# config는 arca_crawler보다 먼저 import해야 함 (arca_crawler가 app_config로 프록시를 읽음)
from Module.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TOKEN, app_config, get_discord_intents, validate_required_env  # isort: skip
from Module.arca_bot import ArcaBot
from Module.dcbot import DCBot
from Module.gallery_client import attach_web_gallery
from web_app import create_app


def load_gallery_config(gallery_name):
    with open("galleries.json", encoding="utf-8") as f:
        galleries = json.load(f)
    if gallery_name not in galleries:
        print(f"알 수 없는 갤러리: {gallery_name}")
        print(f"사용 가능: {', '.join(galleries.keys())}")
        sys.exit(1)
    return galleries[gallery_name]


def start_web_gallery():
    # 기본값은 로컬 전용(127.0.0.1) — 외부 공개는 리버스 프록시(Caddy 등)를 통해서만.
    # 프록시 없이 직접 공개하려면 WEB_HOST=0.0.0.0 을 명시적으로 지정한다.
    cfg = uvicorn.Config(create_app(), host=app_config.web_host, port=app_config.web_port, log_level="info")
    uvicorn.Server(cfg).run()


async def main(gallery_name):
    config = load_gallery_config(gallery_name)
    intents = get_discord_intents()
    if not app_config.web_ingest_token:
        app_config.web_ingest_token = secrets.token_urlsafe(32)

    web_thread = Thread(target=start_web_gallery, daemon=True)
    web_thread.start()

    if config.get("type") == "arca":
        # ArcaBot은 Telegram을 쓰지 않으므로 DISCORD_TOKEN만 확인한다.
        if not TOKEN:
            print("필수 환경변수가 없습니다: DISCORD_TOKEN")
            sys.exit(1)
        # ArcaBot은 WEB_GALLERY=1 이면 내부에서 웹 갤러리에 적재한다.
        # app_config는 module level에서 읽히므로 직접 덮어씀
        app_config.web_gallery = True
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
        # dcbot은 건드리지 않고 센더만 감싸 웹 갤러리에 적재
        attach_web_gallery(bot.message_sender, gallery_name)

    await bot.run_bot()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python run_web_gallery.py <gallery_name>")
        print("  WEB_GALLERY=1 로 웹 갤러리 연동")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
