"""Ephemeral 웹 갤러리.

여러 크롤러 프로세스(launcher가 띄우는 run_gallery.py들)가 동시에 이미지를
보내고, 독립 웹 서버 프로세스 1개가 그것을 보여주는 구조를 지원하기 위해
피드를 **파일시스템**에 둔다. (프로세스 간 메모리 공유가 불가능하므로)

- 크롤러: save_bytes_to_gallery() 로 공유 디렉터리에 이미지 + 사이드카(.json) 기록
- 웹 서버: snapshot() 으로 디렉터리를 mtime/created_at 기준 최신순 나열,
  TTL 경과분과 max_items 초과분을 디스크에서 삭제 (ephemeral)

저장소가 없어 어느 프로세스에서든 동작하며, TTL이 지나면 파일이 실제로 사라진다.
"""
import asyncio
import hashlib
import hmac
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _static_dir() -> Path:
    return Path(os.getenv("WEB_STATIC_DIR", "web_static"))


def _upload_dir() -> Path:
    d = _static_dir() / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _thumb_dir() -> Path:
    # snapshot()의 iterdir()는 파일만 보므로 하위 디렉터리의 썸네일은 피드에 중복 등재되지 않는다.
    d = _upload_dir() / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _thumb_width() -> int:
    """카드용 썸네일 최대 폭(px). 0이면 썸네일 생성 비활성화."""
    return int(os.getenv("WEB_THUMB_WIDTH", "480"))


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


def _image_size(data: bytes) -> tuple[int, int]:
    """이미지의 (width, height). 프론트가 로드 전에 카드 높이를 예약해
    masonry 컬럼이 이미지 로딩 중에 뒤틀리지 않게 한다. 실패 시 (0, 0)."""
    try:
        import io

        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            return img.width, img.height
    except Exception:
        return 0, 0


def _make_thumbnail(data: bytes, name: str) -> bool:
    """카드용 축소 이미지를 thumbs/<name>으로 생성한다 (같은 확장자 유지 → content-type 일치).

    전송량을 줄이는 최적화일 뿐이므로 어떤 실패도 피드 적재를 막지 않는다(best-effort).
    GIF/애니메이션은 움직임이 사라지므로 건너뛰고, 원본이 이미 충분히 작아도 건너뛴다.
    """
    max_w = _thumb_width()
    if max_w <= 0 or name.lower().endswith(".gif"):
        return False
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(data))
        if getattr(img, "is_animated", False) or img.width <= max_w:
            return False
        img.load()
        img.thumbnail((max_w, max_w * 4), Image.LANCZOS)
        ext = os.path.splitext(name)[1].lower()
        if ext in (".jpg", ".jpeg") and img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        dest = _thumb_dir() / name
        tmp = dest.with_suffix(dest.suffix + ".part")
        fmt = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}[ext.lstrip(".")]
        save_kwargs = {"quality": 80} if fmt in ("JPEG", "WEBP") else {"optimize": True}
        img.save(tmp, format=fmt, **save_kwargs)  # .part 확장자에선 포맷 추론이 안 되므로 명시
        tmp.rename(dest)  # 부분 기록 노출 방지
        return True
    except Exception:
        return False


def save_bytes_to_gallery(data: bytes, filename: str, title: str = "", link: str = "", gallery: str = "") -> dict:
    """이미지 바이트를 공유 갤러리 디렉터리에 기록한다. (크롤러 프로세스에서 호출)

    이미지는 <uuid>.<ext>, 메타데이터는 <uuid>.<ext>.json 사이드카로 저장한다.
    부분 기록된 파일이 웹 서버에 노출되지 않도록 임시파일에 쓴 뒤 atomic rename 한다.
    link이 있으면 피드에서 제목이 해당 게시글 하이퍼링크가 되고,
    gallery(출처 갤러리명)는 피드의 갤러리별 필터에 쓰인다.
    """
    if _is_duplicate(filename):
        return {}
    up = _upload_dir()
    name = f"{uuid.uuid4().hex}{_ext_for(filename)}"
    final = up / name
    tmp = up / f"{name}.part"
    created = time.time()
    w, h = _image_size(data)
    meta = {"filename": filename or name, "title": title, "link": link or "",
            "gallery": gallery or "", "created_at": created, "w": w, "h": h}
    try:
        tmp.write_bytes(data)
        (up / f"{name}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        tmp.rename(final)  # 같은 디렉터리 내 rename은 atomic
    except OSError:
        _remove([tmp, up / f"{name}.json"])
        return {}
    has_thumb = _make_thumbnail(data, name)
    item = {"id": name, "url": f"/static/images/{name}", **meta}
    item["thumb"] = f"/static/images/thumbs/{name}" if has_thumb else item["url"]
    return item


def _read_meta(up: Path, name: str, mtime: float) -> dict:
    """사이드카 메타를 안전한 기본값과 함께 dict로 읽는다."""
    out = {"created_at": mtime, "title": "", "link": "", "gallery": "", "likes": 0, "w": 0, "h": 0}
    try:
        meta = json.loads((up / f"{name}.json").read_text(encoding="utf-8"))
        out["created_at"] = float(meta.get("created_at", mtime))
        out["title"] = meta.get("title", "") or ""
        out["link"] = meta.get("link", "") or ""
        out["gallery"] = meta.get("gallery", "") or ""
        out["likes"] = int(meta.get("likes", 0))
        out["w"] = int(meta.get("w", 0))
        out["h"] = int(meta.get("h", 0))
    except (OSError, ValueError, TypeError):
        pass
    return out


def _remaining_ttl(name: str) -> int:
    """이미지의 남은 TTL(초)을 반환한다. 만료됐으면 파일·사이드카·썸네일을 삭제하고 -1."""
    up = _upload_dir()
    image = up / name
    thumb = _thumb_dir() / name
    try:
        mtime = image.stat().st_mtime
    except OSError:
        _remove([thumb, up / f"{name}.json"])  # 원본이 사라진 고아 썸네일/사이드카 정리
        return -1
    created = _read_meta(up, name, mtime)["created_at"]
    remaining = int(created + _ttl() - time.time())
    if remaining > 0:
        return remaining
    _remove([image, up / f"{name}.json", thumb])
    return -1


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
    thumbs = _thumb_dir()
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
        meta = _read_meta(up, p.name, mtime)
        if meta["created_at"] < cutoff:
            remove += [p, up / f"{p.name}.json", thumbs / p.name]
            continue
        url = f"/static/images/{p.name}"
        items.append({
            "id": p.name,
            "url": url,
            # 카드용 축소 이미지(전송량↓). 썸네일이 없는 이미지(GIF/소형/생성실패)는 원본 폴백.
            "thumb": f"/static/images/thumbs/{p.name}" if (thumbs / p.name).is_file() else url,
            # title/link/gallery/likes + w/h(로드 전 카드 높이 예약, masonry 뒤틀림 방지)
            **{k: meta[k] for k in ("title", "link", "gallery", "likes", "w", "h", "created_at")},
        })
    items.sort(key=lambda it: it["created_at"], reverse=True)
    if len(items) > maxn:
        for it in items[maxn:]:
            remove += [up / it["id"], up / f"{it['id']}.json", thumbs / it["id"]]
        items = items[:maxn]
    _remove(remove)
    return items[: min(limit, len(items))]


def attach_web_gallery(message_sender, gallery: str = "") -> None:
    """봇의 메시지 센더를 감싸, 디스코드/텔레그램으로 보낸 이미지를 웹 갤러리에도 적재한다.

    dcbot 코드는 건드리지 않는다. 디스코드가 먼저 전송되므로 title이 보존되고,
    프로세스 내 dedup으로 채널 수만큼/텔레그램 중복이 합쳐진다.
    gallery는 이 크롤러가 담당하는 갤러리명(피드의 갤러리별 필터용).
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
                    save_bytes_to_gallery(data, filename or "", title or "", url or "", gallery)
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
                save_bytes_to_gallery(data, filename or "", "", "", gallery)

    message_sender.send_to_discord = discord_with_web
    message_sender.send_to_telegram = telegram_with_web


# ── Cloudflare Turnstile (봇 차단) ──
# 시크릿이 설정돼 있을 때만 활성화. 사이트키는 공개값(HTML에 주입), 시크릿은 .env에만 둔다.
_TS_COOKIE = "ts_ok"
_TS_TTL = 86400  # 한 번 통과하면 24시간 유지


def _ts_sitekey() -> str:
    return os.getenv("TURNSTILE_SITEKEY", "")


def _ts_secret() -> str:
    return os.getenv("TURNSTILE_SECRET", "")


def _ts_enabled() -> bool:
    return bool(_ts_secret())


def _ts_make_cookie() -> str:
    exp = int(time.time()) + _TS_TTL
    sig = hmac.new(_ts_secret().encode(), str(exp).encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def _ts_cookie_valid(value: str) -> bool:
    if not value or "." not in value:
        return False
    exp_s, sig = value.split(".", 1)
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    if time.time() > exp:
        return False
    good = hmac.new(_ts_secret().encode(), str(exp).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, good)


def _ts_siteverify(token: str, remoteip: str) -> bool:
    data = urllib.parse.urlencode({
        "secret": _ts_secret(),
        "response": token or "",
        "remoteip": remoteip or "",
    }).encode()
    req = urllib.request.Request(
        "https://challenges.cloudflare.com/turnstile/v0/siteverify", data=data
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return bool(json.load(r).get("success", False))
    except Exception:
        return False


# ── 긴급 점검(서버 닫기) 모드 ──
# 플래그 파일이 존재하거나 WEB_MAINTENANCE=1 이면 점검 페이지를 보여준다.
# dcselfie.sh down/up 으로 토글(웹 서버 재시작 없이 즉시 반영).
def _maintenance_file() -> Path:
    return Path(os.getenv("WEB_MAINTENANCE_FILE", str(_static_dir().parent / ".maintenance")))


def _maintenance_on() -> bool:
    return os.getenv("WEB_MAINTENANCE") == "1" or _maintenance_file().exists()


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
        path = request.url.path
        remaining = 0
        if path.startswith("/static/images/"):
            # 원본(/static/images/<id>)과 썸네일(/static/images/thumbs/<id>) 모두
            # 마지막 세그먼트가 원본 id이므로, 썸네일은 원본의 남은 TTL을 그대로 상속한다.
            image_id = path.rsplit("/", 1)[-1]
            remaining = _remaining_ttl(image_id) if _ID_RE.match(image_id or "") else -1
            if remaining <= 0:
                # 만료(또는 잘못된 id): 404. no-store로 만료 응답 자체가 캐시되는 것도 방지.
                return Response(status_code=404, headers={"Cache-Control": "no-store"})
        resp = await call_next(request)
        if path.startswith("/static/images/"):
            # 캐시 수명 = 남은 TTL. CDN/브라우저가 정확히 만료 시점에 캐시를 버리므로
            # TTL 지난 이미지가 캐시로 살아남지 않으면서도 엣지 캐싱(오리진 부하↓)은 유지된다.
            resp.headers["Cache-Control"] = f"public, max-age={remaining}, immutable"
        elif path == "/feed" or path == "/":
            # 실시간 피드/페이지는 절대 캐시 금지 (캐시되면 새 자짤이 안 뜸)
            resp.headers["Cache-Control"] = "no-store"
        return resp

    def _maintenance_response() -> HTMLResponse:
        m = static_dir / "maintenance.html"
        body = m.read_text(encoding="utf-8") if m.exists() else "<h1>잠시 점검 중입니다</h1>"
        return HTMLResponse(body, status_code=503, headers={"Retry-After": "3600"})

    @app.get("/", response_class=HTMLResponse)
    async def index():
        if _maintenance_on():
            return _maintenance_response()
        idx = static_dir / "index.html"
        if not idx.exists():
            return HTMLResponse("<h1>Gallery starting...</h1>")
        html = idx.read_text(encoding="utf-8")
        html = html.replace("{{TURNSTILE_SITEKEY}}", _ts_sitekey() if _ts_enabled() else "")
        return HTMLResponse(html)

    @app.get("/policy", response_class=HTMLResponse)
    async def policy():
        return _page("policy.html")

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

    # 브라우저가 루트 경로로 직접 요청하는 파비콘들. 내용이 안 바뀌므로 캐시 헤더 부여.
    for _fname, _mime in (
        ("favicon.ico", "image/x-icon"),
        ("favicon-16x16.png", "image/png"),
        ("favicon-32x32.png", "image/png"),
        ("apple-touch-icon.png", "image/png"),
        ("og-image.jpg", "image/jpeg"),  # 링크 공유 미리보기(Open Graph)
        ("robots.txt", "text/plain"),    # Sitemap 참조 포함 (CF 관리형 robots와 병합됨)
        ("sitemap.xml", "application/xml"),
    ):
        def _make_favicon_route(fname=_fname, mime=_mime):
            async def _serve():
                f = static_dir / fname
                if not f.exists():
                    return PlainTextResponse("", status_code=404)
                return FileResponse(f, media_type=mime, headers={"Cache-Control": "public, max-age=604800"})
            return _serve

        app.add_api_route(f"/{_fname}", _make_favicon_route(), methods=["GET"])

    @app.get("/.well-known/security.txt", response_class=PlainTextResponse)
    async def security_txt():
        # RFC 9116: 보안 취약점 제보 연락처
        f = static_dir / "security.txt"
        if not f.exists():
            return PlainTextResponse("", status_code=404)
        return PlainTextResponse(f.read_text(encoding="utf-8"),
                                 headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/feed")
    async def feed(request: Request, limit: int = Query(60, ge=1, le=200)):
        if _maintenance_on() and request.headers.get("cf-connecting-ip"):
            return JSONResponse({"error": "maintenance"}, status_code=503)
        # Cloudflare를 거친 공개 요청(cf-connecting-ip 존재)만 Turnstile 통과를 요구한다.
        # 로컬 직접 접근(대시보드 등)은 헤더가 없어 그대로 허용.
        if _ts_enabled() and request.headers.get("cf-connecting-ip"):
            if not _ts_cookie_valid(request.cookies.get(_TS_COOKIE, "")):
                return JSONResponse({"error": "verification required"}, status_code=403)
        return JSONResponse(snapshot(limit))

    @app.post("/verify")
    async def verify(request: Request):
        if not _ts_enabled():
            return JSONResponse({"ok": True})
        try:
            body = await request.json()
        except Exception:
            body = {}
        token = body.get("token", "") if isinstance(body, dict) else ""
        ip = request.headers.get("cf-connecting-ip", "")
        ok = await asyncio.to_thread(_ts_siteverify, token, ip)
        if not ok:
            return JSONResponse({"ok": False}, status_code=403)
        resp = JSONResponse({"ok": True})
        resp.set_cookie(_TS_COOKIE, _ts_make_cookie(), max_age=_TS_TTL,
                        httponly=True, samesite="lax", secure=True)
        return resp

    @app.post("/like/{image_id}")
    async def like(image_id: str):
        n = like_image(image_id)
        if n is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"id": image_id, "likes": n})

    @app.get("/healthz")
    async def healthz():
        items = snapshot(_max_items())
        return JSONResponse({
            "ok": True,
            "items": len(items),
            "ttl": _ttl(),
            "maintenance": _maintenance_on(),
        })

    return app
