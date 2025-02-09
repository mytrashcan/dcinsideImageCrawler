# config.py
import os
import discord
from dotenv import load_dotenv

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL")

# 디스코드 봇 Token 과 채널 ID
TOKEN = DISCORD_TOKEN
CHANNEL_IDS = ['1337403396185129041', '1337336259605037096']  # 여러 채널 ID를 리스트로 설정

# 텔레그램 봇 Token과 채팅 ID
TELEGRAM_BOT_TOKEN = TELEGRAM_TOKEN
TELEGRAM_CHAT_ID = TELEGRAM_CHANNEL_ID

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

# 기본 URL 설정
BASE_URL = "https://gall.dcinside.com/mgallery/board/lists/?id=projectmx"