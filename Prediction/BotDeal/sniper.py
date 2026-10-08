"""Telegram deal sniper: watch promo channels, parse BRL prices, alert on targets.

Architecture: the Bot API over plain HTTPS (no bot-framework dependency).
``TELEGRAM_BOT_TOKEN`` resolves through the swarm vault (env → Keychain →
~/.env); the bot must be admin of the channels it sniffs, or you run a user
session via MTProto later. Every parsed deal becomes a schema-valid product
record in the day-partitioned Parquet and — when in the plausible range — an
observation in the offers store; messages whose floor lands inside a
``FLOOR_TARGETS`` band trigger an alert to ``telegram.alert_chat``.

Run from ~/BotDeal with the lane venv:

    PYTHONPATH="$HOME/BotDeal:$HOME/Swarm-Prediction" \\
      ~/Swarm-Prediction/.venv/bin/python -m Prediction.BotDeal.sniper
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

import httpx
from Prediction import harvest
from Prediction.BotDeal.database import append_products
from Prediction.BotDeal.hardware import load_catalog, merged_floor_targets
from Prediction.br_hardware import floor_status, market_today

API_BASE = "https://api.telegram.org/bot{token}/{method}"
_ALLOWED_HOSTS = {"api.telegram.org"}


def resolve_token() -> str:
    """Read TELEGRAM_BOT_TOKEN through the swarm vault (env → Keychain)."""
    try:
        from swarm_sdk import vault

        return vault.get("TELEGRAM_BOT_TOKEN") or ""
    except ImportError:
        return ""


def match_sku(text: str, *, catalog: Any | None = None) -> tuple[str, str] | None:
    """Return ``(sku, matched_term)`` for the longest catalog term named in ``text``.

    Longest-match matters: "Ryzen 7 9800X" is a substring of "9800X3D", and the
    more specific model must win.
    """
    haystack = text.lower()
    best: tuple[str, str] | None = None
    for product in (catalog or load_catalog()).products:
        for term in product.terms:
            if term.lower() in haystack and (best is None or len(term) > len(best[1])):
                best = product.sku, term
    return best


def evaluate_message(
    text: str, *, catalog: Any | None = None, today: dt.date | None = None
) -> dict[str, Any] | None:
    """Parse one promo message into a deal verdict, or ``None`` if it is not a deal.

    A message matches when it names a catalog SKU and carries a BRL price in
    that SKU's plausible range. The verdict carries the floor classification
    against ``FLOOR_TARGETS`` and the schema-valid record to store.
    """
    catalog = catalog or load_catalog()
    match_info = match_sku(text, catalog=catalog)
    if match_info is None:
        return None
    sku, term = match_info
    cents = harvest.parse_brl_cents(text)
    if cents is None:
        return None
    plausible = catalog.plausible.get(sku)
    if plausible and not plausible[0] * 100 <= cents <= plausible[1] * 100:
        return None
    day = today or market_today()
    price = cents / 100
    targets = merged_floor_targets()
    verdict = floor_status(sku, cents) if sku in targets else "no_target"
    record = {
        "unique_id": sku,
        "name": text[:200],
        "source": "telegram",
        "url": f"https://t.me/{day.isoformat()}",
        "observed_at": day.isoformat(),
        "price": price,
        "currency": "BRL",
        "condition": "new",
        "snippet": text[:500],
        "query": f"telegram:{term}",
        "confidence": None,
    }
    return {
        "sku": sku,
        "term": term,
        "price_brl": price,
        "verdict": verdict,
        "record": record,
    }


def _post(
    token: str, method: str, payload: dict[str, Any], *, timeout_s: float = 35.0
) -> dict[str, Any]:
    """Call one Bot API method over HTTPS; the host is pinned, no user URLs."""
    if not token or not re.fullmatch(r"\d+:[A-Za-z0-9_\-]+", token):
        raise ValueError("TELEGRAM_BOT_TOKEN missing or malformed")
    response = httpx.post(
        API_BASE.format(token=token, method=method),
        json=payload,
        timeout=timeout_s,
    )
    response.raise_for_status()
    return response.json()


def send_alert(token: str, chat_id: str, message: str) -> None:
    """Send one sniper alert to the configured chat."""
    _post(
        token,
        "sendMessage",
        {"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
    )


def poll_once(
    token: str, *, store: bool = True, alert: bool = True, offset: int = 0
) -> dict[str, Any]:
    """One getUpdates cycle: evaluate channel posts, store deals, alert on targets.

    Returns counts plus the evaluated deals so the orchestrator can print them.
    """
    settings = telegram_settings()
    if not settings["enabled"]:
        return {"skipped": "telegram disabled in hardware.yaml"}
    result = _post(
        token, "getUpdates", {"timeout": int(settings["poll_timeout_s"]), "offset": offset}
    )
    deals: list[dict[str, Any]] = []
    alerts_sent = 0
    for update in result.get("result", []):
        message = update.get("channel_post") or update.get("message") or {}
        text = str(message.get("text", "") or "")
        if not text:
            continue
        verdict = evaluate_message(text)
        if verdict is None:
            continue
        deals.append(verdict)
        if store:
            day = dt.date.today()
            append_products([verdict["record"]], month=day.strftime("%B"), day=day.day)
        if alert and verdict["verdict"] in {"low", "exceptional"} and settings["alert_chat"]:
            alert_text = (
                f"SNIPER {verdict['verdict'].upper()}: "
                f"{verdict['sku']} R${verdict['price_brl']:,.2f}\n{text[:200]}"
            )
            send_alert(token, settings["alert_chat"], alert_text)
            alerts_sent += 1
    return {"deals": deals, "alerts_sent": alerts_sent, "next_offset": _next_offset(result)}


def _next_offset(result: dict[str, Any]) -> int:
    updates = result.get("result", [])
    return max((int(update["update_id"]) + 1 for update in updates), default=0)


def telegram_settings() -> dict[str, Any]:
    """Read the ``telegram:`` block from ``hardware.yaml`` (defaults when absent)."""
    import yaml as _yaml
    from Prediction.BotDeal.hardware import HARDWARE_YAML

    data = _yaml.safe_load(HARDWARE_YAML.read_text()).get("telegram", {})
    return {
        "enabled": bool(data.get("enabled", False)),
        "poll_timeout_s": int(data.get("poll_timeout_s", 30)),
        "alert_chat": str(data.get("alert_chat", "")),
        "channels": list(data.get("channels", [])),
    }


if __name__ == "__main__":
    token = resolve_token()
    if not token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN not found: store it with `swarm-vault set TELEGRAM_BOT_TOKEN`"
        )
    summary = poll_once(token)
    print(summary)
