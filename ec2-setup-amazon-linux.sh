#!/usr/bin/env bash
# One-time setup on Amazon Linux 2 / Amazon Linux 2023 (e.g. ap-south-1 Mumbai).
# Installs Python, copies bridge to /opt/capiffy-bridge, systemd service.
#
# Usage (on EC2, after copying this repo folder or capiffy_bridge/):
#   sudo INSTALL_DIR=/opt/capiffy-bridge ./ec2-setup-amazon-linux.sh
#
# Before start: edit /opt/capiffy-bridge/.env (Capiffy tokens + MT5_API_URL).

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/capiffy-bridge}"
SERVICE_USER="${SERVICE_USER:-capiffy}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run with sudo: sudo $0"
  exit 1
fi

echo "==> Packages (python3)"
if command -v dnf >/dev/null 2>&1; then
  dnf install -y python3 python3-pip
elif command -v yum >/dev/null 2>&1; then
  yum install -y python3 python3-pip
else
  echo "Unsupported OS (need dnf or yum)"
  exit 1
fi

echo "==> Service user: ${SERVICE_USER}"
if ! id "${SERVICE_USER}" &>/dev/null; then
  useradd --system --home-dir "${INSTALL_DIR}" --shell /sbin/nologin "${SERVICE_USER}"
fi

echo "==> Install files → ${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"
for f in automator.py capiffy_auth.py capiffy_client.py mt5_client.py run_automator.sh .env.example; do
  if [[ -f "${SCRIPT_DIR}/${f}" ]]; then
    cp -f "${SCRIPT_DIR}/${f}" "${INSTALL_DIR}/"
  fi
done
chmod +x "${INSTALL_DIR}/run_automator.sh" 2>/dev/null || true

if [[ -f "${SCRIPT_DIR}/.env" ]] && grep -q CAPIFFY_REFRESH_TOKEN "${SCRIPT_DIR}/.env" 2>/dev/null; then
  cp -f "${SCRIPT_DIR}/.env" "${INSTALL_DIR}/.env"
  echo "    Copied configured .env from ${SCRIPT_DIR}"
elif [[ ! -f "${INSTALL_DIR}/.env" ]]; then
  cp "${INSTALL_DIR}/.env.example" "${INSTALL_DIR}/.env"
  echo "    Created ${INSTALL_DIR}/.env — EDIT tokens before starting service."
fi

touch "${INSTALL_DIR}/mirror_state.json"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"
chmod 600 "${INSTALL_DIR}/.env" 2>/dev/null || true

echo "==> systemd unit"
cp -f "${SCRIPT_DIR}/systemd/capiffy-mirror.service" /etc/systemd/system/capiffy-mirror.service
# Ensure paths match INSTALL_DIR
sed -i "s|/opt/capiffy-bridge|${INSTALL_DIR}|g" /etc/systemd/system/capiffy-mirror.service
sed -i "s|User=capiffy|User=${SERVICE_USER}|g" /etc/systemd/system/capiffy-mirror.service
sed -i "s|Group=capiffy|Group=${SERVICE_USER}|g" /etc/systemd/system/capiffy-mirror.service

systemctl daemon-reload
systemctl enable capiffy-mirror.service

echo ""
echo "Setup complete."
echo ""
echo "1) Edit secrets:"
echo "     sudo nano ${INSTALL_DIR}/.env"
echo "   Required: CAPIFFY_ACCESS_TOKEN, CAPIFFY_REFRESH_TOKEN, CAPIFFY_ACCOUNT_ID,"
echo "              MT5_API_URL (e.g. http://13.42.76.172:8080), MT5_API_KEY"
echo ""
echo "2) Test (as ${SERVICE_USER}):"
echo "     sudo -u ${SERVICE_USER} bash -c 'cd ${INSTALL_DIR} && set -a && source .env && set +a && python3 capiffy_auth.py test'"
echo "     sudo -u ${SERVICE_USER} bash -c 'cd ${INSTALL_DIR} && set -a && source .env && set +a && python3 -c \"from mt5_client import get_orders; print(get_orders())\"'"
echo ""
echo "3) Start mirror:"
echo "     sudo systemctl start capiffy-mirror"
echo "     sudo journalctl -u capiffy-mirror -f"
echo ""
echo "Optional: MIRROR_MAGIC=202611 in .env to mirror only that magic (omit = all pending)."
