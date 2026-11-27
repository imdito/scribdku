#!/usr/bin/env bash
# Scribdku — mode JENDELA SENDIRI (Linux/macOS): server lokal + jendela app
# tanpa address bar/tab browser (Chrome/Chromium app mode).
# Menutup jendela app akan mematikan servernya juga.
set -euo pipefail
cd "$(dirname "$0")"

command -v python3 >/dev/null 2>&1 || { echo "Python 3 belum ada. Pasang Python 3.10+ dulu."; exit 1; }

BROWSER=""
for candidate in google-chrome google-chrome-stable chromium chromium-browser; do
  if command -v "$candidate" >/dev/null 2>&1; then BROWSER="$candidate"; break; fi
done
[ -n "$BROWSER" ] || { echo "Chrome/Chromium tidak ditemukan — mode jendela butuh salah satunya."; exit 1; }

if [ ! -x .venv/bin/python ]; then
  echo "Menyiapkan environment Python (.venv)…"
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -q --disable-pip-version-check -r server/requirements.txt

export SCRIBD_DATA_DIR="${SCRIBD_DATA_DIR:-$PWD/data}"
PORT="${SCRIBD_PORT:-8080}"
URL="http://localhost:${PORT}"
mkdir -p "$SCRIBD_DATA_DIR"

# Kalau server sudah jalan (mis. dari run.sh), langsung pakai.
SERVER_PID=""
if ! curl -s -m 2 "$URL/api/health" >/dev/null 2>&1; then
  .venv/bin/python -m uvicorn app:app --app-dir server --host 127.0.0.1 --port "$PORT" \
    >> "$SCRIBD_DATA_DIR/server.log" 2>&1 &
  SERVER_PID=$!
fi
cleanup() { [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null || true; }
trap cleanup EXIT

for i in $(seq 1 60); do
  curl -s -m 3 "$URL/api/health" >/dev/null 2>&1 && break
  sleep 1
done

PROFILE="$SCRIBD_DATA_DIR/browser-profile"
"$BROWSER" --app="$URL" --user-data-dir="$PROFILE" \
  --window-size=1280,860 --no-first-run --no-default-browser-check >/dev/null 2>&1

# Jendela ditutup -> keluar, server ikut mati lewat trap.
