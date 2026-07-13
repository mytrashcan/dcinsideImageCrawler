"""Bounded streaming downloads for untrusted source media."""

from __future__ import annotations

from collections.abc import Mapping

import requests


class MediaDownloadTooLarge(ValueError):
    pass


def download_limited(
    client: object,
    url: str,
    *,
    headers: Mapping[str, str] | None,
    timeout: float,
    max_bytes: int,
    chunk_size: int = 64 * 1024,
) -> bytes:
    """Stream a response into memory while enforcing a hard byte limit."""
    response = client.get(url, headers=headers, timeout=timeout, stream=True)
    try:
        response.raise_for_status()
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError as exc:
                raise requests.exceptions.InvalidHeader("invalid content-length") from exc
            if declared_size > max_bytes:
                raise MediaDownloadTooLarge("media exceeds download limit")

        data = bytearray()
        for chunk in response.iter_content(chunk_size=chunk_size):
            if not chunk:
                continue
            data.extend(chunk)
            if len(data) > max_bytes:
                raise MediaDownloadTooLarge("media exceeds download limit")
        return bytes(data)
    finally:
        response.close()
