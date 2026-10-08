"""Load ``hardware.yaml`` into the catalog structures the pipeline expects.

The YAML is the single source of truth; ``Prediction.br_hardware`` keeps its
Python literals as the offline/test fallback. Prices in the YAML are BRL;
floor targets are converted to centavos here so ``floor_status`` compares
apples to apples.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from Prediction.br_hardware import FLOOR_TARGETS, Product, Source

__all__ = ["HARDWARE_YAML", "Catalog", "floor_targets_cents", "load_catalog"]

HARDWARE_YAML = Path(__file__).resolve().parent / "hardware.yaml"


class Catalog:
    """One parsed hardware catalog snapshot."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.version = int(data.get("version", 1))
        self.products: tuple[Product, ...] = tuple(
            Product(item["sku"], item["name"], item["category"], tuple(item["terms"]))
            for item in data["products"]
        )
        self.sources: tuple[Source, ...] = tuple(
            Source(item["name"], item["domain"], item["kind"]) for item in data["sources"]
        )
        self.floor_targets_brl: dict[str, tuple[float, float]] = {
            sku: (float(band["low"]), float(band["high"]))
            for sku, band in data.get("floor_targets", {}).items()
        }
        self.plausible: dict[str, tuple[float, float]] = {
            sku: (float(lo), float(hi)) for sku, (lo, hi) in data.get("plausible", {}).items()
        }
        self.baselines: dict[str, float | None] = {
            sku: (None if value is None else float(value))
            for sku, value in data.get("baselines", {}).items()
        }

    @property
    def skus(self) -> frozenset[str]:
        return frozenset(product.sku for product in self.products)


def floor_targets_cents(targets_brl: dict[str, tuple[float, float]]) -> dict[str, tuple[int, int]]:
    """Convert BRL floor-target bands to centavos (``br_hardware`` units)."""
    return {
        sku: (int(round(low * 100)), int(round(high * 100)))
        for sku, (low, high) in targets_brl.items()
    }


@lru_cache(maxsize=8)
def _load(path: Path, stamp: float) -> Catalog:
    del stamp  # cache key only: re-parsing happens when mtime changes
    return Catalog(yaml.safe_load(path.read_text()))


def load_catalog(path: Path | None = None) -> Catalog:
    """Parse the YAML catalog; re-parses when the file changed on disk."""
    target = path or HARDWARE_YAML
    return _load(target, target.stat().st_mtime)


def merged_floor_targets() -> dict[str, tuple[int, int]]:
    """YAML floor targets converted to centavos, merged over the Python ones."""
    merged = dict(FLOOR_TARGETS)
    merged.update(floor_targets_cents(load_catalog().floor_targets_brl))
    return merged


def summary() -> str:
    """One-line catalog summary for reports."""
    catalog = load_catalog()
    return json.dumps(
        {
            "version": catalog.version,
            "products": len(catalog.products),
            "sources": len(catalog.sources),
            "floor_targets": catalog.floor_targets_brl,
        },
        sort_keys=True,
    )
