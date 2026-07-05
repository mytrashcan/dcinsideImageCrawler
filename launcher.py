import json
import logging
import os
import signal
import subprocess
import sys
import time
from collections import deque

import psutil
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "Module", ".env"))
load_dotenv(env_path)

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

def signal_handler(sig, frame):
    global shutdown_requested
    logger.info("종료 신호 수신. 프로세스를 정리합니다...")
    shutdown_requested = True

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def is_already_running(gallery_name):
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

def run_script(gallery_name):
    """run_gallery.py를 통해 갤러리 크롤러 실행 (DCInside/Arcalive 모두)"""
    python_executable = sys.executable
    process = subprocess.Popen([python_executable, "run_gallery.py", gallery_name])
    logger.info(f"{gallery_name} 크롤러 실행됨 (PID: {process.pid})")
    return process

def stop_running_processes():
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

def _pick_from_queue(queue, max_count, source_label):
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

def manage_crawlers():
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

def main():
    """메인 실행 함수"""
    logger.info("크롤러 관리 프로세스를 시작합니다.")
    try:
        manage_crawlers()
    finally:
        stop_running_processes()
        logger.info("크롤러 관리 프로세스가 종료되었습니다.")

if __name__ == "__main__":
    main()
