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
