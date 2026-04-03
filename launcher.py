import subprocess
import os
import json
import time
import sys
import signal
import logging
import psutil
from collections import deque
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "Module", ".env"))
load_dotenv(env_path)

# galleries.json에서 갤러리 목록 로드
with open(os.path.join(os.path.dirname(__file__), "galleries.json"), "r", encoding="utf-8") as f:
    gallery_names = list(json.load(f).keys())

folder_queue = deque(gallery_names)
processes = {}  # {gallery_name: (process, start_time)}

MAX_PROCESSES = 5
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
            if cmdline and "run_gallery.py" in " ".join(cmdline) and gallery_name in " ".join(cmdline):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return False

def run_script(gallery_name):
    """run_gallery.py를 통해 갤러리 크롤러 실행"""
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

def manage_crawlers():
    """크롤링 프로세스를 관리"""
    while not shutdown_requested:
        logger.info(f"실행 준비된 갤러리: {list(folder_queue)[:MAX_PROCESSES]}")

        stop_running_processes()

        for _ in range(MAX_PROCESSES):
            if folder_queue and not shutdown_requested:
                gallery_name = folder_queue.popleft()
                if not is_already_running(gallery_name):
                    process = run_script(gallery_name)
                    processes[gallery_name] = (process, time.time())
                folder_queue.append(gallery_name)
                time.sleep(5)

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
