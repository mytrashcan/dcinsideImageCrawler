"""Smoke tests for DCBot instantiation and basic process_post logic.

DCBot inherits discord.Client, so we monkeypatch the crawler and image_handler
to avoid real network/Discord dependencies.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from Module.dcbot import DCBot


@pytest.fixture
def mock_dependencies():
    """Return (mock_crawler_class, mock_image_handler, mock_message_sender) patches."""
    crawler_mock = MagicMock()
    image_handler_mock = MagicMock()

    with (
        patch("Module.dcbot.DCInsideCrawler", return_value=crawler_mock),
        patch("Module.dcbot.ImageHandler", return_value=image_handler_mock),
    ):
        yield crawler_mock, image_handler_mock


@pytest.fixture
def bot(mock_dependencies):
    """Build a DCBot whose crawler / image_handler / message_sender are all mocks."""
    import discord

    intents = discord.Intents.default()
    b = DCBot(
        token="fake-token",
        base_url="https://gall.dcinside.com/mgallery/board/lists/?id=test",
        channel_ids=["123456789"],
        telegram_token="fake-telegram-token",
        telegram_chat_id="fake-chat-id",
        intents=intents,
    )
    # Replace get_channel so send_to_discord doesn't need real channel
    b.get_channel = MagicMock(return_value=MagicMock())
    # Make async methods on message_sender actually awaitable
    b.message_sender.send_to_discord = AsyncMock()
    b.message_sender.send_to_telegram = AsyncMock()
    return b


@pytest.mark.asyncio
async def test_dcbot_instantiation(bot):
    """Verify the bot can be instantiated without errors."""
    assert bot.token == "fake-token"
    assert len(bot.channel_ids) == 1
    assert bot.crawler is not None
    assert bot.image_handler is not None
    assert bot.message_sender is not None


@pytest.mark.asyncio
async def test_setup_hook_starts_only_one_crawler_task(bot):
    """The reconnect-safe crawler task is created once."""
    bot._run_crawler = AsyncMock()

    await bot.setup_hook()
    task = bot._crawler_task
    await bot.setup_hook()
    await task

    assert bot._crawler_task is task
    bot._run_crawler.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_ready_does_not_start_another_crawler_loop(bot):
    """Discord may emit on_ready repeatedly after reconnects."""
    bot.start_crawling = AsyncMock()

    await bot.on_ready()
    await bot.on_ready()

    bot.start_crawling.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_post_with_images(mock_dependencies, bot):
    """process_post downloads images and calls send_to_discord + send_to_telegram."""
    _, image_handler_mock = mock_dependencies
    image_handler_mock.download_images.return_value = [
        (MagicMock(), MagicMock(), "photo.png", False),
    ]

    post = {"title": "Test Post", "link": "https://example.com/post/1", "has_image": True}
    await bot.process_post(post)

    image_handler_mock.download_images.assert_called_once_with(post["link"])
    bot.message_sender.send_to_discord.assert_called()
    bot.message_sender.send_to_telegram.assert_called_once()


@pytest.mark.asyncio
async def test_process_post_no_images(mock_dependencies, bot):
    """process_post returns early when no images are found."""
    _, image_handler_mock = mock_dependencies
    image_handler_mock.download_images.return_value = []

    post = {"title": "No Img Post", "link": "https://example.com/post/2"}
    await bot.process_post(post)

    image_handler_mock.download_images.assert_called_once()
    bot.message_sender.send_to_discord.assert_not_called()
    bot.message_sender.send_to_telegram.assert_not_called()


@pytest.mark.asyncio
async def test_start_crawling_retries_on_error(mock_dependencies, bot):
    """start_crawling does not crash on transient errors; it logs and continues.

    The while True loop never exits, so we use asyncio.wait_for with a short
    timeout to verify it runs through at least one error cycle.
    """
    crawler_mock, _ = mock_dependencies
    crawler_mock.get_latest_post.side_effect = Exception("Transient network error")

    with patch("asyncio.sleep", AsyncMock()):
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(bot.start_crawling(), timeout=0.1)

    assert crawler_mock.get_latest_post.call_count >= 1


@pytest.mark.asyncio
async def test_start_crawling_processes_post_with_image(mock_dependencies, bot):
    """start_crawling calls process_post when get_latest_post returns an image post."""
    crawler_mock, image_handler_mock = mock_dependencies

    post = {"title": "Gallery Post", "link": "https://example.com/post/3", "has_image": True}
    crawler_mock.get_latest_post.side_effect = [post, post, post]

    image_handler_mock.download_images.return_value = [
        (MagicMock(), MagicMock(), "img.png", False),
    ]

    with patch("asyncio.sleep", AsyncMock()):
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(bot.start_crawling(), timeout=0.1)

    image_handler_mock.download_images.assert_called_with(post["link"])
    bot.message_sender.send_to_discord.assert_called()
