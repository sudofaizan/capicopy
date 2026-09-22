#!/usr/bin/env python3
"""Pull active MT5 positions + pending orders from mt5_vps_api."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

MT5_API = os.environ.get("MT5_API_URL", "http://13.42.76.172:8080").rstrip("/")
MT5_KEY = os.environ.get("MT5_API_KEY", "alphafx")


def api_get(path: str) -> dict:
    req = urllib.request.Request(
        f"{MT5_API}{path}",
        headers={"X-API-Key": MT5_KEY, "Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def fetch_orders(symbol: str = "") -> tuple[list, dict]:
    """GET /getOrders (preferred) or orders[] from /getAccountHealth."""
    q = f"?symbol={symbol}" if symbol else ""
    try:
        data = api_get(f"/getOrders{q}")
        if data.get("ok"):
            return data.get("orders") or [], data
    except urllib.error.HTTPError:
        pass

    health = api_get("/getAccountHealth")
    if not health.get("ok"):
        raise RuntimeError(health.get("error") or "getAccountHealth failed")
    if "orders" in health:
        rows = health.get("orders") or []
        if symbol:
            rows = [o for o in rows if o.get("symbol", "").upper() == symbol.upper()]
        return rows, {"ok": True, "source": "getAccountHealth", "count": len(rows), "orders": rows}
    return [], {
        "ok": True,
        "count": health.get("floating", {}).get("orders_count", 0),
        "orders": [],
        "note": "Redeploy server.py — use GET /getOrders or updated /getAccountHealth",
    }


def fetch_positions(symbol: str = "") -> tuple[list, dict]:
    q = f"?symbol={symbol}" if symbol else ""
    try:
        data = api_get(f"/getPositions{q}")
        if data.get("ok"):
            return data.get("positions") or [], data
    except urllib.error.HTTPError:
        pass

    health = api_get("/getAccountHealth")
    rows = health.get("positions") or []
    if symbol:
        rows = [p for p in rows if p.get("symbol", "").upper() == symbol.upper()]
    return rows, {"ok": True, "source": "getAccountHealth", "count": len(rows), "positions": rows}


def main() -> None:
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else ""

    health = api_get("/getAccountHealth")
    if not health.get("ok"):
        print(json.dumps(health, indent=2))
        raise SystemExit(1)

    acct = health.get("account", {})
    print(f"MT5 {acct.get('login')} @ {acct.get('server')}")
    print(f"Balance ${health['balance']['balance']:.2f} · Equity ${health['balance']['equity']:.2f}")
    print()

    pos, pos_meta = fetch_positions(symbol)
    ord_list, ord_meta = fetch_orders(symbol)

    print(f"Open positions: {len(pos)}")
    for p in pos:
        print(
            f"  #{p['ticket']} {p['type'].upper()} {p['volume']} {p['symbol']} "
            f"@ {p.get('price_open', p.get('price', '?'))} SL {p['sl']} TP {p['tp']} "
            f"P/L ${p.get('profit', 0):.2f}"
        )
    if not pos:
        print("  (none)")

    print(f"\nPending orders: {len(ord_list)}")
    for o in ord_list:
        print(
            f"  #{o['ticket']} {o['type'].upper()} {o['volume']} {o['symbol']} "
            f"@ {o.get('price', '?')} SL {o['sl']} TP {o['tp']} magic {o.get('magic', 0)}"
        )
    if not ord_list:
        print("  (none)")
    if ord_meta.get("note"):
        print(f"  Note: {ord_meta['note']}")

    print("\n--- JSON ---")
    print(json.dumps({"positions": pos_meta, "orders": ord_meta}, indent=2))


if __name__ == "__main__":
    main()
