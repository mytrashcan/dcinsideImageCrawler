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


def _big_jpeg(width=1200, height=800) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), "#336699").save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def test_large_image_gets_thumbnail_and_feed_prefers_it(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, ttl_seconds=3600)
    item = save_bytes_to_gallery(_big_jpeg(), "big.jpg", "title", "https://example.com")

    assert item["thumb"] == f"/static/images/thumbs/{item['id']}"
    thumb_path = tmp_path / "web_static" / "images" / "thumbs" / item["id"]
    original_path = tmp_path / "web_static" / "images" / item["id"]
    assert thumb_path.is_file()
    # 전송량 최적화가 목적이므로 썸네일이 원본보다 실제로 작아야 한다.
    assert thumb_path.stat().st_size < original_path.stat().st_size

    feed = client.get("/feed").json()
    assert feed[0]["thumb"] == item["thumb"]

    response = client.get(item["thumb"])
    assert response.status_code == 200
    # 썸네일도 원본과 같은 '남은 TTL' 캐시 정책을 상속한다.
    max_age = int(response.headers["cache-control"].split("max-age=")[1].split(",")[0])
    assert 0 < max_age <= 3600


def test_small_image_skips_thumbnail_and_falls_back_to_original(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, ttl_seconds=3600)
    item = save_bytes_to_gallery(PNG_BYTES, "tiny.png", "title", "")

    assert item["thumb"] == item["url"]
    assert not (tmp_path / "web_static" / "images" / "thumbs" / item["id"]).exists()
    feed = client.get("/feed").json()
    assert feed[0]["thumb"] == item["url"]


def test_expired_image_deletes_thumbnail_too(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, ttl_seconds=3600)
    item = save_bytes_to_gallery(_big_jpeg(), "big-expired.jpg", "title", "")

    thumb_path = tmp_path / "web_static" / "images" / "thumbs" / item["id"]
    assert thumb_path.is_file()

    sidecar = tmp_path / "web_static" / "images" / f"{item['id']}.json"
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    meta["created_at"] = time.time() - 7200
    sidecar.write_text(json.dumps(meta), encoding="utf-8")

    assert client.get(item["thumb"]).status_code == 404
    assert not thumb_path.exists()
    assert not (tmp_path / "web_static" / "images" / item["id"]).exists()


def test_feed_exposes_image_dimensions(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, ttl_seconds=3600)
    save_bytes_to_gallery(_big_jpeg(1200, 800), "dim.jpg", "title", "")

    feed = client.get("/feed").json()
    # 프론트가 로드 전에 카드 높이를 예약할 수 있도록 원본 치수를 내려보낸다.
    assert feed[0]["w"] == 1200
    assert feed[0]["h"] == 800


def test_feed_exposes_source_gallery(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, ttl_seconds=3600)
    save_bytes_to_gallery(PNG_BYTES, "g.png", "title", "", gallery="stariload")

    feed = client.get("/feed").json()
    # 갤러리별 필터를 위해 출처 갤러리명을 내려보낸다 (미기록 이미지는 빈 문자열)
    assert feed[0]["gallery"] == "stariload"


def test_discovery_endpoints_are_served(monkeypatch, tmp_path):
    import shutil

    client = make_client(monkeypatch, tmp_path, ttl_seconds=3600)
    static = tmp_path / "web_static"
    for f in ("robots.txt", "sitemap.xml", "security.txt"):
        shutil.copy(f"web_static/{f}", static / f)

    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    assert "Sitemap: https://dcselfie.win/sitemap.xml" in robots.text

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    assert "<loc>https://dcselfie.win/</loc>" in sitemap.text

    sec = client.get("/.well-known/security.txt")
    assert sec.status_code == 200
    assert "Contact: mailto:" in sec.text and "Expires:" in sec.text


def test_pwa_manifest_is_served(monkeypatch, tmp_path):
    import shutil

    client = make_client(monkeypatch, tmp_path, ttl_seconds=3600)
    shutil.copy("web_static/manifest.json", tmp_path / "web_static" / "manifest.json")

    r = client.get("/manifest.json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/manifest+json")
    m = r.json()
    assert m["display"] == "standalone"
    assert any(i["sizes"] == "512x512" for i in m["icons"])


def test_like_same_ip_does_not_increment_twice(monkeypatch, tmp_path):
    import web_app
    monkeypatch.setattr(web_app, "_like_ip_seen", web_app.LRUCache(100))
    monkeypatch.setattr(web_app, "_like_ip_rate", {})

    client = make_client(monkeypatch, tmp_path, ttl_seconds=3600)
    item = save_bytes_to_gallery(PNG_BYTES, "like.png", "title", "")

    r1 = client.post(f"/like/{item['id']}")
    r2 = client.post(f"/like/{item['id']}")
    # localStorage 우회(같은 IP가 스크립트로 반복 호출)해도 서버에서 중복 증가를 막는다.
    assert r1.json()["likes"] == 1
    assert r2.json()["likes"] == 1


def test_like_different_ip_can_still_increment(monkeypatch, tmp_path):
    import web_app
    monkeypatch.setattr(web_app, "_like_ip_seen", web_app.LRUCache(100))
    monkeypatch.setattr(web_app, "_like_ip_rate", {})

    client = make_client(monkeypatch, tmp_path, ttl_seconds=3600)
    item = save_bytes_to_gallery(PNG_BYTES, "like2.png", "title", "")

    r1 = client.post(f"/like/{item['id']}", headers={"cf-connecting-ip": "1.1.1.1"})
    r2 = client.post(f"/like/{item['id']}", headers={"cf-connecting-ip": "2.2.2.2"})
    assert r1.json()["likes"] == 1
    assert r2.json()["likes"] == 2


def test_like_rate_limit_returns_429_past_threshold(monkeypatch, tmp_path):
    import web_app
    monkeypatch.setattr(web_app, "_like_ip_seen", web_app.LRUCache(100))
    monkeypatch.setattr(web_app, "_like_ip_rate", {})
    monkeypatch.setattr(web_app, "_LIKE_RATE_MAX", 3)

    client = make_client(monkeypatch, tmp_path, ttl_seconds=3600)
    items = [save_bytes_to_gallery(PNG_BYTES, f"rl{i}.png", "title", "") for i in range(5)]

    headers = {"cf-connecting-ip": "9.9.9.9"}
    statuses = [client.post(f"/like/{it['id']}", headers=headers).status_code for it in items]
    assert statuses[:3] == [200, 200, 200]
    assert 429 in statuses[3:]


def test_api_docs_are_disabled(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, ttl_seconds=3600)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_security_headers_present_on_every_response(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, ttl_seconds=3600)
    r = client.get("/feed")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "max-age=" in r.headers["strict-transport-security"]


def test_feed_rate_limit_returns_429_past_threshold(monkeypatch, tmp_path):
    import web_app
    monkeypatch.setattr(web_app, "_feed_ip_rate", {})
    monkeypatch.setattr(web_app, "_FEED_RATE_MAX", 3)

    client = make_client(monkeypatch, tmp_path, ttl_seconds=3600)
    headers = {"cf-connecting-ip": "8.8.8.8"}
    statuses = [client.get("/feed", headers=headers).status_code for _ in range(5)]
    assert statuses[:3] == [200, 200, 200]
    assert 429 in statuses[3:]
