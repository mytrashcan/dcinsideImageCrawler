from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os
import time
import uuid

_state = None


class FeedState:
    def __init__(self):
        self.feed = []
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
        cutoff = self.now() - self.ttl
        kept = []
        remove = []
        for item in self.feed:
            if item["created_at"] >= cutoff:
                kept.append(item)
            else:
                remove.append(self.upload_dir / item["filename"])
        self.feed = kept[: self.max_items]
        if len(kept) > self.max_items:
            excess = kept[self.max_items :]
            for item in excess:
                remove.append(self.upload_dir / item["filename"])
        self._remove(remove)

    def _gc_orphans(self):
        if not self.feed:
            return
        valid = {item["filename"] for item in self.feed}
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

    def enqueue(self, item):
        self._prune()
        self._gc_orphans()
        self.feed.insert(0, item)
        if len(self.feed) > self.max_items:
            overflow = self.feed[self.max_items :]
            self._remove([self.upload_dir / i["filename"] for i in overflow])
            self.feed = self.feed[: self.max_items]

    def snapshot(self, limit=120):
        self._prune()
        self._gc_orphans()
        return self.feed[: min(limit, len(self.feed))]


def get_state() -> FeedState:
    global _state
    if _state is None:
        _state = FeedState()
    return _state


def save_bytes_to_gallery(data: bytes, filename: str, title: str = "") -> dict:
    """Internal helper: save raw image bytes into the gallery feed."""
    state = get_state()
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

    @app.post("/upload")
    async def upload(title: str = Query(""), filename: str = Query(""), file: bytes = b""):
        if not file:
            raise HTTPException(400, "empty upload")
        item = save_bytes_to_gallery(file, filename or "", title)
        if not item:
            raise HTTPException(500, "save failed")
        return JSONResponse(item)

    @app.get("/healthz")
    async def healthz():
        state._prune()
        state._gc_orphans()
        return JSONResponse({"ok": True, "items": len(state.feed), "ttl": state.ttl})

    return app
