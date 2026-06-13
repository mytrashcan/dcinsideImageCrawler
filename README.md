# dcinsideImageCrawler - DCInside Image Downloader & Bot Sender

[![CI](https://github.com/mytrashcan/dcinsideImageCrawler/actions/workflows/ci.yml/badge.svg)](https://github.com/mytrashcan/dcinsideImageCrawler/actions/workflows/ci.yml)

**dcinsideImageCrawler** is a tool that scrapes images from posts on **DCInside** and automatically sends them to **Discord** and **Telegram** bots. The tool is designed to run on a cloud server like **Oracle Cloud** and **Amazon Web Services**, where it downloads images from DCInside posts and sends them to designated chat channels via bots.

## Features

- Scrapes images from DCInside and automatically posts to Discord and Telegram
- Works seamlessly on cloud environments like Oracle Cloud
- Supports multiple image formats (JPG, PNG, GIF) with automatic compression
  - Compression runs once and is reused for both platforms when their size limits match
  - Automatic re-compress & retry on Discord 413 (file too large) responses
- Fast HTML parsing via `lxml` + `SoupStrainer` (falls back to `html.parser` if lxml is unavailable)
- Config-driven gallery management via `galleries.json` - no code changes needed to add new galleries
- Duplicate image detection via SHA256 hashing
- Multi-process architecture for concurrent gallery crawling
- Test suite (pytest) and lint (ruff) enforced by GitHub Actions CI

## Installation

### Prerequisites

- Python 3.11+ (CI tests against 3.11 and 3.12)
- **Discord Bot Token** (for Discord bot integration)
- **Telegram Bot Token** (for Telegram bot integration)

### Steps to Install

1. Clone the repository:
   ```bash
   git clone https://github.com/mytrashcan/dcinsideImageCrawler.git
   ```

2. Navigate to the project directory:
   ```bash
   cd dcinsideImageCrawler
   ```

3. (Optional) Set up a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/MacOS
   ```

4. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

5. Create a `.env` file in the project root (or inside `Module/`):
   ```env
   DISCORD_TOKEN=your_discord_bot_token
   TELEGRAM_TOKEN=your_telegram_bot_token
   TELEGRAM_CHANNEL=your_telegram_chat_id
   # Optional: Discord upload limit in MB (default 10 — the free-tier limit since Sept 2024).
   # Raise to 50 (boost level 2) or 100 (boost level 3) if your server is boosted.
   DISCORD_MAX_SIZE_MB=10
   ```

## Usage

### Run all galleries
```bash
python launcher.py
```
The launcher manages multiple crawling processes using a circular queue, cycling through galleries defined in `galleries.json`.

### Run a single gallery
```bash
python run_gallery.py <gallery_name>
```
Example:
```bash
python run_gallery.py stariload
```

### Adding a new gallery

Edit `galleries.json` and add a new entry:
```json
{
    "my_gallery": {
        "base_url": "https://gall.dcinside.com/mgallery/board/lists/?id=my_gallery_id",
        "channel_ids": ["discord_channel_id_1", "discord_channel_id_2"]
    }
}
```
No code changes required - just restart the launcher.

## Running on a server (e.g. Oracle Cloud)

Run the launcher as a systemd service so it survives reboots and SSH disconnects:

```ini
# /etc/systemd/system/dccrawler.service
[Unit]
Description=DCInside Image Crawler
After=network-online.target

[Service]
WorkingDirectory=/home/ubuntu/dcinsideImageCrawler
ExecStart=/home/ubuntu/dcinsideImageCrawler/venv/bin/python launcher.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now dccrawler
```

Notes for small instances (1 GB RAM free tier):
- The launcher runs up to `MAX_PROCESSES` (default 5) Python processes at once; each loads discord.py and Pillow. Lower `MAX_PROCESSES` in `launcher.py` if memory is tight.
- Make sure `lxml` installed successfully (`pip show lxml`) — it noticeably reduces CPU time per crawl cycle.

## Project Structure

```
dcinsideImageCrawler/
├── launcher.py            # Process manager - runs multiple gallery crawlers
├── run_gallery.py         # Single gallery runner (replaces per-folder main.py)
├── galleries.json         # Gallery configuration (URLs, channel IDs)
├── requirements.txt       # Runtime dependencies
├── requirements-dev.txt   # Dev dependencies (pytest, ruff)
├── pyproject.toml         # pytest & ruff configuration
├── .github/workflows/ci.yml  # CI: lint + tests on Python 3.11/3.12
├── Module/
│   ├── config.py          # Environment variables, headers, logging setup
│   ├── crawler.py         # DCInside page scraping
│   ├── dcbot.py           # Discord bot client & crawling orchestration
│   ├── image_handler.py   # Image downloading, deduplication, compression
│   └── message_sender.py  # Discord & Telegram message delivery
└── tests/                 # pytest test suite
```

## Key Configuration

| Setting | Location | Default | Description |
|---------|----------|---------|-------------|
| `DISCORD_MAX_SIZE_MB` | `.env` | 10 MB | Discord upload limit (raise for boosted servers) |
| `MAX_PROCESSES` | `launcher.py` | 5 | Max concurrent gallery processes |
| `MAX_PROCESS_LIFETIME` | `launcher.py` | 3600s | Process restart interval |
| `REQUEST_TIMEOUT` | `Module/config.py` | 15s | HTTP request timeout |
| Crawl interval | `Module/dcbot.py` | 20-40s | Random delay between crawls |

## Development

```bash
pip install -r requirements-dev.txt

# Run tests
pytest

# Lint
ruff check .
```

CI (GitHub Actions) runs ruff and the test suite on every push to `main` and on pull requests.

## Discord Commands

| Command | Description |
|---------|-------------|
| `!쓰담쓰담` | Clear image hash cache (resets duplicate detection) |

## License
This project is licensed under the GPL License.
