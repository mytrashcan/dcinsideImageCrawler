"""터미널 모니터 대시보드.

웹 갤러리(/healthz, /feed)와 크롤러 프로세스(psutil) 상태를 한 화면에서 라이브로 본다.

  python dashboard.py            # 2초마다 갱신 (Ctrl+C 종료)
  python dashboard.py --once     # 한 프레임만 출력 (스크립트/점검용)
  python dashboard.py -i 1       # 갱신 주기 1초

연결 대상 포트는 WEB_PORT(기본 8000), 호스트는 DASH_HOST(기본 127.0.0.1).
"""
import argparse
import json
import os
import time
import urllib.request
from datetime import datetime

import psutil
from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

DASH_HOST = os.getenv("DASH_HOST", "127.0.0.1")
PORT = int(os.getenv("WEB_PORT", "8000"))
BASE = f"http://{DASH_HOST}:{PORT}"

BANNER = r"""
 ___  ___ ___ __  __ ___    ___   _   _    _    ___ _____   __
|   \/ __|_ _|  \/  / __|  / __| /_\ | |  | |  | __| _ \ \ / /
| |) \__ \| || |\/| \__ \ | (_ |/ _ \| |__| |__| _||   /\ V /
|___/|___/___|_|  |_|___/  \___/_/ \_\____|____|___|_|_\ |_|
        e p h e m e r a l   i m a g e   f e e d   m o n i t o r
"""

ROSE = "#e60023"


def _galleries():
    try:
        with open("galleries.json", encoding="utf-8") as f:
            return list(json.load(f).keys())
    except OSError:
        return []


def _fetch(path, timeout=2.0):
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return None


def _scan_procs():
    """run_gallery.py / run_web_gallery.py / launcher.py / run_web_server.py 프로세스 수집."""
    crawlers, services = {}, {}
    for p in psutil.process_iter(["pid", "cmdline", "create_time"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if "run_gallery.py" in cmd:
            for g in _galleries():
                if f" {g}" in cmd or cmd.endswith(g):
                    crawlers[g] = p
        elif "launcher.py" in cmd:
            services["launcher"] = p
        elif "run_web_server.py" in cmd or "run_web_gallery.py" in cmd:
            services["web"] = p
    return crawlers, services


def _uptime(p):
    try:
        secs = int(time.time() - p.info["create_time"])
    except (KeyError, psutil.NoSuchProcess):
        return "-"
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


def _rss_mb(p):
    try:
        return p.memory_info().rss / 1024 / 1024
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0.0


def _time_ago(epoch):
    diff = int(time.time() - epoch)
    if diff < 60:
        return "방금"
    if diff < 3600:
        return f"{diff // 60}분 전"
    if diff < 86400:
        return f"{diff // 3600}시간 전"
    return f"{diff // 86400}일 전"


def _services_panel(health, services):
    t = Table.grid(padding=(0, 2))
    t.add_column(justify="right", style="bold")
    t.add_column()

    if health and health.get("ok"):
        web = Text("● UP", style="bold green")
        items = f"[bold]{health.get('items', 0)}[/] / {os.getenv('WEB_FEED_MAX_ITEMS', '120')}"
        ttl_h = health.get("ttl", 0) / 3600
        ttl = f"{ttl_h:.1f}h"
    else:
        web = Text("● DOWN", style="bold red")
        items, ttl = "-", "-"

    launcher = Text("● 실행중", style="green") if "launcher" in services else Text("○ 꺼짐", style="dim")
    websvc = Text("● 실행중", style="green") if "web" in services else Text("○ 꺼짐", style="dim")

    if health and health.get("maintenance"):
        maint = Text("🛠 점검중 (down)", style="bold yellow")
    elif health and health.get("ok"):
        maint = Text("정상 운영", style="green")
    else:
        maint = Text("-", style="dim")

    t.add_row("웹 서버", web)
    t.add_row("주소", f"[link={BASE}]{BASE}[/]")
    t.add_row("피드 이미지", items)
    t.add_row("TTL", ttl)
    t.add_row("운영 상태", maint)
    t.add_row("launcher", launcher)
    t.add_row("web process", websvc)
    return Panel(t, title="[bold]서비스 상태", border_style=ROSE, width=42)


def _crawlers_panel(crawlers):
    galleries = _galleries()
    table = Table(expand=True, border_style="grey39")
    table.add_column("갤러리", style="bold")
    table.add_column("상태", justify="center")
    table.add_column("PID", justify="right", style="dim")
    table.add_column("메모리", justify="right")
    table.add_column("업타임", justify="right", style="cyan")

    running = 0
    for g in galleries:
        p = crawlers.get(g)
        if p:
            running += 1
            table.add_row(g, Text("● 크롤중", style="green"), str(p.info["pid"]),
                          f"{_rss_mb(p):.0f}MB", _uptime(p))
        else:
            table.add_row(g, Text("○ 대기", style="dim"), "-", "-", "-")

    title = f"[bold]크롤러[/]  ([green]{running}[/]/{len(galleries)} 실행중)"
    return Panel(table, title=title, border_style=ROSE)


def _recent_panel(feed):
    table = Table(expand=True, border_style="grey39")
    table.add_column("최근 자짤", style="bold", ratio=3, no_wrap=True)
    table.add_column("시간", justify="right", ratio=1, style="grey62")

    if not feed:
        table.add_row(Text("아직 수집된 이미지가 없습니다", style="dim"), "")
    else:
        for it in feed[:12]:
            label = it.get("title") or "자짤"
            table.add_row(label, _time_ago(it.get("created_at", time.time())))
    return Panel(table, title="[bold]실시간 피드", border_style=ROSE)


def render():
    health = _fetch("/healthz")
    feed = _fetch("/feed?limit=12") or []
    crawlers, services = _scan_procs()

    banner = Align.center(Text(BANNER, style=f"bold {ROSE}"))
    clock = Align.center(Text(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), style="grey62"))

    top = Table.grid(expand=True)
    top.add_column(width=42)
    top.add_column(ratio=1)
    top.add_row(_services_panel(health, services), _recent_panel(feed))

    return Group(banner, clock, Text(), top, Text(), _crawlers_panel(crawlers))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="한 프레임만 출력")
    ap.add_argument("-i", "--interval", type=float, default=2.0, help="갱신 주기(초)")
    args = ap.parse_args()

    console = Console()
    if args.once:
        console.print(render())
        return

    try:
        with Live(render(), console=console, refresh_per_second=4, screen=True) as live:
            while True:
                time.sleep(args.interval)
                live.update(render())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
