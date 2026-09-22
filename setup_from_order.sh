#!/usr/bin/env bash
# Pull Capiffy tokens from order.sh into capiffy_bridge/.env
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
ORDER="${1:-$ROOT/../order.sh}"
ENV="$ROOT/.env"

if [[ ! -f "$ORDER" ]]; then
  echo "order.sh not found at: $ORDER"
  echo "Usage: ./setup_from_order.sh [path/to/order.sh]"
  exit 1
fi

ACCESS=$(grep -oE "authorization: Bearer [^'\"]+" "$ORDER" | head -1 | sed 's/authorization: Bearer //')
REFRESH=$(grep -oE 'refreshToken=[^;]+' "$ORDER" | head -1 | sed 's/refreshToken=//')
DEVICE=$(grep -oE "x-device-cid: [^'\"]+" "$ORDER" | head -1 | sed 's/x-device-cid: //')
ACCOUNT=$(grep -oE '"accountId":"[^"]+"' "$ORDER" | head -1 | sed 's/"accountId":"//;s/"$//')

if [[ -z "$ACCESS" || -z "$REFRESH" ]]; then
  echo "Could not parse access/refresh token from $ORDER"
  echo "Copy Bearer + refreshToken from DevTools into .env manually."
  exit 1
fi

cat > "$ENV" <<EOF
# Auto-generated from order.sh — re-run setup_from_order.sh after re-login
CAPIFFY_ACCESS_TOKEN=$ACCESS
CAPIFFY_REFRESH_TOKEN=$REFRESH
CAPIFFY_DEVICE_CID=${DEVICE:-}
CAPIFFY_ACCOUNT_ID=${ACCOUNT:-}

CAPIFFY_REFRESH_URL=https://api.capiffy.com/api/auth/refresh
CAPIFFY_REFRESH_METHOD=POST
CAPIFFY_REFRESH_BODY=empty
EOF

echo "Wrote $ENV"
echo "  access:  ${#ACCESS} chars"
echo "  refresh: ${#REFRESH} chars"
echo "  device:  ${DEVICE:-—}"
echo "  account: ${ACCOUNT:-—}"
echo ""
echo "Next:"
echo "  python3 capiffy_auth.py status"
echo "  python3 capiffy_auth.py refresh"
