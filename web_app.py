"""Ephemeral 웹 갤러리.

여러 크롤러 프로세스(launcher가 띄우는 run_gallery.py들)가 동시에 이미지를
보내고, 독립 웹 서버 프로세스 1개가 그것을 보여주는 구조를 지원하기 위해
피드를 **파일시스템**에 둔다. (프로세스 간 메모리 공유가 불가능하므로)

- 크롤러: save_bytes_to_gallery() 로 공유 디렉터리에 이미지 + 사이드카(.json) 기록
- 웹 서버: snapshot() 으로 디렉터리를 mtime/created_at 기준 최신순 나열,
  TTL 경과분과 max_items 초과분을 디스크에서 삭제 (ephemeral)

저장소가 없어 어느 프로세스에서든 동작하며, TTL이 지나면 파일이 실제로 사라진다.
"""
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _static_dir() -> Path:
    return Path(os.getenv("WEB_STATIC_DIR", "web_static"))


def _upload_dir() -> Path:
    d = _static_dir() / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ttl() -> int:
    return int(os.getenv("WEB_IMAGE_TTL_SECONDS", str(3 * 60 * 60)))


def _max_items() -> int:
    return int(os.getenv("WEB_FEED_MAX_ITEMS", "120"))


def _ext_for(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    return ext if ext in ALLOWED_EXT else ".jpg"


def _remove(paths):
    for p in paths:
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass


# 같은 이미지가 디스코드(채널 수만큼)+텔레그램으로 한 프로세스 안에서 여러 번 들어오므로,
# 최근 저장한 원본 filename을 잠깐 기억해 프로세스 내 중복 기록을 막는다.
_recent_lock = threading.Lock()
_recent: dict[str, float] = {}
_DEDUP_WINDOW = 300.0


def _is_duplicate(filename: str) -> bool:
    if not filename:
        return False
    now = time.monotonic()
    with _recent_lock:
        stale = [k for k, v in _recent.items() if now - v > _DEDUP_WINDOW]
        for k in stale:
            _recent.pop(k, None)
        if filename in _recent:
            return True
        _recent[filename] = now
    return False


def save_bytes_to_gallery(data: bytes, filename: str, title: str = "", link: str = "") -> dict:
    """이미지 바이트를 공유 갤러리 디렉터리에 기록한다. (크롤러 프로세스에서 호출)

    이미지는 <uuid>.<ext>, 메타데이터는 <uuid>.<ext>.json 사이드카로 저장한다.
    부분 기록된 파일이 웹 서버에 노출되지 않도록 임시파일에 쓴 뒤 atomic rename 한다.
    link이 있으면 피드에서 제목이 해당 게시글 하이퍼링크가 된다.
    """
    if _is_duplicate(filename):
        return {}
    up = _upload_dir()
    name = f"{uuid.uuid4().hex}{_ext_for(filename)}"
    final = up / name
    tmp = up / f"{name}.part"
    created = time.time()
    meta = {"filename": filename or name, "title": title, "link": link or "", "created_at": created}
    try:
        tmp.write_bytes(data)
        (up / f"{name}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        tmp.rename(final)  # 같은 디렉터리 내 rename은 atomic
    except OSError:
        _remove([tmp, up / f"{name}.json"])
        return {}
    return {"id": name, "url": f"/static/images/{name}", **meta}


def _read_meta(up: Path, name: str, mtime: float):
    sidecar = up / f"{name}.json"
    created, title, link, likes = mtime, "", "", 0
    try:
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        created = float(meta.get("created_at", mtime))
        title = meta.get("title", "") or ""
        link = meta.get("link", "") or ""
        likes = int(meta.get("likes", 0))
    except (OSError, ValueError, TypeError):
        pass
    return created, title, link, likes


# 이미지 id는 uuid4().hex(32 hex) + 허용 확장자. 경로 조작/임의 파일 접근 방지용 검증.
_ID_RE = re.compile(r"^[0-9a-f]{32}\.(jpg|jpeg|png|gif|webp)$")
_like_lock = threading.Lock()


def like_image(image_id: str):
    """이미지에 좋아요 +1. 사이드카(.json)의 likes 필드를 증가시키고 새 값을 반환한다."""
    if not _ID_RE.match(image_id or ""):
        return None
    up = _upload_dir()
    if not (up / image_id).is_file():
        return None
    sidecar = up / f"{image_id}.json"
    with _like_lock:
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        meta["likes"] = int(meta.get("likes", 0)) + 1
        tmp = up / f"{image_id}.json.part"
        try:
            tmp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            tmp.rename(sidecar)  # 부분 기록 노출 방지
        except OSError:
            return None
        return meta["likes"]


# snapshot은 웹 서버 프로세스 1개에서만 호출되므로 별도 프로세스 락은 불필요하다.
def snapshot(limit: int = 120) -> list[dict]:
    up = _upload_dir()
    cutoff = time.time() - _ttl()
    maxn = _max_items()
    items = []
    remove = []
    for p in up.iterdir():
        if not p.is_file() or p.suffix.lower() not in ALLOWED_EXT:
            continue
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        created, title, link, likes = _read_meta(up, p.name, mtime)
        if created < cutoff:
            remove.append(p)
            remove.append(up / f"{p.name}.json")
            continue
        items.append({
            "id": p.name,
            "url": f"/static/images/{p.name}",
            "title": title,
            "link": link,
            "likes": likes,
            "created_at": created,
        })
    items.sort(key=lambda it: it["created_at"], reverse=True)
    if len(items) > maxn:
        for it in items[maxn:]:
            remove.append(up / it["id"])
            remove.append(up / f"{it['id']}.json")
        items = items[:maxn]
    _remove(remove)
    return items[: min(limit, len(items))]


def attach_web_gallery(message_sender) -> None:
    """봇의 메시지 센더를 감싸, 디스코드/텔레그램으로 보낸 이미지를 웹 갤러리에도 적재한다.

    dcbot 코드는 건드리지 않는다. 디스코드가 먼저 전송되므로 title이 보존되고,
    프로세스 내 dedup으로 채널 수만큼/텔레그램 중복이 합쳐진다.
    """
    original_discord = message_sender.send_to_discord
    original_telegram = message_sender.send_to_telegram

    async def discord_with_web(channel, title, image_buffer, filename, url=None):
        try:
            return await original_discord(channel, title, image_buffer, filename, url)
        finally:
            try:
                image_buffer.seek(0)
                data = image_buffer.read()
                if data:
                    save_bytes_to_gallery(data, filename or "", title or "", url or "")
            except (OSError, ValueError):
                pass

    async def telegram_with_web(image_buffer, filename=None, is_gif=False, max_retries=3):
        data = None
        try:
            data = image_buffer.getvalue()
        except (OSError, ValueError, AttributeError):
            data = None
        try:
            return await original_telegram(image_buffer, filename, is_gif, max_retries)
        finally:
            if data:
                save_bytes_to_gallery(data, filename or "", "")

    message_sender.send_to_discord = discord_with_web
    message_sender.send_to_telegram = telegram_with_web


def create_app() -> FastAPI:
    static_dir = _static_dir()
    _upload_dir()  # 정적 마운트 전에 디렉터리 보장
    static_dir.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="dcinsideImageCrawler Gallery")
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    def _page(name: str) -> HTMLResponse:
        f = static_dir / name
        if not f.exists():
            return HTMLResponse(f"<h1>{name} not found</h1>", status_code=404)
        return HTMLResponse(f.read_text(encoding="utf-8"))

    @app.middleware("http")
    async def cache_control(request, call_next):
        resp = await call_next(request)
        path = request.url.path
        if path.startswith("/static/images/"):
            # uuid URL이라 내용이 절대 안 바뀜 → 길게 캐시(CF 엣지가 이미지 서빙 부담을 가져감)
            resp.headers["Cache-Control"] = "public, max-age=86400, immutable"
        elif path == "/feed" or path == "/":
            # 실시간 피드/페이지는 절대 캐시 금지 (캐시되면 새 자짤이 안 뜸)
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/", response_class=HTMLResponse)
    async def index():
        idx = static_dir / "index.html"
        if not idx.exists():
            return HTMLResponse("<h1>Gallery starting...</h1>")
        return HTMLResponse(idx.read_text(encoding="utf-8"))

    @app.get("/privacy", response_class=HTMLResponse)
    async def privacy():
        return _page("privacy.html")

    @app.get("/about", response_class=HTMLResponse)
    async def about():
        return _page("about.html")

    @app.get("/request", response_class=HTMLResponse)
    async def request_gallery():
        return _page("request.html")

    @app.get("/ads.txt", response_class=PlainTextResponse)
    async def ads_txt():
        f = static_dir / "ads.txt"
        if f.exists():
            return PlainTextResponse(f.read_text(encoding="utf-8"))
        return PlainTextResponse("", status_code=404)

    @app.get("/feed")
    async def feed(limit: int = Query(60, ge=1, le=200)):
        return JSONResponse(snapshot(limit))

    @app.post("/like/{image_id}")
    async def like(image_id: str):
        n = like_image(image_id)
        if n is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"id": image_id, "likes": n})

    @app.get("/healthz")
    async def healthz():
        items = snapshot(_max_items())
        return JSONResponse({"ok": True, "items": len(items), "ttl": _ttl()})

    return app
