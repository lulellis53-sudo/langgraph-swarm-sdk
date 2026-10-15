"""Arbitrage, position sizing, and high-frequency gain algorithms for MathWorker & BotDeal.

Uses standard Python library (math, statistics) for zero-dependency execution across any node,
with optional NumPy acceleration when available.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass


@dataclass(slots=True)
class ArbitrageSignal:
    item_id: str
    target_retailer: str
    buy_price: float
    market_median: float
    expected_profit: float
    roi_percent: float
    z_score: float
    confidence: float
    action: str  # "SNIPE_BUY", "WATCH", "DISCARD"


def calculate_deal_arbitrage(
    buy_price: float,
    historical_prices: list[float],
    marketplace_fee_pct: float = 0.12,
    shipping_cost: float = 15.0,
    confidence_threshold: float = 0.85,
) -> ArbitrageSignal:
    """Calculate statistical arbitrage margin using Z-score outlier detection."""
    if not historical_prices or len(historical_prices) < 5:
        return ArbitrageSignal(
            item_id="unknown",
            target_retailer="unknown",
            buy_price=buy_price,
            market_median=buy_price,
            expected_profit=0.0,
            roi_percent=0.0,
            z_score=0.0,
            confidence=0.0,
            action="DISCARD",
        )

    prices = [float(p) for p in historical_prices]
    median_val = float(statistics.median(prices))
    std_val = float(statistics.stdev(prices)) if len(prices) > 1 else 1e-4
    if std_val < 1e-4:
        std_val = 1e-4

    z_score = (buy_price - median_val) / std_val

    # Resale proceeds net of marketplace fee and shipping
    estimated_gross_resale = median_val * 0.95  # 5% below median for rapid liquidation
    net_proceeds = estimated_gross_resale * (1.0 - marketplace_fee_pct) - shipping_cost
    net_profit = net_proceeds - buy_price
    roi_pct = (net_profit / buy_price) * 100.0 if buy_price > 0 else 0.0

    # Confidence decays as variance increases, grows as z_score drops below -2.0
    confidence = 1.0 / (1.0 + math.exp(z_score + 1.5))

    action = "DISCARD"
    if z_score <= -2.0 and roi_pct >= 25.0 and confidence >= confidence_threshold:
        action = "SNIPE_BUY"
    elif z_score <= -1.2 and roi_pct >= 15.0:
        action = "WATCH"

    return ArbitrageSignal(
        item_id="",
        target_retailer="",
        buy_price=buy_price,
        market_median=round(median_val, 2),
        expected_profit=round(net_profit, 2),
        roi_percent=round(roi_pct, 2),
        z_score=round(z_score, 3),
        confidence=round(confidence, 3),
        action=action,
    )


def optimal_kelly_bet_size(
    win_probability: float,
    win_loss_ratio: float,
    bankroll: float,
    fractional_kelly: float = 0.5,
    max_capital_cap_pct: float = 0.20,
) -> float:
    """Calculate optimal fractional Kelly Criterion position sizing to maximize capital growth."""
    if win_loss_ratio <= 0 or win_probability <= 0:
        return 0.0

    p = win_probability
    q = 1.0 - p
    b = win_loss_ratio

    # Kelly formula: f* = (b*p - q) / b
    kelly_f = (b * p - q) / b
    if kelly_f <= 0:
        return 0.0

    # Fractional Kelly (Half-Kelly) to prevent drawdown risk
    safe_fraction = min(kelly_f * fractional_kelly, max_capital_cap_pct)
    return round(bankroll * safe_fraction, 2)


def multi_channel_liquidity_split(
    total_inventory: int,
    channel_velocities: dict[str, float],
    channel_fees: dict[str, float],
) -> dict[str, int]:
    """Dynamically distribute inventory across marketplace channels to maximize net revenue."""
    channels = list(channel_velocities.keys())
    if not channels or total_inventory <= 0:
        return {}

    # Objective: Weight by (velocity / (1 + fee))
    weights = {}
    for c in channels:
        v = channel_velocities.get(c, 1.0)
        f = channel_fees.get(c, 0.10)
        weights[c] = max(v / (1.0 + f), 0.01)

    total_weight = sum(weights.values())
    allocation = {}
    allocated_units = 0

    for c in channels:
        units = int(math.floor(total_inventory * (weights[c] / total_weight)))
        allocation[c] = units
        allocated_units += units

    # Distribute remainder to highest scoring channel
    remainder = total_inventory - allocated_units
    if remainder > 0:
        best_channel = max(channels, key=lambda c: weights[c])
        allocation[best_channel] += remainder

    return allocation
