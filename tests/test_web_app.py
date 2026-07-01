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


def test_direct_image_url_cache_lifetime_is_capped_by_remaining_ttl(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, ttl_seconds=3600)
    item = save_bytes_to_gallery(PNG_BYTES, "sample-fresh.png", "title", "https://example.com")

    response = client.get(item["url"])

    assert response.status_code == 200
    assert response.content == PNG_BYTES
    # 캐시 수명은 남은 TTL 이하: CDN이 만료 시점에 캐시를 버려 TTL 누출이 없고,
    # 그 전까지는 엣지 캐싱(오리진 부하 감소)이 동작한다.
    cc = response.headers["cache-control"]
    assert cc.startswith("public, max-age=") and cc.endswith(", immutable")
    max_age = int(cc.split("max-age=")[1].split(",")[0])
    assert 0 < max_age <= 3600


def test_direct_image_url_cache_lifetime_shrinks_as_image_ages(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, ttl_seconds=3600)
    item = save_bytes_to_gallery(PNG_BYTES, "sample-aged.png", "title", "https://example.com")

    sidecar = tmp_path / "web_static" / "images" / f"{item['id']}.json"
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    meta["created_at"] = time.time() - 3000  # 3600초 TTL 중 3000초 경과
    sidecar.write_text(json.dumps(meta), encoding="utf-8")

    response = client.get(item["url"])

    assert response.status_code == 200
    max_age = int(response.headers["cache-control"].split("max-age=")[1].split(",")[0])
    assert max_age <= 600
