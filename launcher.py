from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from collections import deque
from urllib import error, request

import psutil
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# 1) 프로젝트 루트 .env 우선 로드 (DISCORD_TOKEN 등 주요 환경변수)
load_dotenv()
# 2) Module/.env 로드 (ARCA_SOCKS_PROXY 등 Module 전용 변수, 기존값 덮어쓰기 허용)
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "Module", ".env"))
load_dotenv(env_path, override=True)

# galleries.json에서 갤러리 목록 로드 (arca 갤러리 포함)
with open(os.path.join(os.path.dirname(__file__), "galleries.json"), encoding="utf-8") as f:
    gallery_configs = json.load(f)
gallery_names = list(gallery_configs.keys())

# DC/Arca 분리
dc_galleries = deque(g for g in gallery_names if gallery_configs[g].get("type") != "arca")
arca_galleries = deque(g for g in gallery_names if gallery_configs[g].get("type") == "arca")

processes = {}  # {gallery_name: (process, start_time)}

MAX_DC = 5
MAX_ARCA = 5
MAX_PROCESS_LIFETIME = 3600

shutdown_requested = False


def _probe_ingest_auth(base_url: str) -> int | None:
    """빈 바디 + 토큰으로 ingest 인증만 검사한다. 415면 토큰 일치(빈 바디라 이미지 검증에서
    거절), 401이면 토큰 불일치. 연결 실패 등은 None."""
    req = request.Request(
        f"{base_url}/internal/images",
        data=b"",
        headers={
            "X-Ingest-Token": os.getenv("WEB_INGEST_TOKEN", ""),
            "Content-Type": "application/octet-stream",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=2) as response:
            return response.status
    except error.HTTPError as exc:
        return exc.code
    except (OSError, ValueError, error.URLError):
        return None


def wait_for_web_gallery() -> bool:
    """Wait until the in-memory web process can accept crawler uploads."""
    if os.getenv("WEB_GALLERY") != "1":
        return True

    base_url = os.getenv("WEB_GALLERY_URL", "http://127.0.0.1:8000").rstrip("/")
    try:
        timeout_seconds = max(1, int(os.getenv("WEB_READY_TIMEOUT_SECONDS", "60")))
    except ValueError:
        timeout_seconds = 60
        logger.warning("WEB_READY_TIMEOUT_SECONDS 값이 올바르지 않아 60초를 사용합니다.")

    health_url = f"{base_url}/healthz"
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            with request.urlopen(health_url, timeout=2) as response:
                health = json.load(response)
            if health.get("ingest_configured") is True:
                # healthz는 웹 쪽에 토큰이 "있다"는 것만 알려준다. 웹이 옛 .env로 기동 중이면
                # (토큰 회전 후 web 미재시작 등) 크롤러 업로드가 전부 401로 조용히 버려지므로,
                # 실제 토큰이 일치하는지까지 확인한 뒤에 크롤러를 시작한다.
                status = _probe_ingest_auth(base_url)
                if status in (200, 415):
                    logger.info("웹 갤러리 준비 완료 (ingest 토큰 인증 확인): %s", health_url)
                    return True
                if status == 401:
                    logger.error(
                        "WEB_INGEST_TOKEN 불일치: 웹 프로세스가 다른 토큰으로 기동 중입니다. "
                        "(.env 변경 후 dcselfie-web 미재시작이 흔한 원인 — web 재시작 필요)"
                    )
                else:
                    logger.warning("ingest 인증 프로브 응답 대기 중 (status=%s)", status)
            else:
                logger.warning("웹 갤러리 ingest가 아직 준비되지 않았습니다: %s", health_url)
        except (OSError, ValueError, error.URLError) as exc:
            logger.info("웹 갤러리 준비 대기 중 (%s): %s", health_url, exc)

        if time.monotonic() >= deadline:
            logger.error("웹 갤러리가 %s초 안에 준비되지 않았습니다: %s", timeout_seconds, health_url)
            return False
        time.sleep(1)

def signal_handler(sig: object, frame: object) -> object:
    global shutdown_requested
    logger.info("종료 신호 수신. 프로세스를 정리합니다...")
    shutdown_requested = True

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def is_already_running(gallery_name: object) -> object:
    """해당 갤러리가 이미 실행 중인지 확인"""
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = proc.info["cmdline"]
            if not cmdline:
                continue
            joined = " ".join(cmdline)
            if "run_gallery.py" in joined and gallery_name in joined:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return False

def run_script(gallery_name: object) -> object:
    """run_gallery.py를 통해 갤러리 크롤러 실행 (DCInside/Arcalive 모두)"""
    python_executable = sys.executable
    process = subprocess.Popen(
        [python_executable, "run_gallery.py", gallery_name],
    )
    logger.info(f"{gallery_name} 크롤러 실행됨 (PID: {process.pid})")
    return process

def stop_running_processes() -> object:
    """현재 실행 중인 모든 프로세스를 종료"""
    for gallery_name, (process, _) in list(processes.items()):
        logger.info(f"{gallery_name} 크롤러 종료 중...")
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    processes.clear()

def _pick_from_queue(queue: object, max_count: object, source_label: object) -> object:
    """큐에서 최대 max_count개의 갤러리를 선택 (실행 중이면 건너뜀)"""
    started = 0
    skipped = 0
    for _ in range(len(queue)):
        if started >= max_count:
            break
        if not queue:
            break
        gallery_name = queue.popleft()
        if not is_already_running(gallery_name):
            process = run_script(gallery_name)
            processes[gallery_name] = (process, time.time())
            started += 1
        else:
            skipped += 1
        queue.append(gallery_name)

    if started > 0:
        logger.info(f"{source_label}: {started}개 시작됨" + (f", {skipped}개 이미 실행 중" if skipped else ""))
    return started

def manage_crawlers() -> object:
    """크롤링 프로세스를 관리 (DC 최대 {MAX_DC}개 + Arca 최대 {MAX_ARCA}개)"""
    while not shutdown_requested:
        logger.info(f"DC 갤러리: {len(dc_galleries)}개, Arca 갤러리: {len(arca_galleries)}개")

        stop_running_processes()

        dc_count = _pick_from_queue(dc_galleries, MAX_DC, "DC")
        arca_count = _pick_from_queue(arca_galleries, MAX_ARCA, "Arca")

        total = dc_count + arca_count
        logger.info(f"총 {total}개 크롤러 실행 중 (DC: {dc_count}, Arca: {arca_count})")

        elapsed_time = 0
        while elapsed_time < MAX_PROCESS_LIFETIME and not shutdown_requested:
            time.sleep(1)
            elapsed_time += 1

        if not shutdown_requested:
            logger.info("실행 시간 초과. 프로세스를 재시작합니다.")

def main() -> object:
    """메인 실행 함수"""
    logger.info("크롤러 관리 프로세스를 시작합니다.")
    if not wait_for_web_gallery():
        raise SystemExit("웹 갤러리 준비 실패")
    try:
        manage_crawlers()
    finally:
        stop_running_processes()
        logger.info("크롤러 관리 프로세스가 종료되었습니다.")

if __name__ == "__main__":
    main()
