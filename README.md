# dcinsideImageCrawler - DCInside & Arcalive Image Crawler & Bot Sender

[![CI](https://github.com/mytrashcan/dcinsideImageCrawler/actions/workflows/ci.yml/badge.svg)](https://github.com/mytrashcan/dcinsideImageCrawler/actions/workflows/ci.yml)

**dcinsideImageCrawler** is a tool that scrapes images from posts on **DCInside** and **Arcalive** (arca.live) and automatically sends them to **Discord** and **Telegram** bots. The tool is designed to run on a cloud server like **Oracle Cloud** and **Amazon Web Services**, where it downloads images from posts and sends them to designated chat channels via bots.

Two crawler types are supported:

- **DCInside** (`Module/crawler.py` + `Module/dcbot.py`) - scrapes `gall.dcinside.com`, downloads **one image per post** (top image only, as spam prevention), and delivers to Discord + Telegram.
- **Arcalive** (`Module/arca_crawler.py` + `Module/arca_bot.py`) - scrapes `arca.live` using `cloudscraper` (Cloudflare bypass), downloads **all images from a post**, and delivers to Discord only (multi-embed, up to 10 images per message).

Both crawlers share the same image pipeline (`ImageHandler` for compression/dedup), delivery layer (`MessageSender`), and the optional ephemeral web gallery (`web_app`).

## Features

- Scrapes images from DCInside and automatically posts to Discord and Telegram
- Arcalive (arca.live) crawler with Cloudflare bypass via `cloudscraper`
- All-image extraction per post (Arcalive) vs single-image extraction (DCInside, spam prevention)
- Discord multi-embed delivery for Arcalive (up to 10 images per message)
- Both crawlers share the same ephemeral web gallery
- Works seamlessly on cloud environments like Oracle Cloud
- Supports multiple image formats (JPG, PNG, GIF) with automatic compression
  - Compression runs once and is reused for both platforms when their size limits match
  - Automatic re-compress & retry on Discord 413 (file too large) responses
- Fast HTML parsing via `lxml` + `SoupStrainer` (falls back to `html.parser` if lxml is unavailable)
- Config-driven gallery management via `galleries.json` - no code changes needed to add new galleries
- Optional **ephemeral web gallery** - serves collected images in a near real-time, Pinterest-style masonry feed (titles link to the source post) that auto-expires (TTL/item-cap), no persistent storage
- Duplicate image detection via SHA256 hashing
- Multi-process architecture for concurrent gallery crawling
- Test suite (pytest) and lint (ruff) enforced by GitHub Actions CI

## Installation

### Prerequisites

- Python 3.11+ (CI tests against 3.11 and 3.12)
- **Discord Bot Token** (for Discord bot integration)
- **Telegram Bot Token** (for Telegram bot integration) - only needed for DCInside galleries; Arcalive galleries are Discord-only
- The Arcalive crawler requires `cloudscraper` (installed via `requirements.txt`)

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

### Run a single arcalive gallery
```bash
# Run a single arcalive gallery (same runner - dispatched by "type" in galleries.json)
python run_gallery.py arca_bluearchive

# With web gallery
WEB_GALLERY=1 python run_gallery.py arca_genshin
```

### Adding a new gallery

Edit `galleries.json` and add a new entry:
```json
{
    "my_dc_gallery": {
        "base_url": "https://gall.dcinside.com/mgallery/board/lists/?id=my_gallery_id",
        "channel_ids": ["discord_channel_id_1"]
    },
    "my_arca_gallery": {
        "base_url": "https://arca.live/b/myboard",
        "channel_ids": ["discord_channel_id_1"],
        "type": "arca"
    }
}
```
Set `"type": "arca"` for arca.live galleries. `run_gallery.py` (and therefore the launcher) auto-detects this and uses the Arcalive crawler instead of the DCInside one.

No code changes required - just restart the launcher.

## Web gallery (optional)

You can serve the collected images as a live, **ephemeral** web feed - a Pinterest-style masonry grid at `http://<host>:8000/` that updates roughly in real time (the page polls every 5 seconds and only adds new cards). Post titles link back to the original DCInside post.

**Nothing is stored permanently.** There is no database. Images are written to `web_static/images/` only as a temporary cache so the browser can load them, and each file is **deleted from disk** the moment it falls out of the feed - once it is older than the TTL (default 3 h) or pushed past the item cap. Direct image URLs also enforce that TTL, so an expired `/static/images/<id>` link returns 404 even if nobody has opened `/feed` recently. At most `WEB_FEED_MAX_ITEMS` images (default **120**) are kept; the 121st arrival deletes the oldest. Nothing accumulates.

> The bot's own Discord/Telegram delivery is fully in-memory (image bytes are sent and garbage-collected, never touching disk). The temporary files exist *only* to display the web gallery. A disk-backed cache is required because the launcher runs each gallery as a separate process, and the filesystem is the only shared store between them.

The feed is backed by the **filesystem**, so those multiple crawler processes can share one web page. Each crawler writes images (plus a small `.json` sidecar for title / post link / timestamp) into the shared `web_static/images/` directory, and a single web-server process lists that directory newest-first.

To cut transfer size, each crawler also generates a **card thumbnail** (max width `WEB_THUMB_WIDTH`, default 480 px) into `web_static/images/thumbs/`, and the feed serves that instead of the original. GIFs, animations, and images already smaller than the limit skip thumbnailing and fall back to the original. Thumbnails inherit the original's remaining-TTL cache policy and are deleted together with it.

### All galleries on one page (with the launcher)

Run the launcher with `WEB_GALLERY=1` so every crawler also writes to the shared gallery, and start one web server alongside it:

```bash
# terminal 1 - crawlers (all galleries in galleries.json), each feeding the gallery
WEB_GALLERY=1 python launcher.py

# terminal 2 - the web server
python run_web_server.py
```

Open `http://localhost:8000/` - images from every gallery appear in one feed. This works for both DCInside and Arcalive galleries - the gallery filter in the web UI shows `arca_*` gallery names for images coming from arcalive sources.

### A single gallery + web in one process

For quick local testing of one gallery, this runs the bot and an embedded web server together:

```bash
python run_web_gallery.py <gallery_name>
```

### Endpoints

| Path | Description |
|------|-------------|
| `/` | Masonry gallery page |
| `/feed?limit=N` | JSON feed of recent items (`limit` 1-200, default 60) |
| `/healthz` | Health check (`{ok, items, ttl}`) |

> The server binds to `0.0.0.0:8000` by default so it is reachable from outside the host. There is no authentication - put it behind a reverse proxy / firewall, or set `WEB_HOST=127.0.0.1` if you only want local access. Image responses are served with `Cache-Control: public, max-age=<remaining TTL>, immutable` - browsers/CDNs may cache each image, but only until its TTL expires, so expired gallery images never outlive the TTL in any cache while edge caching still offloads the origin.

### Terminal monitor

A live terminal dashboard shows the web feed and crawler processes at a glance:

```bash
python dashboard.py          # refreshes every 2s (Ctrl+C to quit)
python dashboard.py --once   # print a single frame
python dashboard.py -i 1     # custom refresh interval (seconds)
```

It reads `/healthz` + `/feed` from the web server (`WEB_PORT`, default 8000) and scans running `launcher.py` / `run_gallery.py` processes via `psutil` - no extra wiring needed. Panels: service status (web up/down, feed size, TTL), per-gallery crawler status (PID / memory / uptime), and the most recent images.

**Monitoring from another machine** (e.g. checking a Mac deployment from your Mac, or an OCI deployment remotely) works for the service-status and feed panels via the public API:

```bash
DASH_BASE_URL=https://dcselfie.win python dashboard.py
```

The crawler-process panel (PID/memory/uptime) can't be shown this way - `psutil` only sees processes on the machine it runs on - so it's replaced with an SSH hint. To see crawler status, run `./dcselfie.sh status` or `python dashboard.py` directly on the server (e.g. over SSH).

## Deploying the web gallery

Two common setups:

- **On your own machine (e.g. a Mac left running)** - run the crawlers + web server locally and expose the domain with a [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) (`cloudflared`). No port-forwarding, no public IP, automatic HTTPS. Keep the machine awake (`caffeinate -s`, or an app like Amphetamine). On macOS, `./dcselfie.sh install` registers the crawler / web server / tunnel as background **launchd** services (hidden, auto-restart, start at login); `./dcselfie.sh {start|stop|restart|status|logs|dash|uninstall}` manages them, and `./dcselfie.sh dash` opens the terminal monitor on demand.
- **On a cloud VM (e.g. Oracle Cloud free tier)** - run everything as `systemd` services and front it with a reverse proxy (Caddy gives automatic HTTPS). See the systemd example below; bind the web server to `127.0.0.1` and let the proxy serve the domain on 443. On Oracle Cloud remember to open ports 80/443 in **both** the VCN security list **and** the instance's local `iptables`.

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
├── run_gallery.py         # Single gallery runner (DCInside/Arcalive, dispatched by "type")
├── run_web_gallery.py     # Single gallery runner + embedded web gallery (FastAPI)
├── run_web_server.py      # Standalone web gallery server (for the multi-gallery launcher setup)
├── dashboard.py           # Live terminal monitor (web feed + crawler processes)
├── web_app.py             # FastAPI app & filesystem-backed ephemeral feed (TTL/prune)
├── web_static/            # Gallery page (index.html) + temporary images/ (gitignored)
├── galleries.json         # Gallery configuration (URLs, channel IDs)
├── requirements.txt       # Runtime dependencies
├── requirements-dev.txt   # Dev dependencies (pytest, ruff)
├── pyproject.toml         # pytest & ruff configuration
├── .github/workflows/ci.yml  # CI: lint + tests on Python 3.11/3.12
├── Module/
│   ├── config.py          # Environment variables, headers, logging setup
│   ├── crawler.py         # DCInside page scraping
│   ├── dcbot.py           # Discord bot client & crawling orchestration
│   ├── arca_crawler.py    # Arcalive page scraping
│   ├── arca_bot.py        # Arcalive Discord bot client
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
| Arca crawl interval | `Module/arca_bot.py` | 30-60s | Random delay between arcalive crawls |
| `WEB_GALLERY` | env | unset | Set to `1` so `launcher.py`/`run_gallery.py` crawlers also feed the web gallery |
| `WEB_HOST` | env | `0.0.0.0` | Web gallery bind address |
| `WEB_PORT` | env | 8000 | Web gallery port |
| `WEB_IMAGE_TTL_SECONDS` | env | 10800 (3h) | How long an image stays in the feed before it expires and is deleted |
| `WEB_FEED_MAX_ITEMS` | env | 120 | Max images kept in the feed; older ones are pruned and deleted |
| `WEB_STATIC_DIR` | env | `web_static` | Directory for the gallery page and temporary images |
| `WEB_THUMB_WIDTH` | env | 480 | Max card-thumbnail width in px (`0` disables thumbnailing) |

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
