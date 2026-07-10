from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image

import web_app
from Module.memory_gallery import MemoryGalleryStore
from web_app import create_app


def image_bytes(size=(64, 64), *, fmt="PNG", color="#336699") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format=fmt)
    return output.getvalue()


def make_store(*, clock=None, max_items=10, max_bytes=1024 * 1024, ttl=3600, thumb=480):
    return MemoryGalleryStore(
        max_items=max_items,
        max_bytes=max_bytes,
        max_image_bytes=max_bytes,
        ttl_seconds=ttl,
        thumbnail_width=thumb,
        clock=clock or __import__("time").time,
    )


def make_client(monkeypatch, tmp_path, store=None) -> tuple[TestClient, MemoryGalleryStore]:
    static_dir = tmp_path / "web_static"
    static_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(web_app.app_config, "web_static_dir", str(static_dir))
    monkeypatch.setattr(web_app.app_config, "web_ingest_token", "test-secret")
    monkeypatch.setattr(web_app.app_config, "turnstile_secret", "")
    monkeypatch.setattr(web_app, "_like_ip_seen", web_app.LRUCache(100))
    monkeypatch.setattr(web_app, "_like_ip_rate", {})
    monkeypatch.setattr(web_app, "_feed_ip_rate", {})
    gallery_store = store or make_store()
    return TestClient(create_app(gallery_store)), gallery_store


def ingest(client: TestClient, data: bytes, filename="sample.png", **params):
    return client.post(
        "/internal/images",
        params={"filename": filename, **params},
        content=data,
        headers={"X-Ingest-Token": "test-secret", "Content-Type": "application/octet-stream"},
    )


def test_ingest_serves_image_without_writing_to_disk(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path)

    result = ingest(
        client,
        image_bytes(),
        title="title",
        link="https://example.com/post",
        gallery="test",
    )

    assert result.status_code == 200
    item = result.json()
    assert item["url"].startswith("/images/")
    response = client.get(item["url"])
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert not (tmp_path / "web_static" / "images").exists()


def test_ingest_requires_shared_secret(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path)

    response = client.post("/internal/images", content=image_bytes())

    assert response.status_code == 401


def test_ingest_rejects_invalid_image(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path)

    response = ingest(client, b"not-an-image")

    assert response.status_code == 415


def test_ingest_non_ascii_token_returns_401_not_500(monkeypatch, tmp_path):
    """비ASCII 헤더는 str hmac.compare_digest에서 TypeError → 500이 되면 안 된다."""
    client, _ = make_client(monkeypatch, tmp_path)

    response = client.post(
        "/internal/images",
        content=image_bytes(),
        headers={b"x-ingest-token": "caf\xe9".encode("latin-1")},
    )

    assert response.status_code == 401


def test_ingest_empty_body_with_valid_token_returns_415_not_401(monkeypatch, tmp_path):
    """launcher의 기동 프로브 계약: 빈 바디 + 올바른 토큰 = 415(인증 통과), 틀린 토큰 = 401."""
    client, _ = make_client(monkeypatch, tmp_path)

    assert ingest(client, b"").status_code == 415
    wrong = client.post(
        "/internal/images", content=b"", headers={"X-Ingest-Token": "wrong-token"}
    )
    assert wrong.status_code == 401


def test_store_evicts_oldest_by_item_limit():
    store = make_store(max_items=2)
    first = store.put(image_bytes(color="red"), "1.png")
    second = store.put(image_bytes(color="green"), "2.png")
    third = store.put(image_bytes(color="blue"), "3.png")

    assert store.get(first["id"]) is None
    assert store.get(second["id"]) is not None
    assert store.get(third["id"]) is not None
    assert store.stats()["items"] == 2


def test_store_evicts_oldest_by_total_bytes():
    first_data = image_bytes(size=(128, 128), color="red")
    second_data = image_bytes(size=(128, 128), color="blue")
    store = make_store(max_bytes=len(first_data) + len(second_data) - 1, thumb=0)

    first = store.put(first_data, "1.png")
    second = store.put(second_data, "2.png")

    assert store.get(first["id"]) is None
    assert store.get(second["id"]) is not None
    assert store.stats()["memory_bytes"] <= store.max_bytes


def test_store_expires_items_by_ttl():
    now = [1000.0]
    store = make_store(clock=lambda: now[0], ttl=60)
    item = store.put(image_bytes(), "sample.png")

    now[0] += 61

    assert store.get(item["id"]) is None
    assert store.snapshot(10) == []


def test_process_restart_starts_with_empty_store(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path)
    item = ingest(client, image_bytes()).json()
    assert client.get(item["url"]).status_code == 200

    restarted_client, restarted_store = make_client(monkeypatch, tmp_path, make_store())

    assert restarted_store.snapshot(10) == []
    assert restarted_client.get(item["url"]).status_code == 404


def test_large_image_has_in_memory_thumbnail(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path)

    item = ingest(client, image_bytes((1200, 800), fmt="JPEG"), "large.jpg").json()

    assert item["thumb"].endswith("?thumbnail=1")
    thumb = client.get(item["thumb"])
    original = client.get(item["url"])
    assert thumb.status_code == 200
    assert len(thumb.content) < len(original.content)
    assert thumb.headers["cache-control"] == "no-store"


def test_duplicate_content_is_suppressed(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path)
    data = image_bytes()

    assert ingest(client, data, "first.png").json()
    assert ingest(client, data, "second.png").json() == {}


def test_like_state_is_kept_in_memory(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path)
    item = ingest(client, image_bytes()).json()

    first = client.post(f"/like/{item['id']}")
    second = client.post(f"/like/{item['id']}")

    assert first.json()["likes"] == 1
    assert second.json()["likes"] == 1


def test_health_reports_memory_and_freshness(monkeypatch, tmp_path):
    now = [1000.0]
    store = make_store(clock=lambda: now[0])
    client, _ = make_client(monkeypatch, tmp_path, store)
    monkeypatch.setattr(web_app.app_config, "web_freshness_seconds", 30)
    ingest(client, image_bytes())
    now[0] += 31

    health = client.get("/healthz").json()

    assert health["items"] == 1
    assert health["memory_bytes"] > 0
    assert health["ingest_configured"] is True
    assert health["fresh"] is False


def test_health_empty_store_goes_stale_after_grace(monkeypatch, tmp_path):
    """전부 만료돼 빈 스토어가 fresh=true로 돌아가 크롤러 전멸을 가리면 안 된다."""
    now = [1000.0]
    store = make_store(clock=lambda: now[0], ttl=60)
    client, _ = make_client(monkeypatch, tmp_path, store)
    monkeypatch.setattr(web_app.app_config, "web_freshness_seconds", 30)

    assert client.get("/healthz").json()["fresh"] is True  # 기동 직후 그레이스

    ingest(client, image_bytes())
    now[0] += 61  # TTL 경과 → 스토어가 다시 빔

    health = client.get("/healthz").json()
    assert health["items"] == 0
    assert health["fresh"] is False


def test_startup_removes_legacy_disk_cache(monkeypatch, tmp_path):
    legacy = tmp_path / "web_static" / "images" / "thumbs"
    legacy.mkdir(parents=True)
    (legacy / "old.jpg").write_bytes(b"old")

    make_client(monkeypatch, tmp_path)

    assert not (tmp_path / "web_static" / "images").exists()


def test_feed_and_api_docs_policy(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path)
    ingest(client, image_bytes(), gallery="test")

    feed = client.get("/feed")

    assert feed.status_code == 200
    assert feed.json()[0]["gallery"] == "test"
    assert feed.headers["cache-control"] == "no-store"
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_security_headers_present(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path)

    response = client.get("/healthz")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
