import multiprocessing
import subprocess
import os
import time
import sys
import psutil
import asyncio
from collections import deque  # 🔥 순환 실행을 위한 큐
from dotenv import load_dotenv

from projectmx.main import DCBot  # DCBot을 main.py에서 가져옴

env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "Module", ".env"))
load_dotenv(env_path)

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

folders = [
    "projectmx", "bang_dream", "idolmaster", "kizunaai", "comic",
    "bocchi_the_rock","stariload", "wuthering", "stellive", "zzz"
]

folder_queue = deque(folders)  # 🔥 순환 실행을 위한 큐
processes = {}  # 실행된 프로세스 저장 {폴더: (프로세스, 시작시간)}

MAX_PROCESSES = 5  # 동시 실행할 최대 프로세스 개수
MAX_PROCESS_LIFETIME = 3600  # 1시간마다 실행 교체

def is_already_running(folder):
    """해당 폴더의 main.py가 이미 실행 중인지 확인"""
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info['cmdline']
            if cmdline and f"{folder}/main.py" in " ".join(cmdline):
                return True  # 이미 실행 중
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return False

def run_script(folder):
    """각 폴더의 main.py 실행"""
    python_executable = sys.executable  # 현재 Python 실행 파일 경로 (가상환경)
    process = subprocess.Popen([python_executable, f'{folder}/main.py'])
    print(f"✅ {folder}/main.py 실행됨 (PID: {process.pid})")

def stop_running_processes():
    """현재 실행 중인 6개 프로세스를 종료"""
    global processes

    for folder, (process, start_time) in list(processes.items()):
        print(f"🔄 {folder}/main.py 실행 시간 초과. 종료 중...")
        process.terminate()
        process.wait()

    # 실행된 프로세스 딕셔너리 초기화
    processes.clear()

def manage_crawlers():
    """크롤링 프로세스를 동기적으로 관리"""
    while True:
        print(f"🚀 새로운 5개 실행: {list(folder_queue)[:MAX_PROCESSES]}")

        # 현재 실행 중인 프로세스 종료
        stop_running_processes()

        # 새로운 6개 실행
        for _ in range(MAX_PROCESSES):
            if folder_queue:
                folder = folder_queue.popleft()  # 🔥 큐에서 폴더 꺼내 실행
                run_script(folder)
                folder_queue.append(folder)  # 🔥 실행한 폴더를 다시 큐에 추가 (순환 구조)
                time.sleep(5)  # 실행 간격 조정

        time.sleep(MAX_PROCESS_LIFETIME)  # 1시간마다 실행

def run_crawlers():
    """크롤러 관리 프로세스를 실행"""
    print("🚀 크롤러 관리 프로세스 시작")
    manage_crawlers()

async def run_discord_bot():
    """비동기로 디스코드 봇 실행"""
    print("🚀 디스코드 봇 실행 준비 중...")
    bot = DCBot()
    async with bot:
        await bot.start(DISCORD_TOKEN)

def main():
    # multiprocessing을 사용해 크롤러 관리 프로세스를 백그라운드에서 실행
    crawler_process = multiprocessing.Process(target=run_crawlers)
    crawler_process.start()

    # 디스코드 봇 실행
    asyncio.run(run_discord_bot())

    # 메인 프로세스 종료 시 크롤러 프로세스 종료
    crawler_process.terminate()
    crawler_process.join()

if __name__ == "__main__":
    main()