#!/usr/bin/env bash
# Scribdku — jalankan app lokal (Linux/macOS). Butuh Docker + Docker Compose.
set -euo pipefail
cd "$(dirname "$0")"
command -v docker >/dev/null 2>&1 || { echo "Docker belum terpasang. Pasang Docker dulu, lalu jalankan lagi."; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Docker Compose tidak ditemukan."; exit 1; }
PORT="${SCRIBD_PORT:-8080}"
echo "Menyiapkan Scribdku (build + start)…"
docker compose up -d --build
echo "Menunggu server siap di http://localhost:${PORT} …"
for i in $(seq 1 60); do
  if curl -s -m 3 "http://localhost:${PORT}/api/health" >/dev/null 2>&1; then
    echo "Scribdku jalan: http://localhost:${PORT}"
    (xdg-open "http://localhost:${PORT}" >/dev/null 2>&1 &) || true
    exit 0
  fi
  sleep 2
done
echo "Server belum siap. Cek log: docker compose logs -f"
exit 1
