import io
from unittest.mock import AsyncMock, MagicMock

import pytest
import requests

from Module.gallery_client import GalleryClient, attach_web_gallery


def test_publish_sends_bytes_to_authenticated_internal_endpoint(monkeypatch):
    response = MagicMock()
    response.json.return_value = {"id": "abc.jpg"}
    post = MagicMock(return_value=response)
    monkeypatch.setattr("Module.gallery_client.requests.post", post)
    client = GalleryClient("http://127.0.0.1:8000", "secret")

    result = client.publish(
        b"image-bytes",
        "sample.jpg",
        title="title",
        link="https://example.com",
        gallery="test",
    )

    assert result == {"id": "abc.jpg"}
    post.assert_called_once()
    kwargs = post.call_args.kwargs
    assert kwargs["data"] == b"image-bytes"
    assert kwargs["headers"]["X-Ingest-Token"] == "secret"
    assert kwargs["params"]["gallery"] == "test"


def test_publish_retries_when_web_process_is_starting(monkeypatch):
    response = MagicMock()
    response.json.return_value = {"id": "abc.jpg"}
    post = MagicMock(side_effect=[requests.ConnectionError("not ready"), response])
    monkeypatch.setattr("Module.gallery_client.requests.post", post)
    sleep = MagicMock()
    monkeypatch.setattr("Module.gallery_client.time.sleep", sleep)
    client = GalleryClient("http://127.0.0.1:8000", "secret", retry_delay_seconds=0.25)

    assert client.publish(b"image-bytes", "sample.jpg") == {"id": "abc.jpg"}
    assert post.call_count == 2
    sleep.assert_called_once_with(0.25)


@pytest.mark.asyncio
async def test_sender_wrapper_publishes_only_after_successful_delivery():
    sender = MagicMock()
    sender.send_to_discord = AsyncMock(side_effect=[False, True])
    sender.send_to_telegram = AsyncMock(return_value=False)
    client = MagicMock()
    client.publish_async = AsyncMock(return_value={"id": "abc.jpg"})
    attach_web_gallery(sender, "test", client)
    buffer = io.BytesIO(b"image")

    await sender.send_to_discord(MagicMock(), "title", buffer, "sample.jpg", "https://example.com")
    await sender.send_to_discord(MagicMock(), "title", buffer, "sample.jpg", "https://example.com")

    client.publish_async.assert_awaited_once_with(
        b"image",
        "sample.jpg",
        title="title",
        link="https://example.com",
        gallery="test",
    )
