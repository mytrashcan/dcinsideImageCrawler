#!/bin/bash
# Socat 리버스 SOCKS 터널: OCI → 맥북 arca.live 요청 릴레이
#
# 사용법:
#   ./arca-launcher.sh [OCI_SSH_HOST]
#
# 예: ./arca-launcher.sh ubuntu@140.xxx.xxx.xxx
#
# 이 스크립트는 맥북에서 실행하며:
# 1. 맥북 localhost:1080 에서 SSH -D SOCKS 서버 실행
# 2. SSH -R 역방향 터널로 OCI의 localhost:1080 → 맥북 localhost:1080 포워딩

source ~/dcinsideImageCrawler/venv/bin/activate

python3 -c "
import subprocess, signal, sys, os, time

def main():
    OCI_HOST = sys.argv[1] if len(sys.argv) > 1 else os.getenv('OCI_HOST', '').strip()
    SOCKS_PORT = os.getenv('ARCA_SOCKS_PORT', '1080')
    SSH_PORT = os.getenv('OCI_SSH_PORT', '22')

    if not OCI_HOST:
        print('❌ OCI SSH 호스트 지정 필요: ./arca-tunnel.sh ubuntu@xxx')
        print('   또는: export OCI_HOST=ubuntu@140.xxx.xxx.xxx')
        sys.exit(1)

    # SSH: -D: 로컬 SOCKS 서버, -R: 원격 → 로컬 포워딩
    # autossh 대체: 일반 ssh + 무한 재연결
    while True:
        print(f'🔁 SOCKS 터널 연결 중: -D {SOCKS_PORT} -R {SOCKS_PORT}:localhost:{SOCKS_PORT} → {OCI_HOST}')
        proc = subprocess.Popen([
            'ssh',
            '-o', 'ServerAliveInterval=30',
            '-o', 'ServerAliveCountMax=3',
            '-o', 'ExitOnForwardFailure=yes',
            '-o', 'StrictHostKeyChecking=no',
            '-N',
            '-D', SOCKS_PORT,
            '-R', f'{SOCKS_PORT}:localhost:{SOCKS_PORT}',
            '-p', SSH_PORT,
            OCI_HOST,
        ])
        print(f'✅ 터널 활성 (PID {proc.pid}). 끊기면 5초 후 자동 재연결...')
        proc.wait()
        print('⚠️ 연결 끊김. 5초 후 재시도...')
        time.sleep(5)

main()
" "$@"
