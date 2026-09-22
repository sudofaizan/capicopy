# capicopy — MT5 pending orders → Capiffy

Mirror pending orders from your **MT5 REST API** to **Capiffy** (`api.capiffy.com`): place, modify, cancel in sync.

## Quick start

```bash
cp .env.example .env   # paste Capiffy tokens + MT5_API_URL
python3 capiffy_auth.py test
./run_automator.sh
```

## EC2 (Amazon Linux)

See [README-EC2.md](README-EC2.md) and `sudo ./ec2-setup-amazon-linux.sh`.

## Layout

| File | Role |
|------|------|
| `automator.py` | Poll MT5, sync Capiffy |
| `capiffy_client.py` | Capiffy trade API |
| `capiffy_auth.py` | Token refresh |
| `mt5_client.py` | MT5 VPS `GET /getOrders` |

Do not commit `.env` or `tokens.json`.
