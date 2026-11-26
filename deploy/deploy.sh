#!/usr/bin/env bash
# Deploy latest main to this boxd machine. Run from anywhere; logs to deploy.log.
set -euo pipefail
cd "$HOME/scribdku"
export SCRIBD_PORT="${SCRIBD_PORT:-8001}"
git fetch origin main
git reset --hard origin/main
git submodule update --init --recursive
docker compose up -d --build
for i in $(seq 1 30); do
  if curl -sf "http://localhost:${SCRIBD_PORT}/api/health" >/dev/null; then echo "healthy on :${SCRIBD_PORT}"; exit 0; fi
  sleep 4
done
echo "healthcheck FAILED"; docker compose ps; exit 1
