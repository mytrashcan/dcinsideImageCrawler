"""
아카라이브 전용 Discord 봇.

DCInsideImageCrawler의 dcbot.py와 차이점:
- 게시글 내 모든 이미지를 추출하여 전송 (DCInside: 최상단 1개)
- Telegram 전송 없음 (순수 Discord 전용)
- 멀티 임베드 메시지 (한 게시글 여러 이미지를 하나의 메시지로)
- 모든 이미지 처리는 인메모리(BytesIO)로 수행되며, WEB_GALLERY=1 일 때만 공유 웹 갤러리용으로 디스크에 기록됨
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random

import discord
import requests

from Module.arca_crawler import ArcaliveCrawler
from Module.config import app_config
from Module.embeds import make_image_embed
from Module.image_handler import ImageHandler
from Module.media_pipeline import MediaPipeline
from Module.message_sender import MessageSender

logger = logging.getLogger(__name__)

# 아카라이브 임베드 색상 (블루 계열)
ARCA_EMBED_COLOR = 0x00A3FF
# Discord 메시지당 최대 임베드/파일 수
MAX_EMBEDS_PER_MSG = 10
# 게시글당 최대 이미지 수 (초과분은 무시)
MAX_IMAGES_PER_POST = 4
# 이미지 간 전송 딜레이(초)
INTER_IMAGE_DELAY = 1.0
# 이미지 다운로드 간격(초) — CDN rate limit 방지
IMAGE_DOWNLOAD_DELAY = 0.5


class ArcaBot(discord.Client):
    """아카라이브 게시글을 크롤링하여 디스코드로 전송하는 봇.

    Telegram 전송 없이 Discord embed만 사용.
    게시글 내 모든 이미지를 추출하여 전송한다.
    """

    def __init__(self, token: object, base_url: object, channel_ids: object, intents: object, gallery_name: object="") -> None:
        super().__init__(intents=intents)
        self.token = token
        self.base_url = base_url
        self.channel_ids = channel_ids
        self.web_gallery_name = gallery_name
        self.web_gallery_enabled = app_config.web_gallery
        self.crawler = ArcaliveCrawler(base_url)
        self.image_handler = ImageHandler()
        # Telegram 없이 Discord 전용 MessageSender
        self.message_sender = MessageSender(
            telegram_bot_token=None,
            telegram_chat_id=None,
            image_handler=self.image_handler,
        )
        self.media_pipeline = MediaPipeline(
            self.message_sender,
            self,
            self.channel_ids,
            image_handler=self.image_handler,
            web_gallery_enabled=self.web_gallery_enabled,
            web_gallery_name=self.web_gallery_name,
            discord_embed_color=ARCA_EMBED_COLOR,
            telegram_enabled=False,
        )

    async def on_ready(self) -> object:
        logger.info(f"[아카라이브] Logged in as {self.user}")
        await self.start_crawling()

    async def start_crawling(self) -> object:
        """주기적으로 새 게시글을 폴링한다."""
        while True:
            try:
                posts = await asyncio.to_thread(self.crawler.get_latest_posts)
                for post in posts:
                    logger.info(f"[아카라이브] 새 게시글: {post['title']} ({post['link']})")
                    await self.process_post(post)
            except discord.ConnectionClosed:
                logger.warning("[아카라이브] Discord 연결 끊김. 재연결 대기...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"[아카라이브] 크롤링 오류: {e}", exc_info=True)
            # 30~60초 간격 폴링
            delay = random.uniform(30, 60)
            await asyncio.sleep(delay)

    async def process_post(self, post: object) -> object:
        """게시글 내 모든 이미지를 추출하여 디스코드로 전송한다."""
        images = await asyncio.to_thread(
            self.crawler.extract_all_images, post["link"]
        )
        if not images:
            logger.info(f"[아카라이브] 이미지 없음: {post['title']}")
            return

        # 게시글당 최대 이미지 수 제한
        if len(images) > MAX_IMAGES_PER_POST:
            logger.info(f"[아카라이브] 이미지 {len(images)}개 중 {MAX_IMAGES_PER_POST}개만 처리: {post['title']}")
            images = images[:MAX_IMAGES_PER_POST]

        title = post["title"]
        link = post["link"]
        logger.info(f"[아카라이브] {title}: {len(images)}개 이미지 추출됨")

        downloaded = await self._download_and_process(images, link)
        if not downloaded:
            logger.info(f"[아카라이브] 다운로드 성공한 이미지 없음: {title}")
            return

        # 배치 처리: MAX_EMBEDS_PER_MSG개씩 나눠서 전송
        for batch_start in range(0, len(downloaded), MAX_EMBEDS_PER_MSG):
            batch = downloaded[batch_start : batch_start + MAX_EMBEDS_PER_MSG]
            await self._send_image_batch(batch, title, link, batch_start)

    async def _download_and_process(
        self, images: list[dict[str, object]], link: str
    ) -> list[dict[str, object]]:
        """이미지 URL 목록을 다운로드→압축→중복제거하여 전송 가능한 버퍼 목록으로 만든다."""
        downloaded = []
        for img_info in images:
            try:
                buffer_data = await asyncio.to_thread(
                    self._download_single_image, img_info["url"], link
                )
                if not buffer_data:
                    continue

                # 내용 기반 중복 제거 — process_image 성공 후에 체크 (실패 시 영구 스킵 방지)
                discord_buffer, telegram_buffer, is_gif = await asyncio.to_thread(
                    self.image_handler.process_image,
                    buffer_data, img_info["filename"],
                )

                content_hash = hashlib.sha256(buffer_data).hexdigest()
                if self.image_handler.is_duplicate(content_hash):
                    logger.info(f"[아카라이브] 중복 이미지 스킵: {img_info['filename']}")
                    continue

                downloaded.append({
                    "discord_buffer": discord_buffer,
                    "telegram_buffer": telegram_buffer,
                    "filename": img_info["filename"],
                    "is_gif": is_gif,
                })
            except (OSError, ValueError) as e:
                logger.warning(f"[아카라이브] 이미지 처리 실패 ({img_info['filename']}): {e}")
                continue

            # CDN rate limit 방지
            await asyncio.sleep(IMAGE_DOWNLOAD_DELAY)
        return downloaded

    def _download_single_image(self, img_url: str, referer: str) -> bytes | None:
        """단일 이미지 URL을 메모리로 다운로드.

        namu.la CDN은 Cloudflare 보호가 없으므로 일반 requests 사용.
        """
        headers = {"Referer": referer}
        try:
            resp = requests.get(img_url, headers=headers, timeout=15)
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as e:
            logger.warning(f"이미지 다운로드 실패 ({img_url}): {e}")
            return None

    async def _send_image_batch(self, batch: list[dict[str, object]], title: str,
                                link: str, batch_index: int) -> object:
        """한 배치의 이미지를 Discord embed로 전송한다.

        - 첫 번째 embed: title + link 포함
        - 나머지 embed: 이미지만 (제목 없는 깔끔한 갤러리 형태)
        """
        # 웹 갤러리 적재용 스냅샷 — 전송 과정에서 버퍼 위치가 소비되므로 미리 확보
        gallery_snapshot = None
        if self.web_gallery_enabled:
            gallery_snapshot = [
                (item["discord_buffer"].getvalue(), item["filename"])
                for item in batch
            ]

        sent_ok = False
        for channel_id in self.channel_ids:
            channel = self.get_channel(int(channel_id))
            if not channel:
                logger.warning(f"[아카라이브] 채널 없음: {channel_id}")
                continue

            batch_sent = await self.media_pipeline.send_batch_to_channel(
                channel,
                batch,
                title=title,
                link=link,
                batch_index=batch_index,
            )
            sent_ok = sent_ok or batch_sent

        # 전송 성공한 배치를 공유 웹 갤러리에 적재
        # (fallback 경로는 _send_fallback 내부에서 개별 적재)
        if sent_ok and gallery_snapshot:
            for i, (data, filename) in enumerate(gallery_snapshot):
                self.media_pipeline.attach_to_web_gallery(
                    data,
                    filename,
                    batch_index + i,
                    title,
                    link,
                )

        # 배치 간 딜레이 (rate limit 방지)
        if batch_index > 0:
            await asyncio.sleep(INTER_IMAGE_DELAY)

    def _save_to_web_gallery(self, data: bytes, filename: str,
                             global_idx: int, title: str, link: str) -> object:
        """WEB_GALLERY=1 이면 전송된 이미지를 공유 웹 갤러리에 적재한다.

        첫 번째 이미지에는 원본 제목, 이후 이미지에는 '제목 - N' 형식으로 표시한다.
        """
        self.media_pipeline.attach_to_web_gallery(data, filename, global_idx, title, link)

    async def _send_fallback(self, channel: object, batch: list[dict[str, object]], title: str,
                              link: str, batch_index: int) -> object:
        """413(파일 크기 초과) 발생 시 한 장씩 개별 전송 (재압축 포함)."""
        for i, item in enumerate(batch):
            global_idx = batch_index + i
            item["discord_buffer"].seek(0)
            buffer = item["discord_buffer"]
            filename = item["filename"]

            try:
                embed_title = title if global_idx == 0 else None
                embed_link = link if global_idx == 0 else None
                embed = make_image_embed(
                    filename, title=embed_title, url=embed_link, color=ARCA_EMBED_COLOR,
                )

                # 전송 전에 스냅샷 확보 (send가 버퍼 위치를 소비함)
                data = buffer.getvalue()
                await channel.send(
                    file=discord.File(buffer, filename=filename),
                    embed=embed,
                )
                self._save_to_web_gallery(data, filename, global_idx, title, link)
            except discord.HTTPException as e2:
                if e2.status == 413:
                    # 재압축 시도
                    logger.warning(f"[아카라이브] 413 재압축 시도: {filename}")
                    recompressed = await asyncio.to_thread(
                        self.message_sender.recompress_for_discord,
                        channel, buffer, filename,
                    )
                    if recompressed:
                        embed = make_image_embed(filename, color=ARCA_EMBED_COLOR)
                        data = recompressed.getvalue()
                        await channel.send(
                            file=discord.File(recompressed, filename=filename),
                            embed=embed,
                        )
                        self._save_to_web_gallery(data, filename, global_idx, title, link)
                else:
                    logger.error(f"[아카라이브] fallback 전송 실패: {e2}")

            await asyncio.sleep(0.5)

    async def run_bot(self) -> object:
        async with self:
            await self.start(self.token)
