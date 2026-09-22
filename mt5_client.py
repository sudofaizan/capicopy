"""MT5 VPS API client (getOrders / getPositions)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

MT5_API = os.environ.get("MT5_API_URL", "http://13.42.76.172:8080").rstrip("/")
MT5_KEY = os.environ.get("MT5_API_KEY", "alphafx")


def _get(path: str) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{MT5_API}{path}",
        headers={"X-API-Key": MT5_KEY, "Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def get_orders(symbol: str = "", magic: int | None = None) -> list[dict[str, Any]]:
    q_parts: list[str] = []
    if symbol:
        q_parts.append(f"symbol={symbol}")
    if magic is not None:
        q_parts.append(f"magic={magic}")
    q = ("?" + "&".join(q_parts)) if q_parts else ""

    data = _get(f"/getOrders{q}")
    if not data.get("ok"):
        raise RuntimeError(data.get("error") or "getOrders failed")
    return data.get("orders") or []


def get_positions(symbol: str = "", magic: int | None = None) -> list[dict[str, Any]]:
    q_parts: list[str] = []
    if symbol:
        q_parts.append(f"symbol={symbol}")
    if magic is not None:
        q_parts.append(f"magic={magic}")
    q = ("?" + "&".join(q_parts)) if q_parts else ""

    data = _get(f"/getPositions{q}")
    if not data.get("ok"):
        raise RuntimeError(data.get("error") or "getPositions failed")
    return data.get("positions") or []
