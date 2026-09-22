#!/usr/bin/env bash
# Simple loop if you do NOT use systemd (screen/tmux/nohup).
# Prefer: sudo systemctl start capiffy-mirror
set -euo pipefail
cd "$(dirname "$0")"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export CAPIFFY_SSL_VERIFY="${CAPIFFY_SSL_VERIFY:-false}"
export MIRROR_POLL_SEC="${MIRROR_POLL_SEC:-5}"

echo "MT5→Capiffy watchdog — restart on exit (Ctrl+C to stop)"
while true; do
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) starting automator…"
  python3 automator.py || echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) automator exited $?"
  sleep 10
done
