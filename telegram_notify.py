"""Telegram alerts for Capiffy mirror events (optional ~/telegram.env)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_loaded = False


def _expand(path: str) -> Path:
    return Path(os.path.expanduser(path)).resolve()


def load_telegram_env() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    candidates: list[Path] = []
    raw = os.environ.get("TELEGRAM_ENV_FILE", "").strip()
    if raw:
        candidates.append(_expand(raw))
    candidates.append(_expand("~/telegram.env"))
    candidates.append(Path("/home/ec2-user/telegram.env"))

    for path in candidates:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
        break


def _bot_token() -> str:
    load_telegram_env()
    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM", "TELEGAM"):
        tok = os.environ.get(key, "").strip()
        if tok:
            return tok
    return ""


def _chat_id() -> str:
    load_telegram_env()
    for key in ("TELEGRAM_CHAT_ID", "TELEGRAM_CHANNEL"):
        cid = os.environ.get(key, "").strip()
        if cid:
            return cid
    return "@cqpicopialpha"


def enabled() -> bool:
    if os.environ.get("TELEGRAM_NOTIFY", "true").lower() in ("0", "false", "no"):
        return False
    return bool(_bot_token())


def send_telegram(text: str) -> bool:
    if not enabled():
        return False
    token = _bot_token()
    chat_id = _chat_id()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": "true"}
    ).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("ok"))
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")[:300]
        print(f"telegram HTTP {exc.code}: {err}", flush=True)
        return False
    except Exception as exc:
        print(f"telegram send failed: {exc}", flush=True)
        return False


def _fmt_order_line(o: dict[str, Any], cap_sym: str, side: str, order_type: str) -> str:
    sl = o.get("sl") or 0
    tp = o.get("tp") or 0
    return (
        f"{side} {order_type} {cap_sym}\n"
        f"vol {o.get('volume')} @ {o.get('price')}\n"
        f"SL {sl if float(sl) > 0 else '—'} · TP {tp if float(tp) > 0 else '—'}"
    )


def notify_place(
    cap_id: str,
    mt5_ticket: str,
    o: dict[str, Any],
    cap_sym: str,
    side: str,
    order_type: str,
) -> None:
    send_telegram(
        "✅ Capiffy PLACE\n"
        f"Capiffy {cap_id}\n"
        f"MT5 #{mt5_ticket}\n"
        + _fmt_order_line(o, cap_sym, side, order_type)
    )


def notify_modify(
    cap_id: str,
    mt5_ticket: str,
    o: dict[str, Any],
    cap_sym: str,
    side: str,
    order_type: str,
    old_fp: list[Any],
    new_fp: list[Any],
) -> None:
    labels = ["symbol", "type", "volume", "price", "SL", "TP", "magic"]
    changes: list[str] = []
    for i, label in enumerate(labels):
        if i < len(old_fp) and i < len(new_fp) and old_fp[i] != new_fp[i]:
            changes.append(f"{label}: {old_fp[i]} → {new_fp[i]}")
    change_txt = "\n".join(changes) if changes else "order updated"
    send_telegram(
        "✏️ Capiffy MODIFY\n"
        f"Capiffy {cap_id}\n"
        f"MT5 #{mt5_ticket}\n"
        f"{side} {order_type} {cap_sym}\n"
        f"{change_txt}"
    )


def notify_removed(cap_id: str, mt5_ticket: str, reason: str = "MT5 order removed") -> None:
    send_telegram(
        "🗑 Capiffy REMOVED\n"
        f"Capiffy {cap_id}\n"
        f"MT5 #{mt5_ticket}\n"
        f"{reason}"
    )
