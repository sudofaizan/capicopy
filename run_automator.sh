#!/usr/bin/env bash
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
export TOKEN_REFRESH_SEC="${TOKEN_REFRESH_SEC:-600}"

exec python3 automator.py "$@"
