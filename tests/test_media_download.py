from unittest.mock import MagicMock

import pytest

from Module.media_download import MediaDownloadTooLarge, download_limited


def make_response(chunks: list[bytes], content_length: int | None = None) -> MagicMock:
    response = MagicMock()
    response.headers = {}
    if content_length is not None:
        response.headers["content-length"] = str(content_length)
    response.iter_content.return_value = chunks
    return response


def test_download_limited_streams_within_limit() -> None:
    client = MagicMock()
    response = make_response([b"abc", b"def"], 6)
    client.get.return_value = response

    assert download_limited(
        client, "https://example.com/image", headers=None, timeout=1, max_bytes=6
    ) == b"abcdef"
    response.close.assert_called_once()


def test_download_limited_rejects_content_length_early() -> None:
    client = MagicMock()
    response = make_response([], 7)
    client.get.return_value = response

    with pytest.raises(MediaDownloadTooLarge):
        download_limited(
            client, "https://example.com/image", headers=None, timeout=1, max_bytes=6
        )


def test_download_limited_rejects_chunked_overflow() -> None:
    client = MagicMock()
    response = make_response([b"abcd", b"efgh"])
    client.get.return_value = response

    with pytest.raises(MediaDownloadTooLarge):
        download_limited(
            client, "https://example.com/image", headers=None, timeout=1, max_bytes=6
        )
