import multiprocessing
import subprocess
import os
import time
import psutil
import discord
import asyncio
from collections import deque  # 🔥 순환 실행을 위한 큐
from dotenv import load_dotenv

load_dotenv(os.path.join("Module", ".env"))
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

folders = [
    "projectmx", "bocchi_the_rock", "comic", "fubuki",
    "gov", "idolmaster", "kizunaai", "bang_dream",
    "purikone_redive", "stariload", "stellive", "wuthering",
    "zzz"
]

folder_queue = deque(folders)  # 🔥 순환 실행을 위한 큐
processes = {}  # 실행된 프로세스 저장 {폴더: (프로세스, 시작시간)}

MAX_PROCESSES = 6  # 동시 실행할 최대 프로세스 개수
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
    """각 폴더의 main.py 실행 (중복 실행 방지)"""
    if is_already_running(folder):
        print(f"⚠ {folder}/main.py가 이미 실행 중입니다. 새 프로세스를 실행하지 않습니다.")
        return

    process = subprocess.Popen(['python', f'{folder}/main.py'])
    processes[folder] = (process, time.time())  # 실행된 프로세스를 저장
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
    """크롤링 프로세스를 자동으로 관리 (순환 실행)"""
    while True:
        print(f"🚀 새로운 6개 실행: {list(folder_queue)[:MAX_PROCESSES]}")

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

class ControlBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)

    async def on_ready(self):
        print(f'✅ 디스코드 봇 {self.user} 실행 중!')

    async def on_message(self, message):
        if message.author == self.user:
            return

        if message.content == "쓰담쓰담":
            clear_image_folder("Image")

            image_path = "gaki.png"
            if not os.path.exists(image_path):
                await message.channel.send("❌ gaki.png 파일을 찾을 수 없어요!")
                return

            file = discord.File(image_path, filename="gaki.png")

            embed = discord.Embed(
                title="🧹 Image 폴더의 모든 파일을 싹~ 다 삭제해버릴게!♡",
                description="오빠의 흑역사는 이제 없어졌어! ㅋㅋㅋ",
                color=0xFF69B4
            )
            embed.set_image(url="attachment://gaki.png")

            await message.channel.send(embed=embed, file=file)

def clear_image_folder(folder):
    """상위 폴더의 Image 폴더 내부 파일 삭제 (폴더 자체는 유지)"""
    if not os.path.exists(folder):
        print(f"⚠ {folder} 폴더가 존재하지 않습니다.")
        return

    for file in os.listdir(folder):
        file_path = os.path.join(folder, file)
        try:
            os.remove(file_path)
            print(f"✅ 삭제 완료: {file_path}")
        except PermissionError:
            print(f"❌ 삭제 실패 (권한 문제): {file_path}")

if __name__ == "__main__":
    # 크롤러 관리 프로세스를 별도 실행 (자동 실행)
    crawler_manager = multiprocessing.Process(target=manage_crawlers)
    crawler_manager.start()

    # 디스코드 봇 실행
    bot = ControlBot()
    bot.run(DISCORD_TOKEN)

    # 디스코드 봇이 종료되면 크롤러 관리 프로세스도 종료
    crawler_manager.terminate()
    crawler_manager.join()
