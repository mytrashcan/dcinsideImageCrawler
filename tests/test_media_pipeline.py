import asyncio
import io
from unittest.mock import MagicMock

import pytest

from Module.media_pipeline import MediaPipeline


@pytest.mark.asyncio
async def test_web_publish_is_enqueued_without_waiting_for_network() -> None:
    pipeline = MediaPipeline(MagicMock(), MagicMock(), [], web_gallery_enabled=True)
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_publish(*args, **kwargs):
        started.set()
        await release.wait()
        return {"id": "x"}

    pipeline.gallery_client.publish_async = slow_publish
    queued = await pipeline.attach_to_web_gallery(b"image", "x.jpg", 0, "title", "link")

    assert queued == {"queued": True}
    await started.wait()
    release.set()
    await pipeline.close()


@pytest.mark.asyncio
async def test_full_web_queue_drops_without_blocking(monkeypatch) -> None:
    monkeypatch.setattr("Module.config.app_config.web_upload_queue_size", 1)
    pipeline = MediaPipeline(MagicMock(), MagicMock(), [], web_gallery_enabled=True)
    pipeline._ensure_web_worker = MagicMock()
    pipeline._web_queue = asyncio.Queue(maxsize=1)
    pipeline._web_queue.put_nowait(((), {}))

    assert await pipeline.attach_to_web_gallery(b"next", "x.jpg", 0, "", "") == {}


def test_web_image_uses_original_only_within_ingest_limit(monkeypatch) -> None:
    monkeypatch.setattr("Module.config.app_config.web_ingest_max_mb", 1)
    compressed = io.BytesIO(b"compressed")

    assert MediaPipeline._web_image_data({
        "original_data": b"original",
        "discord_buffer": compressed,
    }) == b"original"
    assert MediaPipeline._web_image_data({
        "original_data": b"x" * (1024 * 1024 + 1),
        "discord_buffer": compressed,
    }) == b"compressed"
