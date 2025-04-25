import subprocess
import os
import time
import sys
import psutil
from collections import deque  # 🔥 순환 실행을 위한 큐
from dotenv import load_dotenv

env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "Module", ".env"))
load_dotenv(env_path)

folders = [
    "projectmx", "bang_dream", "idolmaster", "kizunaai", "comic",
    "bocchi_the_rock", "staraiload", "wuthering", "stellive", "zzz"
]

folder_queue = deque(folders)  # 🔥 순환 실행을 위한 큐
processes = {}  # 실행된 프로세스 저장 {폴더: (프로세스, 시작시간)}

MAX_PROCESSES = 5  # 동시 실행할 최대 프로세스 개수
MAX_PROCESS_LIFETIME = 3600  # 1시간마다 실행 교체

def is_already_running(folder):
    """해당 폴더의 main.py가 이미 실행 중인지 확인"""
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = proc.info["cmdline"]
            if cmdline and f"{folder}/main.py" in " ".join(cmdline):
                return True  # 이미 실행 중
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return False

def run_script(folder):
    """각 폴더의 main.py 실행"""
    python_executable = sys.executable  # 현재 Python 실행 파일 경로 (가상환경 사용 중일 경우 가상환경 Python)
    process = subprocess.Popen([python_executable, f"{folder}/main.py"])
    print(f"✅ {folder}/main.py 실행됨 (PID: {process.pid})")
    return process

def stop_running_processes():
    """현재 실행 중인 모든 프로세스를 종료"""
    global processes

    for folder, (process, start_time) in list(processes.items()):
        print(f"🔄 {folder}/main.py 실행 시간 초과. 종료 중...")
        process.terminate()
        process.wait()

    # 실행된 프로세스 딕셔너리 초기화
    processes.clear()

def manage_crawlers():
    """크롤링 프로세스를 동기적으로 관리"""
    global processes

    while True:
        print(f"🚀 실행 준비된 폴더: {list(folder_queue)[:MAX_PROCESSES]}")

        # 현재 실행 중인 프로세스 중단
        stop_running_processes()

        # 새로운 프로세스 실행
        for _ in range(MAX_PROCESSES):
            if folder_queue:
                folder = folder_queue.popleft()  # 🔥 큐에서 폴더 꺼내 실행
                if not is_already_running(folder):
                    process = run_script(folder)
                    processes[folder] = (process, time.time())
                folder_queue.append(folder)  # 🔥 순환 구조: 실행된 폴더를 다시 큐에 추가

                time.sleep(5)  # 실행 간격 조정

        # 실행된 프로세스가 MAX_PROCESS_LIFETIME 초 동안 실행되도록 대기
        elapsed_time = 0
        while elapsed_time < MAX_PROCESS_LIFETIME:
            time.sleep(1)
            elapsed_time += 1
            # 주기적으로 실행 상태를 확인하거나 로그를 출력 가능
        else:
            print("⏰ 실행 시간이 초과되었습니다. 프로세스를 재시작합니다.")

def main():
    """메인 실행 함수"""
    try:
        print("🚀 크롤러 관리 프로세스를 시작합니다.")
        manage_crawlers()
    except KeyboardInterrupt:
        print("🛑 크롤러 관리 프로세스를 중지합니다.")
        stop_running_processes()

if __name__ == "__main__":
    main()