#!/usr/bin/env python3
"""
MT5 pending-order → Capiffy mirror.

Polls MT5 GET /getOrders only. Calls Capiffy when MT5 orders are added,
updated, or removed. Token refresh runs in a background thread.

Usage:
  cd capiffy_bridge && ./run_automator.sh
  # or: python3 automator.py
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

from capiffy_auth import _load_dotenv, get_valid_tokens
from capiffy_client import (
    cancel_order,
    extract_order_id,
    get_open_orders,
    get_open_positions,
    modify_order,
    close_position,
    modify_position,
    place_order,
)
from mt5_client import get_orders, get_positions
from telegram_notify import (
    notify_modify,
    notify_place,
    notify_position_closed,
    notify_position_linked,
    notify_position_modify,
    notify_removed,
)

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "mirror_state.json"

_log = logging.getLogger("automator")
_running = True


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    if not raw.strip():
        return default
    return int(raw)


def _env_magic() -> int | None:
    raw = os.environ.get("MIRROR_MAGIC", "").strip()
    if not raw:
        return None
    return int(raw)


def _mirror_positions() -> bool:
    return os.environ.get("MIRROR_POSITIONS", "true").lower() not in ("0", "false", "no")


def _symbol_map() -> dict[str, str]:
    raw = os.environ.get("MIRROR_SYMBOL_MAP", "").strip()
    if raw:
        try:
            return {k.upper(): v.upper() for k, v in json.loads(raw).items()}
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid MIRROR_SYMBOL_MAP JSON: {exc}") from exc
    return {
        "XAUUSD": "XAUUSD",
        "XAUUSD.I#": "XAUUSD",
        "GOLD": "XAUUSD",
        "GOLD.I#": "XAUUSD",
        "EURUSD": "EURUSD",
        "GBPUSD": "GBPUSD",
        "USDJPY": "USDJPY",
    }


def normalize_symbol(mt5_symbol: str) -> str | None:
    sym = mt5_symbol.upper().strip()
    mapping = _symbol_map()
    if sym in mapping:
        return mapping[sym]
    base = sym.split(".")[0].split("#")[0].split("_")[0]
    if base in mapping:
        return mapping[base]
    if base in ("XAU", "GOLD"):
        return "XAUUSD"
    return base if len(base) >= 6 else None


def mt5_to_capiffy_side_type(mt5_type: str) -> tuple[str, str] | None:
    t = mt5_type.lower()
    if t == "buy_limit":
        return "BUY", "LIMIT"
    if t == "sell_limit":
        return "SELL", "LIMIT"
    if t == "buy_stop":
        return "BUY", "STOP"
    if t == "sell_stop":
        return "SELL", "STOP"
    return None


def _fp_value(x: float | int | None) -> float:
    if x is None:
        return 0.0
    try:
        return round(float(x), 5)
    except (TypeError, ValueError):
        return 0.0


def order_fingerprint(order: dict[str, Any]) -> list[Any]:
    return [
        order.get("symbol", ""),
        order.get("type", ""),
        _fp_value(order.get("volume")),
        _fp_value(order.get("price")),
        _fp_value(order.get("sl")),
        _fp_value(order.get("tp")),
        int(order.get("magic") or 0),
    ]


def position_fingerprint(pos: dict[str, Any]) -> list[Any]:
    return [_fp_value(pos.get("sl")), _fp_value(pos.get("tp"))]


def mt5_position_side(pos: dict[str, Any]) -> str:
    return "BUY" if str(pos.get("type", "")).lower() == "buy" else "SELL"


def load_state() -> dict[str, Any]:
    if not STATE_FILE.is_file():
        return {"orders": {}}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if "orders" not in data:
            data["orders"] = {}
        if "positions" not in data:
            data["positions"] = {}
        return data
    except Exception as exc:
        _log.warning("Could not read %s: %s — starting fresh", STATE_FILE.name, exc)
        return {"orders": {}, "positions": {}}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def sl_tp_for_capiffy(sl: float | None, tp: float | None) -> tuple[float | None, float | None]:
    out_sl = float(sl) if sl and float(sl) > 0 else None
    out_tp = float(tp) if tp and float(tp) > 0 else None
    return out_sl, out_tp


def token_refresh_loop() -> None:
    interval = _env_int("TOKEN_REFRESH_SEC", 600)
    while _running:
        try:
            tokens = get_valid_tokens()
            left = tokens.access_expires_in()
            _log.debug("Token OK · access expires in %ss", left if left is not None else "?")
        except Exception as exc:
            _log.error("Token refresh failed: %s", exc)
        for _ in range(interval):
            if not _running:
                return
            time.sleep(1)


def cap_matches_mt5(cap_o: dict[str, Any], mt5_o: dict[str, Any]) -> bool:
    mapped = mt5_to_capiffy_side_type(mt5_o.get("type", ""))
    if not mapped:
        return False
    side, order_type = mapped
    cap_sym = normalize_symbol(mt5_o.get("symbol", ""))
    if not cap_sym:
        return False
    return (
        str(cap_o.get("symbol", "")).upper() == cap_sym
        and str(cap_o.get("side", "")).upper() == side
        and str(cap_o.get("type", "")).upper() == order_type
        and _fp_value(cap_o.get("volume")) == _fp_value(mt5_o.get("volume"))
        and _fp_value(cap_o.get("price")) == _fp_value(mt5_o.get("price"))
        and _fp_value(cap_o.get("stopLoss")) == _fp_value(mt5_o.get("sl"))
        and _fp_value(cap_o.get("takeProfit")) == _fp_value(mt5_o.get("tp"))
    )


def find_matching_capiffy_orders(
    mt5_o: dict[str, Any], cap_orders: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [co for co in cap_orders if cap_matches_mt5(co, mt5_o)]


def cap_position_matches_mt5(mt5_p: dict[str, Any], cap_p: dict[str, Any]) -> bool:
    cap_sym = normalize_symbol(mt5_p.get("symbol", ""))
    if not cap_sym:
        return False
    cap_side = str(cap_p.get("side") or "").upper()
    sym = str(cap_p.get("symbol") or cap_p.get("symbolTicker") or "").upper()
    if sym != cap_sym or cap_side != mt5_position_side(mt5_p):
        return False
    return _fp_value(cap_p.get("volume")) == _fp_value(mt5_p.get("volume"))


def find_cap_position_for_mt5(
    mt5_p: dict[str, Any],
    cap_positions: list[dict[str, Any]],
    exclude_ids: set[str],
) -> dict[str, Any] | None:
    for cp in cap_positions:
        cid = str(cp.get("id") or "")
        if not cid or cid in exclude_ids:
            continue
        if cap_position_matches_mt5(mt5_p, cp):
            return cp
    return None


def mt5_pending_became_position(
    entry: dict[str, Any], mt5_positions: list[dict[str, Any]]
) -> dict[str, Any] | None:
    sym = entry.get("cap_sym") or normalize_symbol(str(entry.get("symbol", "")))
    side = str(entry.get("side", "")).upper()
    vol = _fp_value(entry.get("volume"))
    if not sym or not side:
        return None
    for p in mt5_positions:
        if normalize_symbol(p.get("symbol", "")) != sym:
            continue
        if mt5_position_side(p) != side:
            continue
        if _fp_value(p.get("volume")) != vol:
            continue
        return p
    return None


def _missing_grace_polls() -> int:
    return max(1, _env_int("MIRROR_MISSING_GRACE", 3))


def _cancel_orphan_capiffy(
    cap_id: str, ticket: str, reason: str, cap_ids: set[str]
) -> None:
    if cap_id not in cap_ids:
        return
    try:
        resp = cancel_order(cap_id)
        cap_ids.discard(cap_id)
        _log.info("Cancelled orphan Capiffy %s (%s · MT5 #%s): %s", cap_id, reason, ticket, resp)
        notify_removed(str(cap_id), ticket, f"orphan cancel · {reason}")
    except Exception as exc:
        _log.error("Orphan cancel failed Capiffy %s: %s", cap_id, exc)


def sync_positions(
    state: dict[str, Any],
    magic: int | None,
    cap_positions: list[dict[str, Any]],
) -> None:
    if not _mirror_positions():
        return
    mt5_positions = get_positions(magic=magic)
    tracked_pos: dict[str, Any] = state.setdefault("positions", {})
    linked_cap_ids = {str(v.get("capiffy_id")) for v in tracked_pos.values() if v.get("capiffy_id")}
    current: set[str] = set()

    for p in mt5_positions:
        pt = str(p["ticket"])
        current.add(pt)
        fp = position_fingerprint(p)
        sl, tp = sl_tp_for_capiffy(p.get("sl"), p.get("tp"))
        cap_sym = normalize_symbol(p.get("symbol", "")) or ""
        side = mt5_position_side(p)

        if pt not in tracked_pos:
            cap_p = find_cap_position_for_mt5(p, cap_positions, linked_cap_ids)
            if cap_p:
                cid = str(cap_p["id"])
                tracked_pos[pt] = {"capiffy_id": cid, "fingerprint": fp}
                linked_cap_ids.add(cid)
                _log.info("Linked MT5 position #%s · Capiffy position %s", pt, cid)
            continue

        entry = tracked_pos[pt]
        cid = str(entry.get("capiffy_id", ""))
        old_fp = entry.get("fingerprint") or []
        if old_fp == fp or not cid:
            continue
        try:
            modify_position(cid, stop_loss=sl, take_profit=tp)
            notify_position_modify(cid, pt, cap_sym, side, list(old_fp), fp)
            entry["fingerprint"] = fp
            _log.info("Updated Capiffy position %s ← MT5 #%s SL/TP", cid, pt)
        except Exception as exc:
            _log.error("Position modify failed Capiffy %s (MT5 #%s): %s", cid, pt, exc)

    cap_pos_ids = {str(p.get("id")) for p in cap_positions if p.get("id")}
    for pt in list(tracked_pos.keys()):
        if pt not in current:
            entry = tracked_pos[pt]
            cid = str(entry.get("capiffy_id") or "")
            if cid and cid in cap_pos_ids:
                try:
                    resp = close_position(cid)
                    _log.info("Closed Capiffy position %s (MT5 #%s gone): %s", cid, pt, resp)
                    notify_position_closed(cid, pt, "MT5 closed → Capiffy closed")
                except Exception as exc:
                    _log.error("Close failed Capiffy %s (MT5 #%s): %s", cid, pt, exc)
                    continue
            elif cid:
                _log.info("MT5 position #%s gone · Capiffy %s already closed", pt, cid)
            del tracked_pos[pt]


def sync_once(state: dict[str, Any]) -> dict[str, Any]:
    magic = _env_magic()
    mt5_orders = get_orders(magic=magic)
    mt5_positions = get_positions(magic=magic) if _mirror_positions() else []
    mt5_by_ticket: dict[str, dict[str, Any]] = {}
    for o in mt5_orders:
        mapped = mt5_to_capiffy_side_type(o.get("type", ""))
        if not mapped:
            continue
        cap_sym = normalize_symbol(o.get("symbol", ""))
        if not cap_sym:
            _log.warning("Skip MT5 #%s — unknown symbol %s", o.get("ticket"), o.get("symbol"))
            continue
        mt5_by_ticket[str(o["ticket"])] = o

    cap_orders = get_open_orders()
    cap_positions = get_open_positions() if _mirror_positions() else []
    cap_ids = {str(o.get("id")) for o in cap_orders if o.get("id")}

    tracked: dict[str, Any] = state.setdefault("orders", {})
    current = set(mt5_by_ticket.keys())

    # Removed on MT5 → filled into position, or cancel Capiffy pending
    for ticket, entry in list(tracked.items()):
        if ticket in current:
            continue
        filled = mt5_pending_became_position(entry, mt5_positions) if _mirror_positions() else None
        if filled is not None:
            pos_ticket = str(filled["ticket"])
            linked = state.setdefault("positions", {})
            used = {str(v.get("capiffy_id")) for v in linked.values() if v.get("capiffy_id")}
            cap_p = find_cap_position_for_mt5(filled, cap_positions, used)
            if cap_p:
                cid = str(cap_p["id"])
                linked[pos_ticket] = {
                    "capiffy_id": cid,
                    "fingerprint": position_fingerprint(filled),
                    "from_order": ticket,
                }
                _log.info(
                    "MT5 pending #%s filled → position #%s · Capiffy position %s",
                    ticket,
                    pos_ticket,
                    cid,
                )
                notify_position_linked(cid, pos_ticket, ticket)
            else:
                _log.warning(
                    "MT5 pending #%s filled as #%s but no matching Capiffy position yet",
                    ticket,
                    pos_ticket,
                )
            del tracked[ticket]
            continue

        cap_id = entry.get("capiffy_id")
        if cap_id and str(cap_id) in cap_ids:
            try:
                resp = cancel_order(str(cap_id))
                _log.info("Removed Capiffy order %s (MT5 #%s gone): %s", cap_id, ticket, resp)
                notify_removed(str(cap_id), ticket, "MT5 pending removed → Capiffy cancelled")
            except Exception as exc:
                _log.error("Cancel failed Capiffy %s (MT5 #%s): %s", cap_id, ticket, exc)
                continue
        else:
            _log.info("MT5 #%s gone · Capiffy %s already absent", ticket, cap_id)
        del tracked[ticket]

    # New or updated on MT5
    for ticket, o in mt5_by_ticket.items():
        side, order_type = mt5_to_capiffy_side_type(o["type"])  # type: ignore[arg-type]
        cap_sym = normalize_symbol(o["symbol"])  # type: ignore[arg-type]
        fp = order_fingerprint(o)
        sl, tp = sl_tp_for_capiffy(o.get("sl"), o.get("tp"))

        if ticket not in tracked:
            matches = find_matching_capiffy_orders(o, cap_orders)
            if matches:
                cap_id = str(matches[0]["id"])
                tracked[ticket] = {
                    "capiffy_id": cap_id,
                    "fingerprint": fp,
                    "missing_polls": 0,
                    "cap_sym": cap_sym,
                    "side": side,
                    "volume": float(o["volume"]),
                }
                _log.info("Adopted existing Capiffy %s ← MT5 #%s (skip duplicate place)", cap_id, ticket)
                for extra in matches[1:]:
                    _cancel_orphan_capiffy(str(extra["id"]), ticket, "duplicate match", cap_ids)
                continue
            try:
                resp = place_order(
                    symbol=cap_sym,  # type: ignore[arg-type]
                    side=side,
                    volume=float(o["volume"]),
                    order_type=order_type,
                    price=float(o["price"]),
                    stop_loss=sl,
                    take_profit=tp,
                )
                cap_id = extract_order_id(resp)
                if not cap_id:
                    _log.error("Place OK but no order id for MT5 #%s: %s", ticket, resp)
                    continue
                tracked[ticket] = {
                    "capiffy_id": cap_id,
                    "fingerprint": fp,
                    "missing_polls": 0,
                    "cap_sym": cap_sym,
                    "side": side,
                    "volume": float(o["volume"]),
                }
                _log.info(
                    "Placed Capiffy %s ← MT5 #%s %s %s %s @ %s",
                    cap_id,
                    ticket,
                    side,
                    cap_sym,
                    o["volume"],
                    o["price"],
                )
                notify_place(cap_id, ticket, o, cap_sym, side, order_type)
            except Exception as exc:
                _log.error("Place failed MT5 #%s: %s", ticket, exc)
            continue

        entry = tracked[ticket]
        cap_id = str(entry.get("capiffy_id", ""))
        old_fp = entry.get("fingerprint")

        if cap_id and cap_id not in cap_ids:
            missing = int(entry.get("missing_polls", 0)) + 1
            entry["missing_polls"] = missing
            grace = _missing_grace_polls()
            if missing < grace:
                _log.debug(
                    "Capiffy %s not in snapshot (%s/%s) — waiting",
                    cap_id,
                    missing,
                    grace,
                )
                continue
            matches = find_matching_capiffy_orders(o, cap_orders)
            if matches:
                new_id = str(matches[0]["id"])
                if new_id != cap_id:
                    _log.info(
                        "Re-linked Capiffy %s → %s ← MT5 #%s (snapshot lag)",
                        cap_id,
                        new_id,
                        ticket,
                    )
                    entry["capiffy_id"] = new_id
                entry["missing_polls"] = 0
                for extra in matches[1:]:
                    _cancel_orphan_capiffy(str(extra["id"]), ticket, "duplicate match", cap_ids)
                continue
            _log.warning(
                "Capiffy %s missing after %s polls — will re-place MT5 #%s on next cycle",
                cap_id,
                grace,
                ticket,
            )
            del tracked[ticket]
            continue

        entry["missing_polls"] = 0

        if old_fp == fp:
            continue

        try:
            resp = modify_order(
                cap_id,
                price=float(o["price"]),
                stop_loss=sl,
                take_profit=tp,
                volume=float(o["volume"]),
            )
            notify_modify(
                cap_id,
                ticket,
                o,
                cap_sym,
                side,
                order_type,
                list(old_fp) if old_fp else [],
                fp,
            )
            entry["fingerprint"] = fp
            _log.info("Updated Capiffy %s ← MT5 #%s: %s", cap_id, ticket, resp)
        except Exception as exc:
            _log.error("Modify failed Capiffy %s (MT5 #%s): %s", cap_id, ticket, exc)

    # Cancel extra Capiffy orders when multiple match the same MT5 pending order.
    for ticket, o in mt5_by_ticket.items():
        matches = find_matching_capiffy_orders(o, cap_orders)
        if len(matches) <= 1:
            continue
        entry = tracked.get(ticket) or {}
        keep_id = str(entry.get("capiffy_id") or matches[0]["id"])
        if keep_id not in {str(m["id"]) for m in matches}:
            keep_id = str(matches[0]["id"])
        if ticket in tracked:
            tracked[ticket]["capiffy_id"] = keep_id
            tracked[ticket]["missing_polls"] = 0
        for co in matches:
            cid = str(co["id"])
            if cid != keep_id:
                _cancel_orphan_capiffy(cid, ticket, "duplicate match", cap_ids)

    sync_positions(state, magic, cap_positions)

    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state["mt5_count"] = len(mt5_by_ticket)
    state["tracked_count"] = len(tracked)
    state["position_count"] = len(state.get("positions", {}))
    save_state(state)
    return state


def main() -> None:
    _load_dotenv()
    level = os.environ.get("MIRROR_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    poll = _env_int("MIRROR_POLL_SEC", 5)
    _log.info(
        "MT5→Capiffy automator · poll=%ss · magic=%s · positions=%s · state=%s",
        poll,
        _env_magic() if _env_magic() is not None else "all",
        "on" if _mirror_positions() else "off",
        STATE_FILE.name,
    )

    try:
        get_valid_tokens()
        _log.info("Capiffy tokens loaded")
    except Exception as exc:
        _log.error("Capiffy auth failed: %s", exc)
        raise SystemExit(1) from exc

    from telegram_notify import enabled as tg_enabled

    if tg_enabled():
        _log.info("Telegram notify ON")
    else:
        _log.info("Telegram notify OFF (set ~/telegram.env or TELEGRAM_ENV_FILE)")

    def _stop(_sig=None, _frame=None) -> None:
        global _running
        _running = False
        _log.info("Shutting down…")

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    t = threading.Thread(target=token_refresh_loop, name="token-refresh", daemon=True)
    t.start()

    state = load_state()
    while _running:
        try:
            state = sync_once(state)
            _log.debug(
                "Sync OK · MT5 pending=%s tracked=%s",
                state.get("mt5_count"),
                state.get("tracked_count"),
            )
        except Exception as exc:
            _log.error("Sync error: %s", exc)
        for _ in range(poll):
            if not _running:
                break
            time.sleep(1)

    _log.info("Stopped")


if __name__ == "__main__":
    main()
