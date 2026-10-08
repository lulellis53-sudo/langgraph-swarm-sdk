"""Telegram deal sniper: watch promo channels, parse BRL prices, alert on targets.

Architecture: the Bot API over plain HTTPS (no bot-framework dependency). The
bot credential resolves through the swarm vault (env -> Keychain -> ``~/.env``).
Every parsed deal becomes a schema-valid product record in the day-partitioned
Parquet and — when in the plausible range — an observation in the offers store;
messages whose floor lands inside a ``FLOOR_TARGETS`` band trigger an alert to
``telegram.alert_chat``.

Run one batch (cron-friendly; safe to re-run):

    PYTHONPATH="$HOME/BotDeal" ~/BotDeal/.venv/bin/python -m Prediction.BotDeal.sniper

Run as a continuous watcher:

    ... -m Prediction.BotDeal.sniper --watch --max-minutes 60

The getUpdates cursor is persisted beside this module, so consecutive runs
resume instead of re-reading the same backlog.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from Prediction import harvest
from Prediction.BotDeal.database import append_products
from Prediction.BotDeal.hardware import load_catalog, merged_floor_targets
from Prediction.br_hardware import floor_status, market_today

logger = logging.getLogger(__name__)

#: Bot API root. Assembled by :func:`_api_url` so the credential is passed as a
#: variable and never concatenated from literals.
_API_ROOT = "https://api.telegram.org"
#: Bot ids look like ``<digits>:<secret>``; validate before building a URL.
_BOT_ID_RE = re.compile(r"\d+:[A-Za-z0-9_\-]+")
#: Persisted getUpdates cursor so a cron run does not replay the backlog.
_OFFSET_PATH = Path(__file__).resolve().parent / ".telegram_offset"
#: Telegram rejects getUpdates timeouts above this on the Bot API.
_MAX_POLL_TIMEOUT_S = 50
#: Floor classifications worth alerting on.
_ALERT_VERDICTS = frozenset({"low", "exceptional"})


@dataclass(frozen=True, slots=True)
class SniperConfig:
    """The ``telegram:`` block, validated once per read."""

    enabled: bool = False
    poll_timeout_s: int = 30
    alert_chat: str = ""
    channels: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, data: Any) -> SniperConfig:
        """Build from the parsed YAML block, tolerating a missing or non-dict value."""
        if not isinstance(data, dict):
            data = {}
        timeout = int(data.get("poll_timeout_s", 30) or 30)
        return cls(
            enabled=bool(data.get("enabled", False)),
            # Clamp: an out-of-range timeout makes Telegram return HTTP 400.
            poll_timeout_s=max(1, min(timeout, _MAX_POLL_TIMEOUT_S)),
            alert_chat=str(data.get("alert_chat", "") or ""),
            channels=tuple(str(c) for c in (data.get("channels") or [])),
        )


@dataclass
class PollOutcome:
    """What one poll cycle did, for logging and tests."""

    deals: list[dict[str, Any]] = field(default_factory=list)
    alerts_sent: int = 0
    next_offset: int = 0
    skipped: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Serialise for the CLI summary, keeping the historical key names."""
        if self.skipped:
            return {"skipped": self.skipped}
        return {
            "deals": self.deals,
            "alerts_sent": self.alerts_sent,
            "next_offset": self.next_offset,
        }


def resolve_token() -> str:
    """Read the bot credential through the swarm vault (env -> Keychain)."""
    try:
        from swarm_sdk import vault

        return vault.get("TELEGRAM_BOT_TOKEN") or ""
    except ImportError:
        return ""


def telegram_settings() -> dict[str, Any]:
    """Read the ``telegram:`` block from ``hardware.yaml`` (defaults when absent).

    Kept as a plain dict because it is the public shape existing callers and
    tests use; :class:`SniperConfig` is the validated internal form.
    """
    import yaml as _yaml
    from Prediction.BotDeal.hardware import HARDWARE_YAML

    data = _yaml.safe_load(HARDWARE_YAML.read_text())
    block = (data or {}).get("telegram", {}) if isinstance(data, dict) else {}
    cfg = SniperConfig.from_mapping(block)
    return {
        "enabled": cfg.enabled,
        "poll_timeout_s": cfg.poll_timeout_s,
        "alert_chat": cfg.alert_chat,
        "channels": list(cfg.channels),
    }


def match_sku(text: str, *, catalog: Any | None = None) -> tuple[str, str] | None:
    """Return ``(sku, matched_term)`` for the longest catalog term named in ``text``.

    Longest-match matters: "Ryzen 7 9800X" is a substring of "9800X3D", so the
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
    text: str,
    *,
    catalog: Any | None = None,
    today: dt.date | None = None,
    message_url: str | None = None,
) -> dict[str, Any] | None:
    """Parse one promo message into a deal verdict, or ``None`` if it is not a deal.

    A message matches when it names a catalog SKU and carries a BRL price in
    that SKU's plausible range. The verdict carries the floor classification
    against ``FLOOR_TARGETS`` and the schema-valid record to store.

    Args:
        text: Raw channel message text.
        catalog: Catalog override (tests pass a fixture).
        today: Market date override.
        message_url: Real permalink when the caller knows it. The default is a
            per-day placeholder, so pass the real link to keep provenance.
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
        "url": message_url or f"https://t.me/{day.isoformat()}",
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
        "cents": cents,
        "verdict": verdict,
        "record": record,
    }


def _api_url(credential: str, method: str) -> str:
    """Build a Bot API URL, validating the credential's shape first.

    Values reach the URL only as an interpolation of a validated variable, so no
    literal secret can be assembled here.
    """
    if not credential or not _BOT_ID_RE.fullmatch(credential):
        raise ValueError("telegram credential missing or malformed")
    return f"{_API_ROOT}/bot{credential}/{method}"


def _post(
    credential: str, method: str, payload: dict[str, Any], *, timeout_s: float = 35.0
) -> dict[str, Any]:
    """Call one Bot API method over HTTPS; the host is pinned, no user URLs."""
    response = httpx.post(_api_url(credential, method), json=payload, timeout=timeout_s)
    response.raise_for_status()
    return response.json()


def send_alert(credential: str, chat_id: str, message: str) -> None:
    """Send one sniper alert to the configured chat."""
    _post(
        credential,
        "sendMessage",
        {"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
    )


# --- cursor persistence -------------------------------------------------------
# Telegram re-delivers unacknowledged updates, so a run that always sends
# offset=0 re-evaluates and re-alerts the same backlog every time.


def read_offset(path: Path | str | None = None) -> int:
    """Return the persisted update offset, or 0 when none is stored."""
    target = Path(path) if path is not None else _OFFSET_PATH
    try:
        return int(json.loads(target.read_text())["offset"])
    except OSError, ValueError, KeyError, TypeError:
        return 0


def write_offset(offset: int, path: Path | str | None = None) -> None:
    """Persist the cursor atomically so a crash cannot leave a partial file."""
    target = Path(path) if path is not None else _OFFSET_PATH
    tmp = target.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps({"offset": int(offset)}))
        tmp.replace(target)
    except OSError as exc:  # a read-only checkout must not kill the poll
        logger.warning("could not persist the Telegram cursor: %s", exc)


def next_offset(result: dict[str, Any], previous: int = 0) -> int:
    """Return the cursor to resume from: highest seen ``update_id`` + 1.

    Never moves backwards, so an empty or stale batch cannot replay old updates.
    """
    updates = result.get("result") or []
    ids = [int(u["update_id"]) for u in updates if isinstance(u, dict) and "update_id" in u]
    if not ids:
        return previous
    return max(max(ids) + 1, previous)


def _permalink(message: dict[str, Any]) -> str | None:
    """Build the real ``https://t.me/<channel>/<message_id>`` link when possible.

    Provenance matters: without it a stored deal cannot be checked by a human.
    """
    chat = message.get("chat") or {}
    username = chat.get("username")
    message_id = message.get("message_id")
    if username and message_id is not None:
        return f"https://t.me/{username}/{message_id}"
    chat_id = chat.get("id")
    if chat_id is not None and message_id is not None:
        return f"https://t.me/c/{str(chat_id).removeprefix('-100')}/{message_id}"
    return None


def poll_once(
    credential: str,
    *,
    store: bool = True,
    alert: bool = True,
    offset: int | None = None,
    persist_offset: bool = True,
) -> dict[str, Any]:
    """One getUpdates cycle: evaluate channel posts, store deals, alert on targets.

    Args:
        credential: Bot credential.
        store: Write schema-valid records to the Parquet store.
        alert: Send alerts for ``low``/``exceptional`` verdicts.
        offset: Explicit cursor; ``None`` resumes from the persisted one.
        persist_offset: Write the new cursor back to disk.

    Returns:
        Counts plus the evaluated deals, so the orchestrator can print them.
    """
    settings = SniperConfig.from_mapping(telegram_settings())
    if not settings.enabled:
        return PollOutcome(skipped="telegram disabled in hardware.yaml").as_dict()

    cursor = read_offset() if offset is None else offset
    result = _post(credential, "getUpdates", {"timeout": settings.poll_timeout_s, "offset": cursor})

    outcome = PollOutcome(next_offset=next_offset(result, cursor))
    for update in result.get("result") or []:
        if not isinstance(update, dict):
            continue
        message = update.get("channel_post") or update.get("message") or {}
        text = str(message.get("text", "") or "")
        if not text:
            continue
        verdict = evaluate_message(text, message_url=_permalink(message))
        if verdict is None:
            continue
        outcome.deals.append(verdict)
        if store:
            day = market_today()
            append_products([verdict["record"]], month=day.strftime("%B"), day=day.day)
        if alert and verdict["verdict"] in _ALERT_VERDICTS and settings.alert_chat:
            send_alert(
                credential,
                settings.alert_chat,
                f"SNIPER {verdict['verdict'].upper()}: {verdict['sku']} "
                f"R${verdict['price_brl']:,.2f}\n{text[:200]}",
            )
            outcome.alerts_sent += 1

    if persist_offset:
        write_offset(outcome.next_offset)
    return outcome.as_dict()


def watch(
    credential: str,
    *,
    max_minutes: float = 0.0,
    store: bool = True,
    alert: bool = True,
    sleep_s: float = 1.0,
) -> None:
    """Poll until ``max_minutes`` elapse (0 = forever), logging each cycle.

    Every cycle persists its cursor, so stopping and restarting loses nothing.
    """
    deadline = time.monotonic() + max_minutes * 60 if max_minutes > 0 else None
    cycles = 0
    while deadline is None or time.monotonic() < deadline:
        try:
            summary = poll_once(credential, store=store, alert=alert)
        except Exception as exc:  # a network blip must not kill the watcher
            logger.warning("poll failed: %s: %s", type(exc).__name__, exc)
        else:
            cycles += 1
            if summary.get("deals"):
                logger.info(
                    "cycle %d: %d deal(s), %d alert(s)",
                    cycles,
                    len(summary["deals"]),
                    summary.get("alerts_sent", 0),
                )
        if sleep_s > 0:
            time.sleep(sleep_s)


def _build_parser() -> argparse.ArgumentParser:
    """CLI surface for one-off and continuous runs."""
    parser = argparse.ArgumentParser(description="Telegram BR hardware deal sniper")
    parser.add_argument("--watch", action="store_true", help="poll continuously")
    parser.add_argument(
        "--max-minutes",
        type=float,
        default=0.0,
        help="with --watch, stop after this many minutes (0 = forever)",
    )
    parser.add_argument("--no-store", action="store_true", help="do not write records")
    parser.add_argument("--no-alert", action="store_true", help="do not send alerts")
    parser.add_argument(
        "--reset-offset", action="store_true", help="ignore and clear the saved cursor"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)

    credential = resolve_token()
    if not credential:
        raise SystemExit(
            "telegram credential not found: store it with `swarm-vault set TELEGRAM_BOT_TOKEN`"
        )
    if args.reset_offset:
        write_offset(0)

    if args.watch:
        watch(
            credential,
            max_minutes=args.max_minutes,
            store=not args.no_store,
            alert=not args.no_alert,
        )
        return 0

    summary = poll_once(
        credential,
        store=not args.no_store,
        alert=not args.no_alert,
        offset=0 if args.reset_offset else None,
    )
    print(json.dumps(summary, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
