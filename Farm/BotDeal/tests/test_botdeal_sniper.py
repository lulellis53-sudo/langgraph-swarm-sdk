"""Offline tests for the Telegram sniper (no network, no token needed).

Run from ~/BotDeal with the lane venv:

    PYTHONPATH="$HOME/BotDeal:$HOME/Swarm-Prediction" \\
      ~/Swarm-Prediction/.venv/bin/python -m pytest tests/test_botdeal_sniper.py -q
"""

from __future__ import annotations

import datetime as dt

from Prediction.BotDeal.database import validate_record
from Prediction.BotDeal.sniper import evaluate_message, match_sku, telegram_settings

DAY = dt.date(2026, 10, 7)


def test_match_sku_finds_gpu_and_cpu() -> None:
    found = match_sku("RTX 5090 ASUS TUF à vista na Kabum!")
    assert found is not None and found[0] == "rtx-5090"
    cpu = match_sku("kit Ryzen 7 9800X3D em promoção")
    assert cpu is not None and cpu[0] == "ryzen-7-9800x3d"


def test_match_sku_ignores_unknown_products() -> None:
    assert match_sku('Monitor LG 27" barato') is None


def test_evaluate_message_catches_low_floor_deal() -> None:
    verdict = evaluate_message(
        "🔥 RTX 5090 por R$ 18.499,00 no Pix na Kabum! Link: https://kabum.com.br/x",
        today=DAY,
    )
    assert verdict is not None
    assert verdict["sku"] == "rtx-5090"
    assert verdict["price_brl"] == 18499.0
    assert verdict["verdict"] == "low"  # inside the R$18–19k target band
    validate_record(verdict["record"])  # schema-valid, ready for the Parquet store


def test_evaluate_message_exceptional_beats_target_bottom() -> None:
    verdict = evaluate_message("RTX 5090 loca, R$ 17.900,00!", today=DAY)
    assert verdict is not None and verdict["verdict"] == "exceptional"


def test_evaluate_message_ignores_out_of_range_and_unrelated() -> None:
    assert (
        evaluate_message("RTX 5090 a R$ 35.899,00", today=DAY) is not None
    )  # plausible, above range
    assert evaluate_message("Cadeira gamer R$ 899,00", today=DAY) is None
    assert evaluate_message("RTX 5090 chegou!!!", today=DAY) is None  # no price


def test_telegram_settings_defaults_are_safe() -> None:
    settings = telegram_settings()
    assert settings["enabled"] is False  # stays off until the token is stored
    assert settings["channels"] == []


def _local_sniper():
    """Load THIS lane's sniper.py, not the Prediction-lane facade copy.

    The facade package (Tools/Prediction/Prediction, a regular package) always
    shadows this lane's namespace portion, so plain imports would test stale
    facade code. Loading by file path pins the module to the product source.
    """
    import importlib.util
    import sys
    from pathlib import Path

    import Prediction.harvest  # noqa: F401  (dependency of sniper.py)

    path = Path(__file__).resolve().parents[1] / "Prediction" / "BotDeal" / "sniper.py"
    spec = importlib.util.spec_from_file_location("botdeal_local_sniper", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_sanitize_error_masks_bot_url_token() -> None:
    msg = "ConnectionError: https://api.telegram.org/bot123456:ABC-def_GHI/sendMessage"
    sanitized = _local_sniper()._sanitize_error(msg)
    assert "123456:ABC-def_GHI" not in sanitized
    assert "/bot<masked_token>/sendMessage" in sanitized


def test_sanitize_error_masks_literal_credential() -> None:
    token = "999888:zzz_secret_token"
    sanitized = _local_sniper()._sanitize_error(
        f"timeout after auth {token}", credential=token
    )
    assert token not in sanitized
    assert "<masked_token>" in sanitized


def test_post_failure_raises_sanitized_runtime_error(monkeypatch) -> None:
    import httpx
    import pytest

    sniper = _local_sniper()
    token = "111222:AAA_token_xyz"
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    def boom(*args, **kwargs):
        raise httpx.ConnectError(f"failed for {url}")

    monkeypatch.setattr(sniper.httpx, "post", boom)
    with pytest.raises(RuntimeError, match="Telegram API request failed") as excinfo:
        sniper._post(token, "sendMessage", {"chat_id": "1", "text": "hi"})
    assert token not in str(excinfo.value)
    assert excinfo.value.__cause__ is None  # from None: URL never reaches the traceback

