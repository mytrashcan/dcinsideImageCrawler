from pathlib import Path

import pytest
from dotenv import dotenv_values

from scripts.ensure_web_ingest_token import ensure_web_ingest_token


@pytest.mark.parametrize("empty_value", ["", '""', "''", "   "])
def test_replaces_empty_ingest_token(tmp_path: Path, empty_value: str):
    env_path = tmp_path / ".env"
    env_path.write_text(f"DISCORD_TOKEN=keep-me\nWEB_INGEST_TOKEN={empty_value}\n")

    changed = ensure_web_ingest_token(env_path, token_factory=lambda: "generated-token")

    values = dotenv_values(env_path)
    assert changed is True
    assert values["WEB_INGEST_TOKEN"] == "generated-token"
    assert values["DISCORD_TOKEN"] == "keep-me"


def test_creates_missing_env_file_and_token(tmp_path: Path):
    env_path = tmp_path / ".env"

    changed = ensure_web_ingest_token(env_path, token_factory=lambda: "generated-token")

    assert changed is True
    assert dotenv_values(env_path)["WEB_INGEST_TOKEN"] == "generated-token"


def test_preserves_existing_ingest_token(tmp_path: Path):
    env_path = tmp_path / ".env"
    original = "WEB_INGEST_TOKEN=existing-token\n"
    env_path.write_text(original)

    changed = ensure_web_ingest_token(env_path, token_factory=lambda: "replacement-token")

    assert changed is False
    assert env_path.read_text() == original
