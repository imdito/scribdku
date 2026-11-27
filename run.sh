#!/usr/bin/env bash
# Scribdku — jalan langsung tanpa Docker (Linux/macOS).
# Butuh: Python 3.10+ dan Chrome/Chromium terpasang.
set -euo pipefail
cd "$(dirname "$0")"

command -v python3 >/dev/null 2>&1 || { echo "Python 3 belum ada. Pasang Python 3.10+ dulu."; exit 1; }
if ! command -v google-chrome google-chrome-stable chromium chromium-browser >/dev/null 2>&1; then
  echo "Catatan: Chrome/Chromium tidak ketemu di PATH — Selenium akan mencoba mengunduh Chrome sendiri."
fi

if [ ! -x .venv/bin/python ]; then
  echo "Menyiapkan environment Python (.venv)…"
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -q --disable-pip-version-check -r server/requirements.txt

export SCRIBD_DATA_DIR="${SCRIBD_DATA_DIR:-$PWD/data}"
PORT="${SCRIBD_PORT:-8080}"
URL="http://localhost:${PORT}"

( for i in $(seq 1 60); do
    if curl -s -m 3 "$URL/api/health" >/dev/null 2>&1; then
      (xdg-open "$URL" >/dev/null 2>&1 &) || true
      break
    fi
    sleep 2
  done ) &

echo "Scribdku jalan di $URL — tekan Ctrl+C untuk berhenti."
exec .venv/bin/python -m uvicorn app:app --app-dir server --host 127.0.0.1 --port "$PORT"
