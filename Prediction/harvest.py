"""Harvest BR hardware prices through the WebSearch lane and report floors.

Searches every catalog source for each product, parses BRL prices from
result titles/snippets, stores them as snippet-level observations, rebuilds
daily floors, and prints a deal report against fixed baselines (rtx-5060
<= R$2400, rtx-5090 <= R$22000; DDR5 baselines are learned from this run's
median because no reference level was given). OLX is the used-market lane:
its observations are recorded as ``used`` and reported as a separate floor
(the new-condition floors exclude them).

Run from the lane root with its venv (WebSearch is vendored here):
    uv run --no-sync python -m Prediction.harvest
"""

from __future__ import annotations

import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
#: WebSearch is consumed from the sibling WebSearch worktree when present on PYTHONPATH.

from Prediction.br_hardware import (  # noqa: E402
    PRODUCTS,
    SOURCES,
    connect,
    import_observation,
    market_today,
    rebuild_alerts,
    rebuild_floors,
)

DB_PATH = Path(__file__).resolve().parent / "offers.db"
#: Live search mix (user-specified): Jina, Exa, Tavily are built-in HTTP
#: searchers with Keychain-resolved keys; ddglite stays as the keyless
#: fallback. "context" (non-context7) and "ddg_mcp" need backend functions
#: before they can join (providers.yaml carries their inert specs).
BACKENDS = ("tavily", "exa", "jina", "ddglite")
#: Query alias for the x.com aggregator lane (legacy host still indexed).
SITE_ALIAS = {"x": "x.com OR site:twitter.com"}
#: OLX listings are second-hand goods; every other source sells new stock.
CONDITION_BY_SOURCE = {"olx": "used"}
#: Sanity ranges in BRL; prices outside are misparsed listings.
PLAUSIBLE = {
    "rtx-5090": (8_000, 45_000),
    "rtx-5080": (5_000, 20_000),
    "rtx-5070-ti": (4_000, 10_000),
    "rtx-5070": (3_000, 7_000),
    "rtx-5060": (1_800, 4_500),
    "ddr5-16gb": (150, 2_000),
    "ddr5-32gb": (250, 4_000),
    "ddr5-64gb": (400, 8_000),
}
#: User-supplied deal baselines in BRL; None = learn from today's median.
BASELINES = {
    "rtx-5060": 2_400,
    "rtx-5090": 22_000,
    "ddr5-16gb": None,
    "ddr5-32gb": None,
    "ddr5-64gb": None,
}

_PRICE = re.compile(r"R\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d+(?:,\d{2})?)")


def parse_brl_cents(text: str) -> int | None:
    """Extract the first BRL amount as centavos, or ``None``."""
    match = _PRICE.search(text)
    if not match:
        return None
    digits = match.group(1).replace(".", "").replace(",", ".")
    try:
        return round(float(digits) * 100)
    except ValueError:
        return None


def source_for(url: str) -> str | None:
    """Map a hit URL to a catalog source name, or ``None``."""
    host = re.sub(r"^www\.", "", url.split("/")[2] if "://" in url else "", flags=re.I)
    if host in {"twitter.com", "x.com"}:
        return "x"
    for source in SOURCES:
        if host == source.domain or host.endswith("." + source.domain):
            return source.name
    return None


def leads_for(query: str) -> list[tuple[str, str, str]]:
    """Run one query through the WebSearch lane with the live backends."""
    from WebSearch import builtin_searchers, load_providers
    from WebSearch.agent_tools import search_hits

    table = {k: v for k, v in builtin_searchers().items() if k in BACKENDS}
    hits = search_hits(query, backends=table, limit=10, config=load_providers())
    return [(h.url, h.title, h.snippet) for h in hits]


def harvest_product(conn, product, day: str) -> None:
    """Search every source for one product and store snippet-price observations."""
    low, high = PLAUSIBLE[product.sku]
    terms = " OR ".join(f'"{t}"' for t in product.terms)
    for source in SOURCES:
        site = SITE_ALIAS.get(source.name, f"site:{source.domain}")
        query = f"({terms}) (preco OR oferta OR promocao) {site}"
        try:
            leads = leads_for(query)
        except Exception as exc:
            print(f"{product.sku}/{source.name}: search failed {type(exc).__name__}: {exc}")
            continue
        stored = 0
        for url, title, snippet in leads:
            if source_for(url) != source.name:
                continue
            cents = next(
                (c for c in (parse_brl_cents(t) for t in (title, snippet)) if c is not None),
                None,
            )
            if cents is None or not low * 100 <= cents <= high * 100:
                continue
            import_observation(
                conn,
                sku=product.sku,
                source=source.name,
                url=url,
                observed_on=day,
                amount_cents=cents,
                payment="card",
                condition=CONDITION_BY_SOURCE.get(source.name, "new"),
                data_origin="observed",
                evidence=f"snippet-derived price from search hit: {title[:120]}",
                verification="snippet",
            )
            stored += 1
        if not stored:
            print(f"{product.sku}/{source.name}: no snippet prices")


def _report_line(label: str, prices: list[float], baseline: float | None) -> str:
    """Format one floor/median/verdict line."""
    if not prices:
        return f"{label:<22} (no prices)"
    floor = min(prices)
    median = statistics.median(prices)
    floor_s, median_s = f"R${floor:,.2f}", f"R${median:,.2f}"
    if baseline is None:
        verdict = f"baseline learned -> deal below R${0.7 * median:,.2f}"
    elif floor <= baseline:
        verdict = f"DEAL (floor <= R${baseline:,.0f})"
    elif floor <= baseline + 400:
        verdict = "near baseline"
    else:
        verdict = f"not a deal (> R${baseline:,.0f})"
    return f"{label:<22} floor {floor_s:>12}  median {median_s:>12}  n={len(prices):<3} {verdict}"


def main() -> int:
    import swarm_sdk.vault as vault

    vault.load_into_env(
        [
            n
            for n in ("TAVILY_API_KEY", "EXA_API_KEY")
            if (vault.get_with_source(n) or (None, None))[0]
        ]
    )
    day = market_today().isoformat()
    conn = connect(DB_PATH)
    for product in PRODUCTS:
        if product.sku in PLAUSIBLE:
            harvest_product(conn, product, day)
    rebuild_floors(conn)
    rebuild_alerts(conn)

    print(f"\n=== BR price floors for {day} (snippet-derived, card prices) ===")
    for product in PRODUCTS:
        if product.sku not in PLAUSIBLE:
            continue
        new_rows = conn.execute(
            """
            SELECT amount_cents FROM price_observations
            WHERE sku = ? AND observed_on = ? AND condition = 'new'
            """,
            (product.sku, day),
        ).fetchall()
        new_prices = [int(r["amount_cents"]) / 100 for r in new_rows]
        print(_report_line(product.sku, new_prices, BASELINES.get(product.sku)))
        used_rows = conn.execute(
            """
            SELECT amount_cents FROM price_observations
            WHERE sku = ? AND observed_on = ? AND condition = 'used'
            """,
            (product.sku, day),
        ).fetchall()
        used_prices = [int(r["amount_cents"]) / 100 for r in used_rows]
        if used_prices:
            label = f"{product.sku} (OLX used)"
            print(_report_line(label, used_prices, BASELINES.get(product.sku)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
