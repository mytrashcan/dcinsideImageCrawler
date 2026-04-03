# dcinsideImageCrawler - DCInside Image Downloader & Bot Sender

**dcinsideImageCrawler** is a tool that scrapes images from posts on **DCInside** and automatically sends them to **Discord** and **Telegram** bots. The tool is designed to run on a cloud server like **Oracle Cloud** and **Amazon Web Services**, where it downloads images from DCInside posts and sends them to designated chat channels via bots.

## Features

- Scrapes images from DCInside and automatically posts to Discord and Telegram
- Works seamlessly on cloud environments like Oracle Cloud
- Supports multiple image formats (JPG, PNG, GIF) with automatic compression
- Config-driven gallery management via `galleries.json` - no code changes needed to add new galleries
- Duplicate image detection via SHA256 hashing
- Multi-process architecture for concurrent gallery crawling

## Installation

### Prerequisites

- Python 3.9+
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

5. Create a `.env` file inside the `Module/` directory:
   ```env
   DISCORD_TOKEN=your_discord_bot_token
   TELEGRAM_TOKEN=your_telegram_bot_token
   TELEGRAM_CHANNEL=your_telegram_chat_id
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

## Project Structure

```
dcinsideImageCrawler/
├── launcher.py          # Process manager - runs multiple gallery crawlers
├── run_gallery.py       # Single gallery runner (replaces per-folder main.py)
├── galleries.json       # Gallery configuration (URLs, channel IDs)
├── requirements.txt
├── Module/
│   ├── config.py        # Environment variables, headers, logging setup
│   ├── crawler.py       # DCInside page scraping
│   ├── dcbot.py         # Discord bot client & crawling orchestration
│   ├── image_handler.py # Image downloading, deduplication, compression
│   └── message_sender.py # Discord & Telegram message delivery
```

## Key Configuration

| Setting | Location | Default | Description |
|---------|----------|---------|-------------|
| `MAX_PROCESSES` | `launcher.py` | 5 | Max concurrent gallery processes |
| `MAX_PROCESS_LIFETIME` | `launcher.py` | 3600s | Process restart interval |
| `REQUEST_TIMEOUT` | `Module/config.py` | 15s | HTTP request timeout |
| Crawl interval | `Module/dcbot.py` | 20-40s | Random delay between crawls |

## Discord Commands

| Command | Description |
|---------|-------------|
| `!쓰담쓰담` | Clear image hash cache (resets duplicate detection) |

## License
This project is licensed under the GPL License.
