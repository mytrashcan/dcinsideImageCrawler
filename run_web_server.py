"""임시 웹 갤러리 서버 (단독 실행).

launcher.py가 여러 갤러리 크롤러를 띄우고(WEB_GALLERY=1), 그 크롤러들이 공유
디렉터리(web_static/images)에 이미지를 쌓으면, 이 서버 1개가 모아서 보여준다.

  WEB_GALLERY=1 python launcher.py     # 크롤러들 (각자 웹에 적재)
  python run_web_server.py             # 웹 서버 (http://localhost:8000)
"""
from __future__ import annotations
import os

import uvicorn
from dotenv import load_dotenv

from web_app import create_app

load_dotenv()  # .env에서 TURNSTILE_SITEKEY/SECRET 등 로드

if __name__ == "__main__":
    # 기본값은 로컬 전용(127.0.0.1) — 외부 공개는 리버스 프록시(Caddy 등)를 통해서만.
    # 프록시 없이 직접 공개하려면 WEB_HOST=0.0.0.0 을 명시적으로 지정한다.
    host = os.getenv("WEB_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_PORT", "8000"))
    uvicorn.run(create_app(), host=host, port=port, log_level="info")
