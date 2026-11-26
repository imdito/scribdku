#!/usr/bin/env bash
# Scribdku — matikan app lokal. Data job tetap tersimpan di volume Docker.
set -euo pipefail
cd "$(dirname "$0")"
docker compose down
echo "Scribdku berhenti."
