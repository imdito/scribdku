#!/usr/bin/env bash
# Scribdku — matikan server native yang jalan di background (kalau ada).
PORT="${SCRIBD_PORT:-8080}"
if command -v fuser >/dev/null 2>&1; then fuser -k "${PORT}/tcp" 2>/dev/null || true; fi
pkill -f "uvicorn app:app" 2>/dev/null || true
echo "Scribdku berhenti (kalau tadi jalan via terminal, Ctrl+C juga bisa)."
