#!/usr/bin/env bash
# Poll origin/main; deploy only when it moved. Called by systemd timer.
set -uo pipefail
export GIT_TERMINAL_PROMPT=0
cd "$HOME/scribdku" || exit 0
git fetch -q origin main || exit 0
LOCAL=$(git rev-parse HEAD); REMOTE=$(git rev-parse origin/main)
if [ "$LOCAL" != "$REMOTE" ]; then
  echo "[$(date -Is)] $LOCAL -> $REMOTE" >> "$HOME/scribdku/deploy.log"
  SCRIBD_PORT=8001 bash deploy/deploy.sh >> "$HOME/scribdku/deploy.log" 2>&1
fi
