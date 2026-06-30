import os
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

_state = None


class FeedState:
    def __init__(self):
        self.feed = []
        # feed는 봇 스레드(enqueue)와 웹 스레드(snapshot/_prune)에서 동시에 변경되므로 락으로 보호한다.
        self._lock = threading.RLock()
        self.ttl = int(os.getenv("WEB_IMAGE_TTL_SECONDS", str(3 * 60 * 60)))
        self.max_items = int(os.getenv("WEB_FEED_MAX_ITEMS", "120"))
        self.static_dir = Path(os.getenv("WEB_STATIC_DIR", "web_static"))
        self.upload_dir = self.static_dir / "images"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.static_dir.mkdir(parents=True, exist_ok=True)

    def now(self):
        return time.time()

    def _remove(self, paths):
        for p in paths:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass

    def _prune(self):
        # 디스크 파일명은 item["id"](uuid)이다. item["filename"]은 원본 이름이라 삭제 경로로 쓰면 안 된다.
        with self._lock:
            cutoff = self.now() - self.ttl
            kept = []
            remove = []
            for item in self.feed:
                if item["created_at"] >= cutoff:
                    kept.append(item)
                else:
                    remove.append(self.upload_dir / item["id"])
            self.feed = kept[: self.max_items]
            if len(kept) > self.max_items:
                excess = kept[self.max_items :]
                for item in excess:
                    remove.append(self.upload_dir / item["id"])
        self._remove(remove)

    def _gc_orphans(self):
        with self._lock:
            if not self.feed:
                return
            valid = {item["id"] for item in self.feed}
            cutoff = self.now() - self.ttl
            remove = []
            for p in self.upload_dir.iterdir():
                if p.is_file() and p.name not in valid:
                    try:
                        if p.stat().st_mtime < cutoff:
                            remove.append(p)
                    except OSError:
                        pass
        self._remove(remove)

    def find_by_filename(self, filename):
        if not filename:
            return None
        with self._lock:
            for item in self.feed:
                if item["filename"] == filename:
                    return item
        return None

    def enqueue(self, item):
        self._prune()
        with self._lock:
            self.feed.insert(0, item)
            if len(self.feed) > self.max_items:
                overflow = self.feed[self.max_items :]
                remove = [self.upload_dir / i["id"] for i in overflow]
                self.feed = self.feed[: self.max_items]
            else:
                remove = []
        self._remove(remove)

    def snapshot(self, limit=120):
        self._prune()
        self._gc_orphans()
        with self._lock:
            return self.feed[: min(limit, len(self.feed))]


def get_state() -> FeedState:
    global _state
    if _state is None:
        _state = FeedState()
    return _state


def save_bytes_to_gallery(data: bytes, filename: str, title: str = "") -> dict:
    """Internal helper: save raw image bytes into the gallery feed.

    동일 이미지는 디스코드(채널 수만큼)+텔레그램 경로로 여러 번 들어오므로,
    아직 피드에 살아있는 같은 원본 filename은 중복 적재하지 않는다.
    """
    state = get_state()
    existing = state.find_by_filename(filename)
    if existing is not None:
        return existing
    ext = os.path.splitext(filename or "")[1].lower() or ".jpg"
    if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        ext = ".jpg"
    name = f"{uuid.uuid4().hex}{ext}"
    path = state.upload_dir / name
    try:
        path.write_bytes(data)
    except OSError:
        return {}
    item = {
        "id": name,
        "filename": filename or name,
        "url": f"/static/images/{name}",
        "title": title,
        "created_at": state.now(),
    }
    state.enqueue(item)
    return item


def create_app() -> FastAPI:
    state = get_state()
    app = FastAPI(title="dcinsideImageCrawler Gallery")
    app.mount("/static", StaticFiles(directory=str(state.static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        idx = state.static_dir / "index.html"
        if not idx.exists():
            return HTMLResponse("<h1>Gallery starting...</h1>")
        return idx.read_text(encoding="utf-8")

    @app.get("/feed")
    async def feed(limit: int = Query(60, ge=1, le=200)):
        return JSONResponse(state.snapshot(limit))

    @app.get("/healthz")
    async def healthz():
        state._prune()
        state._gc_orphans()
        return JSONResponse({"ok": True, "items": len(state.feed), "ttl": state.ttl})

    return app
