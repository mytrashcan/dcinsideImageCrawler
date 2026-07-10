"""Ensure the deployment dotenv file contains a non-empty web ingest token."""

from __future__ import annotations

import secrets
import sys
from collections.abc import Callable
from pathlib import Path

from dotenv import dotenv_values, set_key

TOKEN_KEY = "WEB_INGEST_TOKEN"


def generate_web_ingest_token() -> str:
    return secrets.token_hex(32)


def ensure_web_ingest_token(
    env_path: Path,
    token_factory: Callable[[], str] = generate_web_ingest_token,
) -> bool:
    """Create or replace an empty ingest token; return whether the file changed."""
    env_path.touch(mode=0o600, exist_ok=True)
    token = (dotenv_values(env_path).get(TOKEN_KEY) or "").strip()
    if token:
        return False

    set_key(env_path, TOKEN_KEY, token_factory(), quote_mode="never")
    return True


def main() -> int:
    env_path = Path(sys.argv[1] if len(sys.argv) > 1 else ".env")
    if ensure_web_ingest_token(env_path):
        print(f"Generated {TOKEN_KEY} in {env_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
