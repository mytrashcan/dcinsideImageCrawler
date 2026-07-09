"""Loopback adapter used by crawler processes to publish ephemeral images."""

from __future__ import annotations

import asyncio
import logging
import time

import requests

from Module.config import app_config

logger = logging.getLogger(__name__)


class GalleryClient:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        *,
        max_attempts: int = 3,
        retry_delay_seconds: float = 1.0,
    ):
        self.base_url = (base_url or app_config.web_gallery_url).rstrip("/")
        self.token = token if token is not None else app_config.web_ingest_token
        self.max_attempts = max(1, max_attempts)
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)

    def publish(
        self,
        data: bytes,
        filename: str,
        *,
        title: str = "",
        link: str = "",
        gallery: str = "",
    ) -> dict:
        if not data or not self.token:
            if not self.token:
                logger.error("WEB_INGEST_TOKEN이 없어 웹 갤러리 전송을 건너뜁니다.")
            return {}
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = requests.post(
                    f"{self.base_url}/internal/images",
                    params={
                        "filename": filename or "",
                        "title": title or "",
                        "link": link or "",
                        "gallery": gallery or "",
                    },
                    data=data,
                    headers={
                        "X-Ingest-Token": self.token,
                        "Content-Type": "application/octet-stream",
                    },
                    timeout=10,
                )
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                if attempt == self.max_attempts:
                    logger.warning("웹 갤러리 전송 실패 (%s): %s", filename, exc)
                    return {}
                logger.warning(
                    "웹 갤러리 전송 재시도 %s/%s (%s): %s",
                    attempt,
                    self.max_attempts,
                    filename,
                    exc,
                )
                time.sleep(self.retry_delay_seconds * attempt)
        return {}

    async def publish_async(self, *args, **kwargs) -> dict:
        return await asyncio.to_thread(self.publish, *args, **kwargs)


def attach_web_gallery(message_sender, gallery: str = "", client: GalleryClient | None = None) -> None:
    """Publish successfully sent Discord/Telegram buffers to the web process."""
    gallery_client = client or GalleryClient()
    original_discord = message_sender.send_to_discord
    original_telegram = message_sender.send_to_telegram

    async def discord_with_web(channel, title, image_buffer, filename, url=None):
        sent = await original_discord(channel, title, image_buffer, filename, url)
        if sent:
            try:
                data = image_buffer.getvalue()
            except (OSError, ValueError, AttributeError):
                data = b""
            await gallery_client.publish_async(
                data, filename or "", title=title or "", link=url or "", gallery=gallery
            )
        return sent

    async def telegram_with_web(image_buffer, filename=None, is_gif=False, max_retries=3):
        sent = await original_telegram(image_buffer, filename, is_gif, max_retries)
        if sent:
            try:
                data = image_buffer.getvalue()
            except (OSError, ValueError, AttributeError):
                data = b""
            await gallery_client.publish_async(data, filename or "", gallery=gallery)
        return sent

    message_sender.send_to_discord = discord_with_web
    message_sender.send_to_telegram = telegram_with_web
