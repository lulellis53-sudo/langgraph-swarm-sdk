"""Tests for hardware.yaml loading and the floor-target verdict.

Run from ~/BotDeal with the lane venv:

    PYTHONPATH="$HOME/BotDeal:$HOME/Swarm-Prediction" \\
      ~/Swarm-Prediction/.venv/bin/python -m pytest tests/test_botdeal_hardware.py -q
"""

from __future__ import annotations

import pytest
from Prediction.BotDeal.hardware import (
    floor_targets_cents,
    load_catalog,
    merged_floor_targets,
)
from Prediction.br_hardware import floor_status


def test_catalog_loads_from_yaml() -> None:
    catalog = load_catalog()
    skus = catalog.skus
    assert "rtx-5090" in skus
    assert {
        "ryzen-5-9600x", "ryzen-9-9950x3d2", "ryzen-7-9850x3d", "ryzen-7-9800x",
        "ddr5-2x16gb", "ddr5-1x8gb", "ddr5-2x32gb", "rtx-5060-ti",
    } <= skus
    assert any(source.name == "kabum" for source in catalog.sources)
    assert {source.name for source in catalog.sources} == {
        "kabum",
        "terabyte",
        "pichau",
        "amazon-br",
        "magalu",
        "mercadolivre",
        "casasbahia",
        "olx",
        "promobit",
        "x",
        "telegram",
    }
    assert "rtx-5090" in catalog.plausible


def test_floor_targets_convert_brl_to_cents() -> None:
    cents = floor_targets_cents({"rtx-5090": (18000.0, 19000.0)})
    assert cents == {"rtx-5090": (1_800_000, 1_900_000)}


def test_merged_floor_targets_include_yaml() -> None:
    merged = merged_floor_targets()
    assert merged.get("rtx-5090") == (1_800_000, 1_900_000)


def test_floor_status_verdicts() -> None:
    assert floor_status("rtx-5090", 1_750_000) == "exceptional"  # <= R$18k
    assert floor_status("rtx-5090", 1_850_000) == "low"  # inside R$18–19k
    assert floor_status("rtx-5090", 1_900_000) == "low"  # boundary counts as low
    assert floor_status("rtx-5090", 2_100_000) == "above"
    assert floor_status("rtx-5060", 1_000_000) == "no_target"


def test_floor_status_unknown_sku_is_no_target() -> None:
    assert floor_status("not-a-sku", 100) == "no_target"


def test_every_catalog_sku_has_plausible_range() -> None:
    catalog = load_catalog()
    missing = [product.sku for product in catalog.products if product.sku not in catalog.plausible]
    assert missing == []


@pytest.mark.parametrize(
    ("floor", "expected"),
    [(1_800_000, "exceptional"), (1_800_001, "low")],
)
def test_floor_boundary_is_bottom_inclusive(floor: int, expected: str) -> None:
    assert floor_status("rtx-5090", floor) == expected
