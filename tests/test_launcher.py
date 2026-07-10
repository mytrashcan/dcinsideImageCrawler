import io
from contextlib import nullcontext

import launcher

HEALTH_OK = b'{"ingest_configured": true}'


def fake_urlopen(*, probe_status: int):
    """healthz GET은 정상 응답, ingest 프로브 POST는 지정한 HTTP 상태를 돌려주는 가짜."""

    def _urlopen(url_or_request, timeout):
        if isinstance(url_or_request, launcher.request.Request):
            raise launcher.error.HTTPError(
                url_or_request.full_url, probe_status, "probe", None, None
            )
        return nullcontext(io.BytesIO(HEALTH_OK))

    return _urlopen


def test_wait_for_web_gallery_skips_when_gallery_disabled(monkeypatch):
    monkeypatch.delenv("WEB_GALLERY", raising=False)

    assert launcher.wait_for_web_gallery() is True


def test_wait_for_web_gallery_requires_ready_ingest_and_matching_token(monkeypatch):
    monkeypatch.setenv("WEB_GALLERY", "1")
    monkeypatch.setenv("WEB_GALLERY_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("WEB_INGEST_TOKEN", "tok")
    # 빈 바디 프로브는 인증 통과 시 이미지 검증 단계에서 415로 거절된다 = 토큰 일치.
    monkeypatch.setattr("launcher.request.urlopen", fake_urlopen(probe_status=415))

    assert launcher.wait_for_web_gallery() is True


def test_wait_for_web_gallery_fails_on_token_mismatch(monkeypatch):
    monkeypatch.setenv("WEB_GALLERY", "1")
    monkeypatch.setenv("WEB_GALLERY_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("WEB_INGEST_TOKEN", "rotated-token")
    monkeypatch.setenv("WEB_READY_TIMEOUT_SECONDS", "1")
    # 웹 프로세스가 옛 토큰으로 기동 중 → 프로브가 계속 401 → 시간 내 준비 실패로 종료해야 한다.
    monkeypatch.setattr("launcher.request.urlopen", fake_urlopen(probe_status=401))
    monkeypatch.setattr("launcher.time.sleep", lambda seconds: None)
    ticks = iter([0.0, 0.5, 1.5, 2.5, 3.5])
    monkeypatch.setattr("launcher.time.monotonic", lambda: next(ticks))

    assert launcher.wait_for_web_gallery() is False
