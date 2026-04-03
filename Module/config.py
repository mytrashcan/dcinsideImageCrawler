# config.py
import os
import sys
import logging
import discord
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHANNEL")

# 시작 시 필수 환경변수 검증
_required = {"DISCORD_TOKEN": TOKEN, "TELEGRAM_TOKEN": TELEGRAM_BOT_TOKEN, "TELEGRAM_CHANNEL": TELEGRAM_CHAT_ID}
_missing = [k for k, v in _required.items() if not v]
if _missing:
    print(f"필수 환경변수 누락: {', '.join(_missing)}")
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
def get_discord_intents():
    intents = discord.Intents.default()
    intents.message_content = True
    return intents
