"""
아카라이브 전용 Discord 봇.

DCInsideImageCrawler의 dcbot.py와 차이점:
- 게시글 내 모든 이미지를 추출하여 전송 (DCInside: 최상단 1개)
- Telegram 전송 없음 (순수 Discord 전용)
- 멀티 임베드 메시지 (한 게시글 여러 이미지를 하나의 메시지로)
- 모든 이미지 처리는 인메모리(BytesIO)로 수행되며, WEB_GALLERY=1 일 때만 공유 웹 갤러리용으로 디스크에 기록됨
"""
import asyncio
import hashlib
import logging
import os
import random

import discord

from Module.arca_crawler import ArcaliveCrawler
from Module.image_handler import ImageHandler
from Module.message_sender import MessageSender

logger = logging.getLogger(__name__)

# Discord 메시지당 최대 임베드/파일 수
MAX_EMBEDS_PER_MSG = 10
# 이미지 간 전송 딜레이(초)
INTER_IMAGE_DELAY = 1.0
# 이미지 다운로드 간격(초) — CDN rate limit 방지
IMAGE_DOWNLOAD_DELAY = 0.5


class ArcaBot(discord.Client):
    """아카라이브 게시글을 크롤링하여 디스코드로 전송하는 봇.

    Telegram 전송 없이 Discord embed만 사용.
    게시글 내 모든 이미지를 추출하여 전송한다.
    """

    def __init__(self, token, base_url, channel_ids, intents, gallery_name=""):
        super().__init__(intents=intents)
        self.token = token
        self.base_url = base_url
        self.channel_ids = channel_ids
        self.web_gallery_name = gallery_name
        self.web_gallery_enabled = os.getenv("WEB_GALLERY") == "1"
        self.crawler = ArcaliveCrawler(base_url)
        self.image_handler = ImageHandler()
        # Telegram 없이 Discord 전용 MessageSender
        self.message_sender = MessageSender(
            telegram_bot_token=None,
            telegram_chat_id=None,
            image_handler=self.image_handler,
        )

    async def on_ready(self):
        logger.info(f"[아카라이브] Logged in as {self.user}")
        await self.start_crawling()

    async def start_crawling(self):
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

    async def process_post(self, post):
        """게시글 내 모든 이미지를 추출하여 디스코드로 전송한다."""
        images = await asyncio.to_thread(
            self.crawler.extract_all_images, post["link"]
        )
        if not images:
            logger.info(f"[아카라이브] 이미지 없음: {post['title']}")
            return

        title = post["title"]
        link = post["link"]
        logger.info(f"[아카라이브] {title}: {len(images)}개 이미지 추출됨")

        # 이미지 URL을 메모리 버퍼로 다운로드 + 압축 처리
        downloaded = []
        for img_info in images:
            try:
                buffer_data = await asyncio.to_thread(
                    self._download_single_image, img_info["url"], link
                )
                if not buffer_data:
                    continue

                # 내용 기반 중복 제거 (DCInside는 download_images()에서 수행하지만
                # 여기서는 process_image()를 직접 쓰므로 해시 체크가 없다)
                content_hash = hashlib.sha256(buffer_data).hexdigest()
                if self.image_handler._check_hash(content_hash):
                    logger.info(f"[아카라이브] 중복 이미지 스킵: {img_info['filename']}")
                    continue

                # ImageHandler.process_image()로 압축 + 포맷 검증
                discord_buffer, telegram_buffer, is_gif = await asyncio.to_thread(
                    self.image_handler.process_image,
                    buffer_data, img_info["filename"],
                )
                downloaded.append({
                    "discord_buffer": discord_buffer,
                    "telegram_buffer": telegram_buffer,
                    "filename": img_info["filename"],
                    "is_gif": is_gif,
                })
            except Exception as e:
                logger.warning(f"[아카라이브] 이미지 처리 실패 ({img_info['filename']}): {e}")
                continue

            # CDN rate limit 방지
            await asyncio.sleep(IMAGE_DOWNLOAD_DELAY)

        if not downloaded:
            logger.info(f"[아카라이브] 다운로드 성공한 이미지 없음: {title}")
            return

        # 배치 처리: MAX_EMBEDS_PER_MSG개씩 나눠서 전송
        for batch_start in range(0, len(downloaded), MAX_EMBEDS_PER_MSG):
            batch = downloaded[batch_start : batch_start + MAX_EMBEDS_PER_MSG]
            await self._send_image_batch(batch, title, link, batch_start)

    def _download_single_image(self, img_url: str, referer: str) -> bytes | None:
        """단일 이미지 URL을 메모리로 다운로드.
        
        ImageHandler.download_images()가 DCInside 전용이라
        직접 cloudscraper로 다운로드한다.
        """
        headers = {"Referer": referer}
        try:
            resp = self.crawler.scraper.get(img_url, headers=headers, timeout=15)
            resp.raise_for_status()
            return resp.content
        except Exception:
            # fallback: 일반 requests
            import requests as req
            try:
                resp = req.get(img_url, headers=headers, timeout=15)
                resp.raise_for_status()
                return resp.content
            except Exception as e2:
                logger.warning(f"이미지 다운로드 실패 ({img_url}): {e2}")
                return None

    async def _send_image_batch(self, batch: list[dict], title: str,
                                link: str, batch_index: int):
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

            files = []
            embeds = []

            for i, item in enumerate(batch):
                buffer = item["discord_buffer"]
                filename = item["filename"]
                global_idx = batch_index + i

                # Discord.File 생성
                discord_file = discord.File(buffer, filename=filename)
                files.append(discord_file)

                # Embed 생성
                # 첫 번째 이미지에만 title+link, 나머지는 제목 없음
                if global_idx == 0:
                    embed = discord.Embed(
                        title=title,
                        url=link,
                        color=0x00A3FF,  # 아카라이브 블루 계열
                    )
                    embed.set_footer(
                        text=f"아카라이브 · {len(batch)}개 이미지"
                    )
                else:
                    embed = discord.Embed(color=0x00A3FF)

                embed.set_image(url=f"attachment://{filename}")
                embeds.append(embed)

            try:
                await channel.send(files=files, embeds=embeds)
                sent_ok = True
                logger.info(
                    f"[아카라이브] 배치 전송 완료: {title} "
                    f"({batch_index + 1}~{batch_index + len(batch)}/{len(batch)})"
                )
            except discord.HTTPException as e:
                logger.error(f"[아카라이브] Discord 전송 실패: {e.status} {e.text}")
                # 413(파일 크기)이면 한 장씩 fallback 전송
                if e.status == 413:
                    await self._send_fallback(channel, batch, title, link, batch_index)

        # 전송 성공한 배치를 공유 웹 갤러리에 적재
        # (fallback 경로는 _send_fallback 내부에서 개별 적재)
        if sent_ok and gallery_snapshot:
            for i, (data, filename) in enumerate(gallery_snapshot):
                self._save_to_web_gallery(data, filename, batch_index + i, title, link)

        # 배치 간 딜레이 (rate limit 방지)
        if batch_index > 0:
            await asyncio.sleep(INTER_IMAGE_DELAY)

    def _save_to_web_gallery(self, data: bytes, filename: str,
                             global_idx: int, title: str, link: str):
        """WEB_GALLERY=1 이면 전송된 이미지를 공유 웹 갤러리에 적재한다.

        첫 번째 이미지에는 원본 제목, 이후 이미지에는 '제목 - N' 형식으로 표시한다.
        """
        if not self.web_gallery_enabled or not data:
            return
        try:
            from web_app import save_bytes_to_gallery
            save_bytes_to_gallery(
                data,
                filename,
                title=title if global_idx == 0 else f"{title} - {global_idx + 1}",
                link=link if global_idx == 0 else "",
                gallery=self.web_gallery_name,
            )
        except (OSError, ValueError) as e:
            logger.warning(f"[아카라이브] 웹 갤러리 적재 실패 ({filename}): {e}")

    async def _send_fallback(self, channel, batch: list[dict], title: str,
                              link: str, batch_index: int):
        """413(파일 크기 초과) 발생 시 한 장씩 개별 전송 (재압축 포함)."""
        for i, item in enumerate(batch):
            global_idx = batch_index + i
            item["discord_buffer"].seek(0)
            buffer = item["discord_buffer"]
            filename = item["filename"]

            try:
                embed_title = title if global_idx == 0 else None
                embed_link = link if global_idx == 0 else None
                embed = discord.Embed(
                    title=embed_title,
                    url=embed_link,
                    color=0x00A3FF,
                )
                embed.set_image(url=f"attachment://{filename}")

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
                        self.message_sender._recompress_for_discord,
                        channel, buffer, filename,
                    )
                    if recompressed:
                        embed = discord.Embed(color=0x00A3FF)
                        embed.set_image(url=f"attachment://{filename}")
                        data = recompressed.getvalue()
                        await channel.send(
                            file=discord.File(recompressed, filename=filename),
                            embed=embed,
                        )
                        self._save_to_web_gallery(data, filename, global_idx, title, link)
                else:
                    logger.error(f"[아카라이브] fallback 전송 실패: {e2}")

            await asyncio.sleep(0.5)

    async def run_bot(self):
        async with self:
            await self.start(self.token)
