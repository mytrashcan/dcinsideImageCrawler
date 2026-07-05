#!/bin/bash
# Xvfb 가상 디스플레이 시작 (OCI 헤드리스 서버용)
# nodriver headless=False 모드가 managed challenge를 풀기 위해 필요
export DISPLAY=:99
if ! pgrep -x Xvfb > /dev/null; then
    Xvfb :99 -screen 0 1920x1080x24 -ac +extension RANDR &
    sleep 2
    echo "Xvfb started on :99"
else
    echo "Xvfb already running on :99"
fi
