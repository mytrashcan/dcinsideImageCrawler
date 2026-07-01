import json
import time

from fastapi.testclient import TestClient

from web_app import create_app, save_bytes_to_gallery

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def make_client(monkeypatch, tmp_path, ttl_seconds=3600):
    monkeypatch.setenv("WEB_STATIC_DIR", str(tmp_path / "web_static"))
    monkeypatch.setenv("WEB_IMAGE_TTL_SECONDS", str(ttl_seconds))
    monkeypatch.setenv("TURNSTILE_SECRET", "")
    return TestClient(create_app())


def test_direct_image_url_expires_even_without_feed_poll(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, ttl_seconds=3600)
    item = save_bytes_to_gallery(PNG_BYTES, "sample-expired.png", "title", "https://example.com")

    image_path = tmp_path / "web_static" / "images" / item["id"]
    sidecar = image_path.parent / f"{item['id']}.json"
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    meta["created_at"] = time.time() - 7200
    sidecar.write_text(json.dumps(meta), encoding="utf-8")

    response = client.get(item["url"])

    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert not image_path.exists()
    assert not sidecar.exists()


def test_direct_image_url_is_served_with_no_store_cache_control(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, ttl_seconds=3600)
    item = save_bytes_to_gallery(PNG_BYTES, "sample-fresh.png", "title", "https://example.com")

    response = client.get(item["url"])

    assert response.status_code == 200
    assert response.content == PNG_BYTES
    assert response.headers["cache-control"] == "no-store"
