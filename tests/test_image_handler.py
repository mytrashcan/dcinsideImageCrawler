import io

from PIL import Image

from Module.image_handler import (
    MAX_HASH_CACHE_SIZE,
    ImageHandler,
)


def make_png_bytes(size=(64, 64), color=(255, 0, 0)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def make_gif_bytes(frames=3, size=(64, 64)):
    images = [Image.new("RGB", size, (i * 40, 0, 0)) for i in range(frames)]
    buffer = io.BytesIO()
    images[0].save(buffer, format="GIF", save_all=True, append_images=images[1:], duration=100, loop=0)
    return buffer.getvalue()


class TestHashCache:
    def test_first_time_returns_false_then_true(self):
        handler = ImageHandler()
        assert handler._check_hash("abc") is False
        assert handler._check_hash("abc") is True

    def test_cache_is_bounded(self):
        handler = ImageHandler()
        for i in range(MAX_HASH_CACHE_SIZE + 10):
            handler._check_hash(str(i))
        assert len(handler._seen_hashes) <= MAX_HASH_CACHE_SIZE

    def test_clear(self):
        handler = ImageHandler()
        handler._check_hash("abc")
        handler.clear_seen_hashes()
        assert handler._check_hash("abc") is False


class TestProcessImage:
    def test_small_image_passes_through_unchanged(self):
        handler = ImageHandler()
        data = make_png_bytes()

        discord_buffer, telegram_buffer, is_gif = handler.process_image(data, "test.png")

        assert discord_buffer.read() == data
        assert telegram_buffer.read() == data
        assert is_gif is False

    def test_gif_detected_by_extension(self):
        handler = ImageHandler()
        data = make_gif_bytes()
        _, _, is_gif = handler.process_image(data, "test.gif")
        assert is_gif is True

    def test_gif_detected_by_magic_bytes(self):
        handler = ImageHandler()
        data = make_gif_bytes()
        _, _, is_gif = handler.process_image(data, "no_extension")
        assert is_gif is True

    def test_buffers_are_independent(self):
        handler = ImageHandler()
        data = make_png_bytes()
        discord_buffer, telegram_buffer, _ = handler.process_image(data, "test.png")

        discord_buffer.read()
        assert telegram_buffer.tell() == 0

    def test_telegram_reuses_discord_compression(self, monkeypatch):
        """두 제한이 같으면 압축은 한 번만 수행하고 결과를 재사용해야 함"""
        handler = ImageHandler()
        data = make_png_bytes(size=(800, 800))
        target = len(data) // 2
        monkeypatch.setattr("Module.image_handler.DISCORD_MAX_SIZE", target)
        monkeypatch.setattr("Module.image_handler.TELEGRAM_MAX_SIZE", target)

        calls = []
        original_compress = handler.compress_image

        def counting_compress(*args, **kwargs):
            calls.append(args)
            return original_compress(*args, **kwargs)

        monkeypatch.setattr(handler, "compress_image", counting_compress)

        discord_buffer, telegram_buffer, _ = handler.process_image(data, "test.png")

        assert len(calls) == 1
        assert discord_buffer.getvalue() == telegram_buffer.getvalue()
        # 재사용하더라도 버퍼는 서로 독립적이어야 함
        discord_buffer.read()
        assert telegram_buffer.tell() == 0

    def test_telegram_compresses_separately_when_discord_result_too_large(self, monkeypatch):
        """Discord 압축 결과가 Telegram 제한을 넘으면(부스트 서버) Telegram은 따로 압축해야 함"""
        handler = ImageHandler()
        data = b"x" * 1000
        monkeypatch.setattr("Module.image_handler.DISCORD_MAX_SIZE", 800)
        monkeypatch.setattr("Module.image_handler.TELEGRAM_MAX_SIZE", 200)

        calls = []

        def fake_compress(data_arg, target_arg, filename):
            calls.append(target_arg)
            result = b"y" * (target_arg - 10)
            return io.BytesIO(result), len(result)

        monkeypatch.setattr(handler, "compress_image", fake_compress)

        discord_buffer, telegram_buffer, _ = handler.process_image(data, "test.png")

        assert calls == [800, 200]
        assert len(discord_buffer.getvalue()) == 790
        assert len(telegram_buffer.getvalue()) == 190


class TestCompress:
    def test_compress_image_reaches_target(self):
        handler = ImageHandler()
        data = make_png_bytes(size=(800, 800))
        target = len(data) // 2

        output, size = handler.compress_image(data, target, "test.png")

        assert size <= target
        assert output.read(2) == b"\xff\xd8"  # JPEG 매직 바이트

    def test_compress_gif_reaches_target(self):
        handler = ImageHandler()
        data = make_gif_bytes(frames=12, size=(400, 400))
        target = int(len(data) * 0.8)

        output, size = handler.compress_gif(data, target, "test.gif")

        assert size <= target
        assert output.read(6) in (b"GIF87a", b"GIF89a")

    def test_compress_image_invalid_data_returns_original(self):
        handler = ImageHandler()
        data = b"not an image"
        output, size = handler.compress_image(data, 10, "broken.png")
        assert output.read() == data
        assert size == len(data)
