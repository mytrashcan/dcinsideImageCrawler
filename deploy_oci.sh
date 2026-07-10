#!/usr/bin/env bash
# Safe OCI deployment for the crawler and in-memory web gallery.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "Tracked files are modified; refusing to deploy." >&2
  exit 1
fi

exec 9>/tmp/dcselfie-deploy.lock
flock -n 9 || { echo "Another deployment is running." >&2; exit 1; }

git fetch origin main
git pull --ff-only origin main

venv/bin/pip install -r requirements.txt
umask 077
venv/bin/python scripts/ensure_web_ingest_token.py .env
venv/bin/python -m compileall -q Module scripts web_app.py run_gallery.py run_web_server.py

sudo install -m 0644 dcselfie-launcher.service dcselfie-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart dcselfie-web
web_ingest_ready=0
for _ in $(seq 1 20); do
  if venv/bin/python scripts/probe_web_ingest.py .env; then
    web_ingest_ready=1
    break
  fi
  sleep 1
done
if [ "$web_ingest_ready" -ne 1 ]; then
  echo "Web ingest authentication did not become ready." >&2
  exit 1
fi

sudo systemctl restart dcselfie-launcher
launcher_ready=0
for _ in $(seq 1 20); do
  launcher_pid="$(systemctl show dcselfie-launcher --property MainPID --value)"
  if systemctl is-active --quiet dcselfie-web dcselfie-launcher \
    && [[ "$launcher_pid" =~ ^[1-9][0-9]*$ ]] \
    && pgrep -P "$launcher_pid" -f 'run_gallery.py' >/dev/null; then
    launcher_ready=1
    break
  fi
  sleep 1
done
if [ "$launcher_ready" -ne 1 ]; then
  echo "Crawler launcher did not start gallery workers." >&2
  exit 1
fi

echo "Deployed $(git rev-parse --short HEAD)"
curl -fsS http://127.0.0.1:8000/healthz
