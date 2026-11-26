#!/bin/sh
# Start a virtual display when the downloader runs in headful mode.
set -eu

headless="$(printf '%s' "${SCRIBD_HEADLESS:-1}" | tr '[:upper:]' '[:lower:]')"
case "$headless" in
  0|false|no)
    export DISPLAY="${DISPLAY:-:99}"
    Xvfb "$DISPLAY" -screen 0 1920x2400x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
    sleep 1
    ;;
esac

exec "$@"
