import io
from contextlib import nullcontext

import launcher


def test_wait_for_web_gallery_skips_when_gallery_disabled(monkeypatch):
    monkeypatch.delenv("WEB_GALLERY", raising=False)

    assert launcher.wait_for_web_gallery() is True


def test_wait_for_web_gallery_requires_ready_ingest(monkeypatch):
    monkeypatch.setenv("WEB_GALLERY", "1")
    monkeypatch.setenv("WEB_GALLERY_URL", "http://127.0.0.1:8000")
    monkeypatch.setattr(
        "launcher.request.urlopen",
        lambda url, timeout: nullcontext(io.BytesIO(b'{"ingest_configured": true}')),
    )

    assert launcher.wait_for_web_gallery() is True
