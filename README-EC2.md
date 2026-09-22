# MT5 → Capiffy mirror on EC2 (Amazon Linux, Mumbai)

Polls your **MT5 VPS API** (`GET /getOrders`) and keeps **Capiffy** pending orders in sync: place, modify, cancel.

No MT5 terminal on EC2 — only HTTPS to `api.capiffy.com` and HTTP to your MT5 API (e.g. `13.42.76.172:8080`).

## Mumbai EC2 checklist

1. **Instance**: Amazon Linux 2023, `t3.micro` or small, **ap-south-1**.
2. **Security group (EC2)**:
   - Outbound: **443** (Capiffy), **8080** (or your MT5 API port) to MT5 server IP.
   - Inbound: none required for the mirror (SSH 22 from your IP only).
3. **MT5 server**: allow **8080** from the EC2 **public IP** (or use a private link/VPN if both in AWS).

## Deploy

### A — Copy folder from your Mac

```bash
scp -r capiffy_bridge ec2-user@YOUR_EC2_IP:~/
ssh ec2-user@YOUR_EC2_IP
cd ~/capiffy_bridge
sudo ./ec2-setup-amazon-linux.sh
sudo nano /opt/capiffy-bridge/.env   # paste Capiffy tokens + MT5 URL
# If you edited ~/capicopy/.env instead, copy it:
sudo cp ~/capicopy/.env /opt/capiffy-bridge/.env
sudo chmod 600 /opt/capiffy-bridge/.env
sudo chown capiffy:capiffy /opt/capiffy-bridge/.env
sudo systemctl start capiffy-mirror
sudo journalctl -u capiffy-mirror -f
```

### B — Git clone on EC2

```bash
git clone YOUR_REPO ~/AlphaFX-V5
cd ~/AlphaFX-V5/capiffy_bridge
sudo ./ec2-setup-amazon-linux.sh
# edit /opt/capiffy-bridge/.env
sudo systemctl start capiffy-mirror
```

## `.env` (required)

Copy from `.env.example`. Minimum:

| Variable | Example |
|----------|---------|
| `CAPIFFY_ACCESS_TOKEN` | JWT from browser Bearer |
| `CAPIFFY_REFRESH_TOKEN` | JWT from `refreshToken` cookie |
| `CAPIFFY_DEVICE_CID` | `x-device-cid` header |
| `CAPIFFY_ACCOUNT_ID` | Capiffy account id |
| `CAPIFFY_REFRESH_URL` | `https://api.capiffy.com/api/auth/refresh` |
| `MT5_API_URL` | `http://13.42.76.172:8080` |
| `MT5_API_KEY` | `alphafx` |

### Telegram ([@cqpicopialpha](https://t.me/cqpicopialpha))

```bash
nano ~/telegram.env
```

```env
TELEGRAM=YOUR_BOT_TOKEN
TELEGRAM_CHAT_ID=@cqpicopialpha
```

Add to `/opt/capiffy-bridge/.env`:

```env
TELEGRAM_ENV_FILE=/home/ec2-user/telegram.env
```

Bot must be **admin** on the channel. Alerts: place, modify (price/SL/TP/vol), remove.

Optional:

- `MIRROR_MAGIC=202611` — only mirror orders with this magic (default: all pending).
- `MIRROR_POLL_SEC=5` — poll interval.
- `MIRROR_SYMBOL_MAP={"XAUUSD.c":"XAUUSD"}` — symbol aliases.
- `CAPIFFY_SSL_VERIFY=false` — set on Linux if refresh SSL fails.

## Commands

```bash
sudo systemctl status capiffy-mirror
sudo systemctl restart capiffy-mirror
sudo journalctl -u capiffy-mirror -n 100 --no-pager
cat /opt/capiffy-bridge/mirror_state.json   # MT5 ticket → Capiffy order id
```

## Without systemd

```bash
cd /opt/capiffy-bridge
nohup ./ec2-mirror-watchdog.sh >> mirror.log 2>&1 &
```

## How it behaves

- New MT5 pending → **place** same on Capiffy.
- MT5 pending changed (price/SL/TP/volume) → **PATCH** Capiffy.
- MT5 pending removed → **cancel** Capiffy.
- State file: `mirror_state.json` (survives restarts).

Refresh tokens in `.env` when Capiffy refresh JWT expires (~7 days); access token auto-refreshes in the background.
