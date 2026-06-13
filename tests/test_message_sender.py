import asyncio
import io
from types import SimpleNamespace

import discord
from PIL import Image

from Module.image_handler import ImageHandler
from Module.message_sender import MessageSender


def make_large_png_buffer(size=(800, 800)):
    """JPEG 변환/축소로 확실히 줄어드는 노이즈 PNG 버퍼 생성"""
    img = Image.effect_noise(size, 100).convert("RGB")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def make_413_exception():
    response = SimpleNamespace(status=413, reason="Payload Too Large")
    return discord.HTTPException(response, "Request entity too large")


class FakeChannel:
    """첫 send에서 지정된 예외를 던지고 이후 성공하는 채널 목"""

    def __init__(self, fail_times=1, exception=None, filesize_limit=None):
        self.sent_files = []
        self._fail_times = fail_times
        self._exception = exception
        if filesize_limit is not None:
            self.guild = SimpleNamespace(filesize_limit=filesize_limit)

    async def send(self, file=None, embed=None):
        if self._fail_times > 0 and self._exception is not None:
            self._fail_times -= 1
            raise self._exception
        self.sent_files.append(file.fp.read())


def make_sender(with_handler=True):
    handler = ImageHandler() if with_handler else None
    return MessageSender("123456:TEST-TOKEN", "0", image_handler=handler)


class TestDiscord413Fallback:
    def test_413_recompresses_and_retries(self):
        sender = make_sender()
        channel = FakeChannel(fail_times=1, exception=make_413_exception())
        buffer = make_large_png_buffer()
        original_size = len(buffer.getvalue())

        result = asyncio.run(sender.send_to_discord(channel, "title", buffer, "test.png"))

        assert result is True
        assert len(channel.sent_files) == 1
        assert len(channel.sent_files[0]) < original_size

    def test_413_uses_guild_filesize_limit_as_target(self):
        sender = make_sender()
        buffer = make_large_png_buffer()
        original_size = len(buffer.getvalue())
        limit = original_size // 4
        channel = FakeChannel(fail_times=1, exception=make_413_exception(), filesize_limit=limit)

        result = asyncio.run(sender.send_to_discord(channel, "title", buffer, "test.png"))

        assert result is True
        assert len(channel.sent_files[0]) <= limit

    def test_413_without_image_handler_fails_without_retry(self):
        sender = make_sender(with_handler=False)
        channel = FakeChannel(fail_times=99, exception=make_413_exception())
        buffer = make_large_png_buffer()

        result = asyncio.run(sender.send_to_discord(channel, "title", buffer, "test.png"))

        assert result is False
        assert channel.sent_files == []

    def test_non_413_http_error_is_not_retried(self):
        response = SimpleNamespace(status=403, reason="Forbidden")
        exc = discord.HTTPException(response, "Missing permissions")
        sender = make_sender()
        channel = FakeChannel(fail_times=99, exception=exc)
        buffer = make_large_png_buffer()

        result = asyncio.run(sender.send_to_discord(channel, "title", buffer, "test.png"))

        assert result is False
        assert channel.sent_files == []


class TestConfigDiscordMaxSize:
    def test_default_is_10mb(self, monkeypatch):
        import importlib

        from Module import config

        monkeypatch.delenv("DISCORD_MAX_SIZE_MB", raising=False)
        importlib.reload(config)
        assert config.DISCORD_MAX_SIZE == 10 * 1024 * 1024

    def test_env_override(self, monkeypatch):
        import importlib

        from Module import config

        monkeypatch.setenv("DISCORD_MAX_SIZE_MB", "50")
        importlib.reload(config)
        assert config.DISCORD_MAX_SIZE == 50 * 1024 * 1024

        # 다른 테스트에 영향 없도록 기본값으로 복원
        monkeypatch.delenv("DISCORD_MAX_SIZE_MB", raising=False)
        importlib.reload(config)
