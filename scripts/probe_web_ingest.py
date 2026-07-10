"""Verify that the deployed web process accepts the configured ingest token."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib import error, request

from dotenv import dotenv_values

READY_STATUS = 415


def probe_web_ingest(base_url: str, token: str) -> bool:
    """Return true only when auth succeeds and the empty image is rejected."""
    if not token:
        return False
    try:
        probe = request.Request(
            f"{base_url.rstrip('/')}/internal/images",
            data=b"",
            headers={
                "X-Ingest-Token": token,
                "Content-Type": "application/octet-stream",
            },
            method="POST",
        )
        with request.urlopen(probe, timeout=2) as response:
            status = response.status
    except error.HTTPError as exc:
        status = exc.code
    except (OSError, ValueError, error.URLError):
        return False
    return status == READY_STATUS


def main() -> int:
    env_path = Path(sys.argv[1] if len(sys.argv) > 1 else ".env")
    values = dotenv_values(env_path)
    token = (os.getenv("WEB_INGEST_TOKEN") or values.get("WEB_INGEST_TOKEN") or "").strip()
    base_url = (
        os.getenv("WEB_GALLERY_URL")
        or values.get("WEB_GALLERY_URL")
        or "http://127.0.0.1:8000"
    ).strip()
    return 0 if probe_web_ingest(base_url, token) else 1


if __name__ == "__main__":
    raise SystemExit(main())
