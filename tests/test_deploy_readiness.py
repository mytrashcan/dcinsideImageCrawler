from contextlib import nullcontext
from urllib import error

from scripts import probe_web_ingest


class ReadyResponse:
    status = 415


def test_probe_accepts_authenticated_empty_image_contract(monkeypatch):
    monkeypatch.setattr(
        probe_web_ingest.request,
        "urlopen",
        lambda probe, timeout: nullcontext(ReadyResponse()),
    )

    assert probe_web_ingest.probe_web_ingest("http://127.0.0.1:8000", "token") is True


def test_probe_accepts_415_http_error_from_web_app(monkeypatch):
    def reject_empty_image(probe, timeout):
        raise error.HTTPError(probe.full_url, 415, "invalid image", None, None)

    monkeypatch.setattr(probe_web_ingest.request, "urlopen", reject_empty_image)

    assert probe_web_ingest.probe_web_ingest("http://127.0.0.1:8000", "token") is True


def test_probe_rejects_wrong_token(monkeypatch):
    def reject_token(probe, timeout):
        raise error.HTTPError(probe.full_url, 401, "unauthorized", None, None)

    monkeypatch.setattr(probe_web_ingest.request, "urlopen", reject_token)

    assert probe_web_ingest.probe_web_ingest("http://127.0.0.1:8000", "token") is False


def test_probe_rejects_unexpected_success_status(monkeypatch):
    class UnexpectedResponse:
        status = 200

    monkeypatch.setattr(
        probe_web_ingest.request,
        "urlopen",
        lambda probe, timeout: nullcontext(UnexpectedResponse()),
    )

    assert probe_web_ingest.probe_web_ingest("http://127.0.0.1:8000", "token") is False


def test_probe_rejects_missing_token():
    assert probe_web_ingest.probe_web_ingest("http://127.0.0.1:8000", "") is False


def test_cli_reads_token_and_url_from_dotenv(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "WEB_INGEST_TOKEN=dotenv-token\nWEB_GALLERY_URL=http://127.0.0.1:9000\n"
    )
    observed = {}

    def record_probe(base_url, token):
        observed.update(base_url=base_url, token=token)
        return True

    monkeypatch.delenv("WEB_INGEST_TOKEN", raising=False)
    monkeypatch.delenv("WEB_GALLERY_URL", raising=False)
    monkeypatch.setattr(probe_web_ingest, "probe_web_ingest", record_probe)
    monkeypatch.setattr(probe_web_ingest.sys, "argv", ["probe_web_ingest.py", str(env_path)])

    assert probe_web_ingest.main() == 0
    assert observed == {"base_url": "http://127.0.0.1:9000", "token": "dotenv-token"}
