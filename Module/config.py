from __future__ import annotations
# config.py
import logging
import os
import sys

import discord
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHANNEL")

def validate_required_env() -> object:
    """필수 환경변수 검증 (봇 시작 시 호출 — import 시점에는 검증하지 않음)"""
    required = {"DISCORD_TOKEN": TOKEN, "TELEGRAM_TOKEN": TELEGRAM_BOT_TOKEN, "TELEGRAM_CHANNEL": TELEGRAM_CHAT_ID}
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"필수 환경변수 누락: {', '.join(missing)}")
        print(".env 파일을 확인해주세요.")
        sys.exit(1)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# HTTP 요청 타임아웃 (초)
REQUEST_TIMEOUT = 15

# Discord 업로드 제한 (MB) — 2024년 9월부터 무료(부스트 없는) 서버는 10MB
# (부스트 레벨 2: 50MB, 레벨 3: 100MB — 서버에 맞게 .env의 DISCORD_MAX_SIZE_MB로 조정)
_DEFAULT_DISCORD_MAX_SIZE_MB = 10
try:
    DISCORD_MAX_SIZE = int(float(os.getenv("DISCORD_MAX_SIZE_MB", _DEFAULT_DISCORD_MAX_SIZE_MB)) * 1024 * 1024)
except ValueError:
    print(f"DISCORD_MAX_SIZE_MB 값이 잘못되었습니다. 기본값 {_DEFAULT_DISCORD_MAX_SIZE_MB}MB를 사용합니다.")
    DISCORD_MAX_SIZE = _DEFAULT_DISCORD_MAX_SIZE_MB * 1024 * 1024

# BeautifulSoup 파서 (lxml이 설치되어 있으면 사용 — html.parser보다 수 배 빠름)
try:
    import lxml  # noqa: F401
    BS_PARSER = "lxml"
except ImportError:
    BS_PARSER = "html.parser"

# 헤더 설정
HEADERS = {
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
    "sec-ch-ua-mobile": "?0",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.93 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "ko-KR,ko;q=0.9"
}

# 디스코드 인텐트 설정
def get_discord_intents() -> object:
    intents = discord.Intents.default()
    intents.message_content = True
    return intents
