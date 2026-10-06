"""RTX 5000-series price-drop prediction: local verified offers + web evidence.

Data reality (2026-10-06): the harvested store (``Prediction/offers.db``, SQLite)
holds verified observations for a single day only (2026-10-05), so the
"since August" history is rebuilt from web evidence: a keyless DuckDuckGo-lite
search per GPU model, page fetch, crude text normalization, and the
``swarm_sdk.prediction`` date/number extractor build a dated price series per
model; ``weighted_linear_trend`` / ``EtsForecaster`` forecast 14 days ahead and
each forecast is judged against today's verified local floor.

Outputs (gitignored lane): ``results/rtx_forecast_<run>/`` with
``chart.png``, ``summary.csv``, and ``summary.json``. A snippet is never a
verified price: web evidence feeds the forecast, the local store stays the
ground truth for today's floor.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx

_PKG_DIR = Path(__file__).resolve().parent
DB_PATH = _PKG_DIR / "offers.db"
RESULTS_ROOT = _PKG_DIR / "results"
RUN_DIR = RESULTS_ROOT / f"rtx_forecast_{date.today().isoformat()}"
EVIDENCE_SINCE = date(2026, 8, 1)
HORIZON = 14

GPUS = (
    ("rtx-5060", "RTX 5060"),
    ("rtx-5060-ti", "RTX 5060 Ti"),
    ("rtx-5070", "RTX 5070"),
    ("rtx-5070-ti", "RTX 5070 Ti"),
    ("rtx-5080", "RTX 5080"),
    ("rtx-5090", "RTX 5090"),
)

_FETCH_TIMEOUT_S = 20.0
_SEARCH_TIMEOUT_S = 15.0
_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_ANY_TAG = re.compile(r"<[^>]+>")
_RESULT_LINK = re.compile(r"href=\"([^\"]*uddg=[^\"]+)\"")
_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}


def _local_floors() -> dict[str, dict[str, float]]:
    """Return today's verified per-GPU floor/median (BRL cents -> reais)."""
    if not DB_PATH.is_file():
        return {}
    connection = sqlite3.connect(DB_PATH)
    try:
        rows = connection.execute(
            """
            SELECT sku, MIN(amount_cents) / 100.0, AVG(amount_cents) / 100.0, COUNT(*)
            FROM price_observations
            WHERE sku LIKE 'rtx-50%' AND condition = 'new'
            GROUP BY sku
            """
        ).fetchall()
    finally:
        connection.close()
    return {
        sku: {"floor_brl": low, "median_brl": round(avg, 2), "samples": count}
        for sku, low, avg, count in rows
    }


def _strip_html(raw: str) -> str:
    """Reduce one HTML page to plain text (scripts/styles dropped, entities fixed)."""
    text = _TAG.sub(" ", raw)
    text = _ANY_TAG.sub(" ", text)
    return html_lib.unescape(text)


def _decode_ddg(href: str) -> str:
    """Decode one DuckDuckGo redirect href (protocol-relative, HTML-escaped)."""
    tail = href.split("uddg=", 1)[1]
    tail = html_lib.unescape(tail).split("&", 1)[0]
    return unquote(tail)


def search_links(client: httpx.Client, query: str, limit: int) -> list[str]:
    """Return up to ``limit`` result URLs from the keyless DuckDuckGo-lite endpoint."""
    response = client.get(
        "https://lite.duckduckgo.com/lite/",
        params={"q": query},
        timeout=_SEARCH_TIMEOUT_S,
        headers=_UA,
    )
    response.raise_for_status()
    links: list[str] = []
    for match in _RESULT_LINK.finditer(response.text):
        target = _decode_ddg(match.group(1))
        if target.startswith("http") and "duckduckgo" not in target:
            links.append(target)
        if len(links) >= limit:
            break
    return links


def _page_text(client: httpx.Client, url: str) -> str:
    """Fetch one page and return its extracted text, or ``""`` on any failure."""
    try:
        response = client.get(url, timeout=_FETCH_TIMEOUT_S, follow_redirects=True)
        response.raise_for_status()
        return _strip_html(response.text)
    except Exception:  # noqa: BLE001 - one bad page must not kill the run
        return ""


def build_tool():
    """Build a ``(query, limit) -> [(url, text), ...]`` tool for the engine."""
    def tool(query: str, *, limit: int = 6) -> list[tuple[str, str]]:
        with httpx.Client(timeout=_FETCH_TIMEOUT_S, follow_redirects=True) as client:
            documents: list[tuple[str, str]] = []
            for url in search_links(client, query, limit * 2):
                text = _page_text(client, url)
                if len(text) > 400:
                    documents.append((url, text))
                if len(documents) >= limit:
                    break
        return documents

    return tool


#: Plausible BRL band per class, used when no verified floor exists yet.
_CLASS_BANDS = {
    "RTX 5060": (1700.0, 4500.0),
    "RTX 5060 Ti": (2100.0, 5500.0),
    "RTX 5070": (3000.0, 7000.0),
    "RTX 5070 Ti": (3800.0, 9000.0),
    "RTX 5080": (4800.0, 12000.0),
    "RTX 5090": (13000.0, 35000.0),
}


def _plausible(model: str, value: float, floors: dict[str, dict[str, float]]) -> bool:
    """Accept a value only inside a window around the verified floor (or class band)."""
    floor = floors.get(_sku_of(model), {}).get("floor_brl")
    if floor:
        return 0.4 * floor <= value <= 1.9 * floor
    low, high = _CLASS_BANDS.get(model, (0.0, float("inf")))
    return low <= value <= high


def _sku_of(model: str) -> str:
    """Map the display label back to the store sku ('RTX 5070 Ti' -> 'rtx-5070-ti')."""
    return model.lower().replace(" ", "-")


def _evidence_series(
    model: str, tool, floors: dict[str, dict[str, float]]
) -> list:
    """Gather dated BRL price evidence for one GPU model since August.

    Several query variants (launch-month price, month-by-month, price-drop
    coverage) because store listing pages show only current prices; dated
    history lives in news, reviews, and deal trackers. Values outside the
    plausibility window (benchmark FPS numbers, other products) are dropped.
    """
    from swarm_sdk.prediction import EvidencePoint
    from swarm_sdk.prediction.evidence import pair_dates_numbers

    queries = (
        f"{model} preço lançamento agosto 2026 Brasil R$",
        f"{model} preço setembro 2026 R$ review",
        f"{model} queda de preço outubro 2026 R$",
    )
    points: list[EvidencePoint] = []
    for query in queries:
        for url, text in tool(query, limit=5):
            for point_date, value in pair_dates_numbers(
                text, decimal_comma=True, require_near=_model_token(model)
            ):
                if (
                    point_date >= EVIDENCE_SINCE
                    and 1500.0 <= value <= 40000.0
                    and _plausible(model, value, floors)
                ):
                    points.append(EvidencePoint(point_date, value, url, ""))
        time.sleep(0.5)
    by_date: dict[date, list[float]] = {}
    for point in points:
        by_date.setdefault(point.date, []).append(point.value)
    series: list[EvidencePoint] = []
    for point_date in sorted(by_date):
        same = sorted(by_date[point_date])
        middle = len(same) // 2
        median = same[middle] if len(same) % 2 else (same[middle - 1] + same[middle]) / 2
        series.append(EvidencePoint(point_date, median, "", ""))
    return series


def _model_token(model: str) -> tuple[str]:
    """Return the GPU's distinguishing number token ('RTX 5070 Ti' -> ('5070',))."""
    return (model.split()[1],)


def _forecast(model: str, series: list) -> dict[str, Any]:
    """Forecast one series; returns the verdict dict or a skip reason."""
    from swarm_sdk.prediction import EtsForecaster
    from swarm_sdk.prediction.forecast import weighted_linear_trend

    if len(series) < 4:
        return {"model": model, "status": "skipped", "reason": f"only {len(series)} dated points"}
    method = "weighted_linear_trend"
    steps = weighted_linear_trend(series, HORIZON)
    if len(series) >= 12:
        try:
            steps = EtsForecaster()(series, HORIZON)
            method = "ets_damped"
        except Exception:  # noqa: BLE001 - ETS is an upgrade, never a gate
            pass
    last = series[-1]
    end_value = steps[-1][1]
    if end_value < 0.3 * last.value:
        return {
            "model": model,
            "status": "unstable",
            "reason": (
                f"trend extrapolates to {end_value:.0f} BRL, under 30% of the "
                f"last evidence {last.value:.0f}; evidence too noisy to forecast"
            ),
        }
    slope_per_day = (end_value - last.value) / max((steps[-1][0] - last.date).days, 1)
    return {
        "model": model,
        "status": "forecast",
        "method": method,
        "evidence_points": len(series),
        "first_date": series[0].date.isoformat(),
        "last_date": last.date.isoformat(),
        "last_evidence_brl": round(last.value, 2),
        "horizon_days": HORIZON,
        "forecast_end_date": steps[-1][0].isoformat(),
        "forecast_end_brl": round(end_value, 2),
        "forecast_low_brl": round(steps[-1][2], 2),
        "forecast_high_brl": round(steps[-1][3], 2),
        "direction_brl_per_day": round(slope_per_day, 2),
    }


def _plot(all_series: dict[str, list], forecasts: dict[str, dict], floors: dict[str, dict]) -> Path:
    """Render the 2x3 evidence + forecast chart."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 3, figsize=(16, 8), sharex=False)
    fig.suptitle("RTX 5000-series BRL prices: web evidence since Aug + 14-day forecast")
    for axis, (sku, label) in zip(axes.flat, GPUS, strict=True):
        series = all_series.get(sku, [])
        if series:
            days = [datetime.combine(point.date, datetime.min.time()) for point in series]
            values = [point.value for point in series]
            axis.plot(days, values, "o-", ms=3, label="web evidence")
            forecast = forecasts.get(sku, {})
            if forecast.get("status") == "forecast":
                end_day = datetime.fromisoformat(forecast["forecast_end_date"])
                axis.axhline(
                    forecast["last_evidence_brl"], ls=":", c="gray", lw=0.8
                )
                axis.plot(
                    [end_day],
                    [forecast["forecast_end_brl"]],
                    "rD", ms=5, label="forecast end",
                )
                axis.errorbar(
                    [end_day],
                    [forecast["forecast_end_brl"]],
                    yerr=[
                        [forecast["forecast_end_brl"] - forecast["forecast_low_brl"]],
                        [forecast["forecast_high_brl"] - forecast["forecast_end_brl"]],
                    ],
                    fmt="none", ecolor="red", capsize=3,
                )
        floor = floors.get(sku, {}).get("floor_brl")
        if floor:
            axis.axhline(floor, ls="--", c="green", lw=1, label="verified floor (10-05)")
        axis.set_title(f"{label} (n={len(series)})", fontsize=9)
        axis.grid(alpha=0.3)
        axis.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        axis.tick_params(labelsize=7)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, fontsize=8)
    fig.tight_layout(rect=(0, 0.04, 1, 0.97))
    target = RUN_DIR / "chart.png"
    fig.savefig(target, dpi=140)
    plt.close(fig)
    return target


def main() -> int:
    """Run the full pipeline; prints the summary table and writes artifacts."""
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    floors = _local_floors()
    tool = build_tool()
    all_series: dict[str, list] = {}
    forecasts: dict[str, dict] = {}
    for sku, label in GPUS:
        series = _evidence_series(label, tool, floors)
        all_series[sku] = series
        forecast = _forecast(label, series)
        forecasts[sku] = forecast
        floor = floors.get(sku, {}).get("floor_brl")
        if forecast.get("status") == "forecast" and floor:
            forecast["verified_floor_brl"] = floor
            forecast["drop_vs_floor_pct"] = round(
                (forecast["forecast_end_brl"] - floor) / floor * 100.0, 1
            )
        print(
            f"{label:12s} points={len(series):2d} "
            f"{forecast.get('status')}: {forecast.get('forecast_end_brl', '-')} BRL "
            f"(floor {floor})",
            flush=True,
        )
        time.sleep(1.0)

    import polars as pl

    frame = pl.DataFrame(list(forecasts.values()), strict=False).sort("model")
    frame.write_csv(RUN_DIR / "summary.csv")
    chart = _plot(all_series, forecasts, floors)
    (RUN_DIR / "summary.json").write_text(
        json.dumps(
            {
                "run_date": date.today().isoformat(),
                "evidence_since": EVIDENCE_SINCE.isoformat(),
                "horizon_days": HORIZON,
                "floors_source": str(DB_PATH),
                "note": "web evidence is not a verified price; floors are",
                "forecasts": forecasts,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(frame)
    print(f"chart: {chart}")
    return 0


if __name__ == "__main__":
    repo_root = "/Users/usuario/Swarm"
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    raise SystemExit(main())
