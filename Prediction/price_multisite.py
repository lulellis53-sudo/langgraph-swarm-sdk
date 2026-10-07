"""Multi-provider, multi-site BR hardware price scrape with a daily price table.

Sites: kabum, terabyte, pichau, magalu, amazon-br, olx. Providers for URL
discovery: DDG (keyless), Brave, Tavily, Exa, Brightdata SERP (API keys from
the macOS keychain via ``keys get``; never printed). Fetches use curl_cffi
(Chrome TLS impersonation; plain httpx fallback) because Magalu 403s and
Terabyte JS-hides prices against generic clients. Scrapy/Crawlee/Playwright
are installed as the ``scraping`` extra for later JS-heavy phases; this pass
is server-rendered only.

Prices land in ``offers.price_observations`` (verification='snippet',
data_origin='listing') and roll up into the per-day table
``daily_site_prices (day, sku, site, floor/median/n)``. A scraped listing
price is a snippet-class observation, never a verified store invoice.
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from urllib.parse import unquote

_PKG_DIR = Path(__file__).resolve().parent
DB_PATH = _PKG_DIR / "offers.db"
RESULTS_DIR = _PKG_DIR / "results" / "price_multisite"
RUN_DAY = date.today().isoformat()

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _UA, "Accept-Language": "pt-BR,pt;q=0.9"}
_PRICE = re.compile(r"R\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d+(?:,\d{2})?)")
_JSONLD_PRICE = re.compile(r'"price"\s*:\s*"?(\d[\d.,]*)"?')
_TIMEOUT_S = 25.0

SKUS: dict[str, dict[str, Any]] = {
    "rtx-5060": {"terms": "rtx 5060", "band": (1800, 4500)},
    "rtx-5060-ti": {"terms": "rtx 5060 ti", "band": (2200, 5500)},
    "rtx-5070": {"terms": "rtx 5070", "band": (3000, 7000)},
    "rtx-5070-ti": {"terms": "rtx 5070 ti", "band": (3800, 9000)},
    "rtx-5080": {"terms": "rtx 5080", "band": (4800, 12000)},
    "rtx-5090": {"terms": "rtx 5090", "band": (8000, 45000)},
    "ddr5-16gb": {"terms": "memoria ddr5 16gb", "band": (150, 2000)},
    "ddr5-32gb": {"terms": "memoria ddr5 32gb", "band": (250, 4000)},
    "ddr5-64gb": {"terms": "memoria ddr5 64gb", "band": (400, 8000)},
    "ddr4-16gb": {"terms": "memoria ddr4 16gb", "band": (120, 700)},
    "ddr4-32gb": {"terms": "memoria ddr4 32gb", "band": (200, 1000)},
    "ryzen-9600x": {"terms": "ryzen 5 9600x", "band": (1200, 2600)},
    "ryzen-9700x": {"terms": "ryzen 7 9700x", "band": (1500, 3200)},
    "ryzen-9950x": {"terms": "ryzen 9 9950x", "band": (3300, 6500)},
    "ryzen-9800x3d": {"terms": "ryzen 7 9800x3d", "band": (2600, 5200)},
    "ryzen-7600": {"terms": "ryzen 5 7600", "band": (800, 1800)},
    "ryzen-7800x3d": {"terms": "ryzen 7 7800x3d", "band": (1800, 3800)},
    "ryzen-7900x": {"terms": "ryzen 9 7900x", "band": (1700, 3600)},
}

SITES: dict[str, dict[str, str]] = {
    "kabum": {"domain": "kabum.com.br", "listing": "https://www.kabum.com.br/busca/{q}"},
    "terabyte": {"domain": "terabyteshop.com.br", "listing": "https://www.terabyteshop.com.br/busca?str={q}"},
    "pichau": {"domain": "pichau.com.br", "listing": "https://www.pichau.com.br/search?q={q}"},
    "magalu": {"domain": "magazineluiza.com.br", "listing": "https://www.magazineluiza.com.br/busca/{q}/"},
    "amazon-br": {"domain": "amazon.com.br", "listing": "https://www.amazon.com.br/s?k={q}"},
    "olx": {"domain": "olx.com.br", "listing": "https://olx.com.br/brasil?q={q}"},
}
PROVIDERS = ("ddg", "brave", "tavily", "exa", "brightdata")


def _key(name: str) -> str:
    """Read one key from the macOS keychain; never logged."""
    try:
        out = subprocess.run(
            ["keys", "get", name], capture_output=True, text=True, timeout=15, check=True
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


_KEYS = {name: "" for name in ("BRAVE_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY", "BRIGHTDATA_API_KEY")}

#: Brightdata SERP zone; the keychain holds an MCP token, not a SERP key, so
#: this provider degrades loudly when the zone rejects the token.
_BRIGHTDATA_ZONE = "serp"


def fetch(url: str) -> str:
    """Fetch one page with curl_cffi Chrome impersonation, httpx fallback."""
    try:
        from curl_cffi import requests as cffi

        response = cffi.get(url, impersonate="chrome", headers=_HEADERS, timeout=_TIMEOUT_S)
        if response.status_code == 200 and len(response.text) > 2000:
            return response.text
    except Exception:  # noqa: BLE001 - fallback below
        pass
    try:
        response = httpx.get(
            url, headers=_HEADERS, timeout=_TIMEOUT_S, follow_redirects=True
        )
        return response.text if response.status_code == 200 else ""
    except Exception:  # noqa: BLE001 - one page must not kill the run
        return ""


def _search_urls(provider: str, query: str, limit: int = 6) -> list[str]:
    """Run one discovery query on one provider; returns provider URLs (may be [])."""
    if provider == "ddg":
        text = fetch(f"https://lite.duckduckgo.com/lite/?q={query.replace(' ', '+')}")
        return [
            unquote(href.split("uddg=")[1].split("&")[0])
            for href in re.findall(r'href="([^"]*uddg=[^"]+)"', text)
        ][:limit]
    if provider == "brave":
        if not _KEYS["BRAVE_API_KEY"]:
            return []
        response = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": limit},
            headers={"X-Subscription-Token": _KEYS["BRAVE_API_KEY"], "Accept": "application/json"},
            timeout=_TIMEOUT_S,
        )
        return [item["url"] for item in response.json().get("web", {}).get("results", [])][:limit]
    if provider == "tavily":
        if not _KEYS["TAVILY_API_KEY"]:
            return []
        response = httpx.post(
            "https://api.tavily.com/search",
            json={"api_key": _KEYS["TAVILY_API_KEY"], "query": query, "max_results": limit},
            timeout=_TIMEOUT_S,
        )
        return [item["url"] for item in response.json().get("results", [])][:limit]
    if provider == "exa":
        if not _KEYS["EXA_API_KEY"]:
            return []
        response = httpx.post(
            "https://api.exa.ai/search",
            json={"query": query, "numResults": limit, "type": "neural"},
            headers={"x-api-key": _KEYS["EXA_API_KEY"], "Content-Type": "application/json"},
            timeout=_TIMEOUT_S,
        )
        return [item["url"] for item in response.json().get("results", [])][:limit]
    if provider == "brightdata":
        if not _KEYS["BRIGHTDATA_API_KEY"]:
            return []
        response = httpx.post(
            "https://api.brightdata.com/serp/req",
            headers={"Authorization": f"Bearer {_KEYS['BRIGHTDATA_API_KEY']}"},
            json={"zone": "serp", "body": {"q": query}},
            timeout=45.0,
        )
        organic = response.json().get("organic", [])
        return [item.get("link", "") for item in organic][:limit]
    return []


def parse_brl_cents(token: str) -> int | None:
    """Parse one BRL token to centavos."""
    digits = token.replace(".", "").replace(",", ".")
    try:
        return round(float(digits) * 100)
    except ValueError:
        return None


def extract_prices(html: str, terms: str, band: tuple[int, int]) -> list[int]:
    """Return in-band BRL centavos from JSON-LD first, then R$ near the terms."""
    prices: list[int] = []
    for match in _JSONLD_PRICE.finditer(html):
        cents = parse_brl_cents(match.group(1))
        if cents is not None and band[0] * 100 <= cents <= band[1] * 100:
            prices.append(cents)
    if prices:
        return prices
    tokens = [token for token in terms.lower().split() if len(token) > 2]
    for match in _PRICE.finditer(html):
        start = max(0, match.start() - 250)
        context = html[start : match.end() + 100].lower()
        if not any(token in context for token in tokens):
            continue
        cents = parse_brl_cents(match.group(1))
        if cents is not None and band[0] * 100 <= cents <= band[1] * 100:
            prices.append(cents)
    return prices


def scrape_sku_site(sku: str, site: str, provider_log: dict[str, int]) -> list[dict[str, Any]]:
    """Scrape one SKU on one site: listing page first, providers only if thin."""
    spec = SKUS[sku]
    domain = SITES[site]["domain"]
    query = f"site:{domain} {spec['terms']}"
    joiner = "-" if site == "kabum" else "+"
    listing = SITES[site]["listing"].format(q=spec["terms"].replace(" ", joiner))
    urls = [listing]
    seen: set[str] = set()
    offers: list[dict[str, Any]] = []
    for url in [listing]:
        seen.add(url)
        html = fetch(url)
        if html:
            for cents in extract_prices(html, spec["terms"], spec["band"]):
                offers.append({"sku": sku, "site": site, "url": url, "amount_cents": cents})
        time.sleep(0.4)
    if len(offers) >= 3:
        return offers
    for provider in PROVIDERS:
        try:
            found = _search_urls(provider, query)
            provider_log[provider] += len(found)
            urls.extend(url for url in found if domain in url and url not in seen)
        except Exception:  # noqa: BLE001 - provider failure degrades coverage
            continue
        time.sleep(0.2)
    for url in urls[1:6]:
        if url in seen:
            continue
        seen.add(url)
        html = fetch(url)
        if not html:
            continue
        for cents in extract_prices(html, spec["terms"], spec["band"]):
            offers.append({"sku": sku, "site": site, "url": url, "amount_cents": cents})
        time.sleep(0.4)
        if len(offers) >= 8:
            break
    return offers


def ensure_daily_table(connection: sqlite3.Connection) -> None:
    """Create the per-day per-site price table when absent."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_site_prices (
            market_date TEXT NOT NULL,
            sku TEXT NOT NULL,
            site TEXT NOT NULL,
            payment TEXT NOT NULL,
            floor_cents INTEGER NOT NULL,
            median_cents INTEGER NOT NULL,
            n INTEGER NOT NULL,
            data_origin TEXT NOT NULL,
            PRIMARY KEY (market_date, sku, site, payment, data_origin)
        )
        """
    )


def store(offers: list[dict[str, Any]]) -> None:
    """Insert observations and refresh the per-day per-site rollup."""
    connection = sqlite3.connect(DB_PATH)
    ensure_daily_table(connection)
    today = RUN_DAY
    for offer in offers:
        connection.execute(
            """
            INSERT OR IGNORE INTO price_observations
            (sku, source, url, observed_on, amount_cents, currency, payment,
             condition, verification, data_origin, evidence)
            VALUES (?, ?, ?, ?, ?, 'BRL', 'card', 'new', 'snippet', 'listing', ?)
            """,
            (
                offer["sku"],
                offer["site"],
                offer["url"],
                today,
                offer["amount_cents"],
                f"listing scrape {today}",
            ),
        )
    connection.execute(
        "DELETE FROM daily_site_prices WHERE market_date = ? AND data_origin = 'listing'",
        (today,),
    )
    connection.execute(
        """
        INSERT INTO daily_site_prices
            (market_date, sku, site, payment, floor_cents, median_cents, n, data_origin)
        SELECT observed_on, sku, source, payment,
               MIN(amount_cents),
               CAST(AVG(amount_cents) AS INTEGER),
               COUNT(*), 'listing'
        FROM price_observations
        WHERE observed_on = ? AND data_origin = 'listing'
        GROUP BY observed_on, sku, source, payment
        """,
        (today,),
    )
    connection.commit()
    connection.close()


def main() -> int:
    """Scrape every SKU x site, store, and print the daily per-site floor table."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    for name in _KEYS:
        _KEYS[name] = _key(name)
    if not _KEYS["BRIGHTDATA_API_KEY"]:
        _KEYS["BRIGHTDATA_API_KEY"] = _key("BRIGHTDATA_MCP_TOKEN")
    import polars as pl

    all_offers: list[dict[str, Any]] = []
    provider_log = {provider: 0 for provider in PROVIDERS}
    for sku in SKUS:
        for site in SITES:
            offers = scrape_sku_site(sku, site, provider_log)
            all_offers.extend(offers)
            print(f"{sku:14s} {site:10s} offers={len(offers)}", flush=True)
        time.sleep(0.5)
    store(all_offers)
    frame = pl.DataFrame(all_offers)
    frame.write_csv(RESULTS_DIR / f"offers_{RUN_DAY}.csv")
    print("\nprovider url discovery:", provider_log)
    summary = (
        frame.group_by(["site", "sku"])
        .agg(
            pl.col("amount_cents").min().alias("floor_cents"),
            pl.col("amount_cents").median().alias("median_cents"),
            pl.len().alias("n"),
        )
        .sort(["site", "sku"])
    )
    summary.write_csv(RESULTS_DIR / f"summary_{RUN_DAY}.csv")
    with pl.Config(tbl_rows=40, tbl_cols=8, fmt_str_lengths=40):
        print(summary.with_columns(
            (pl.col("floor_cents") / 100).round(2).alias("floor_brl"),
            (pl.col("median_cents") / 100).round(2).alias("median_brl"),
        ).drop("median_cents"))
    print(f"\nartifacts: {RESULTS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
