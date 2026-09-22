"""
Capiffy trade API client (uses capiffy_auth for auto-refresh).
Future: MT5 bridge will call place_order() when your EA fires.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from capiffy_auth import CapiffyTokens, get_valid_tokens, _load_dotenv, capiffy_urlopen

API_BASE = "https://api.capiffy.com"


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    tokens = get_valid_tokens()
    url = path if path.startswith("http") else f"{API_BASE}{path}"
    headers = {
        "accept": "application/json, text/plain, */*",
        "authorization": f"Bearer {tokens.access_token}",
        "content-type": "application/json",
        "origin": "https://capiffy.com",
        "referer": "https://capiffy.com/",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
        ),
    }
    if tokens.device_cid:
        headers["x-device-cid"] = tokens.device_cid
    if tokens.refresh_token:
        headers["Cookie"] = f"refreshToken={tokens.refresh_token}"

    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with capiffy_urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw.strip() else {"ok": True}
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Capiffy HTTP {exc.code}: {err_body[:500]}") from exc


def get_snapshot(account_id: str | None = None) -> dict[str, Any]:
    """GET /api/trade/snapshot/{accountId} — positions, balance, etc."""
    tokens = get_valid_tokens()
    acct = account_id or tokens.account_id or os.environ.get("CAPIFFY_ACCOUNT_ID", "")
    if not acct:
        raise ValueError("account_id required (CAPIFFY_ACCOUNT_ID in .env)")
    return _request("GET", f"/api/trade/snapshot/{acct}")


def get_open_orders(account_id: str | None = None) -> list[dict[str, Any]]:
    snap = get_snapshot(account_id)
    return snap.get("data", {}).get("orders") or []


def get_open_positions(account_id: str | None = None) -> list[dict[str, Any]]:
    snap = get_snapshot(account_id)
    return snap.get("data", {}).get("positions") or []


def modify_position(
    position_id: str,
    *,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    account_id: str | None = None,
) -> dict[str, Any]:
    """PATCH /api/trade/position/{positionId} — SL/TP on open trade."""
    _ = account_id
    body: dict[str, Any] = {}
    if stop_loss is not None:
        body["stopLoss"] = stop_loss
    if take_profit is not None:
        body["takeProfit"] = take_profit
    if not body:
        raise ValueError("stop_loss or take_profit required")
    return _request("PATCH", f"/api/trade/position/{position_id}", body)


def close_position(position_id: str, account_id: str | None = None) -> dict[str, Any]:
    """DELETE /api/trade/position/{positionId} — close open trade."""
    _ = account_id
    return _request("DELETE", f"/api/trade/position/{position_id}")


def cancel_order(order_id: str, account_id: str | None = None) -> dict[str, Any]:
    """DELETE /api/trade/order/{orderId}"""
    _ = account_id  # account scoped by auth token
    return _request("DELETE", f"/api/trade/order/{order_id}")


def modify_order(
    order_id: str,
    *,
    price: float | None = None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    volume: float | None = None,
    account_id: str | None = None,
) -> dict[str, Any]:
    """PATCH /api/trade/order/{orderId}"""
    _ = account_id
    body: dict[str, Any] = {}
    if price is not None:
        body["price"] = price
    if stop_loss is not None:
        body["stopLoss"] = stop_loss
    if take_profit is not None:
        body["takeProfit"] = take_profit
    if volume is not None:
        body["volume"] = volume
    return _request("PATCH", f"/api/trade/order/{order_id}", body)


def place_order(
    *,
    symbol: str,
    side: str,
    volume: float,
    order_type: str = "LIMIT",
    price: float | None = None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    account_id: str | None = None,
) -> dict[str, Any]:
    tokens = get_valid_tokens()
    acct = account_id or tokens.account_id or os.environ.get("CAPIFFY_ACCOUNT_ID", "")
    if not acct:
        raise ValueError("account_id required (CAPIFFY_ACCOUNT_ID in .env)")

    payload: dict[str, Any] = {
        "accountId": acct,
        "symbolTicker": symbol.upper(),
        "side": side.upper(),
        "volume": volume,
        "orderType": order_type.upper(),
    }
    if price is not None:
        payload["price"] = price
    if stop_loss is not None:
        payload["stopLoss"] = stop_loss
    if take_profit is not None:
        payload["takeProfit"] = take_profit

    return _request("POST", "/api/trade/order", payload)


def extract_order_id(response: dict[str, Any]) -> str | None:
    if not response:
        return None
    data = response.get("data")
    if isinstance(data, dict):
        for key in ("id", "orderId", "order_id"):
            if data.get(key):
                return str(data[key])
    for key in ("id", "orderId", "order_id"):
        if response.get(key):
            return str(response[key])
    return None

if __name__ == "__main__":
    _load_dotenv()
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 capiffy_client.py status")
        print("       python3 capiffy_client.py order BUY XAUUSD 0.01 4425.13")
        raise SystemExit(1)

    if sys.argv[1] == "status":
        from capiffy_auth import print_status

        print_status()
    elif sys.argv[1] == "snapshot":
        print(json.dumps(get_snapshot(), indent=2))
    elif sys.argv[1] == "order" and len(sys.argv) >= 6:
        side, sym, vol, px = sys.argv[2], sys.argv[3], float(sys.argv[4]), float(sys.argv[5])
        print(place_order(symbol=sym, side=side, volume=vol, price=px))
    else:
        print("Unknown command")
        raise SystemExit(1)
