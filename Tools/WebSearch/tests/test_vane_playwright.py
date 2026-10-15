"""Live Playwright smoke tests: Vane (JS, no Docker) + SearXNG.

These run only against real, locally started instances; offline CI skips them.

Enable and run:
    uv sync --extra scraping && playwright install chromium
    # SearXNG: see WebSearch/configs/vane-searxng/README.md
    export SEARXNG_URL=http://127.0.0.1:8888
    # Vane (Node.js, no Docker): npm i && npm run build && npm run start
    export VANE_URL=http://127.0.0.1:3000
    uv run --no-sync python -m pytest WebSearch/tests/test_vane_playwright.py -q

Official documentation:
- Vane README (non-Docker installation):
  https://github.com/ItzCrazyKns/Vane#non-docker-installation
- Vane Search API (POST /api/search, GET /api/providers):
  https://github.com/ItzCrazyKns/Vane/blob/master/docs/API/SEARCH.md
- SearXNG Search API (GET /search, format=json):
  https://docs.searxng.org/dev/search_api.html
"""

from __future__ import annotations

import os

import httpx2
import pytest

pytest.importorskip("playwright", reason="playwright not installed (uv sync --extra scraping)")


@pytest.mark.skipif(not os.environ.get("SEARXNG_URL"), reason="SEARXNG_URL not set")
async def test_searxng_json_api_serves_format_json() -> None:
    """The instance answers the documented JSON endpoint (Search API docs).

    ``GET /search?q=...&format=json`` per
    https://docs.searxng.org/dev/search_api.html — a 403 here means the
    instance lacks ``json`` in ``search.formats`` (see vendored settings.yml).
    """
    base = os.environ["SEARXNG_URL"].rstrip("/")
    async with httpx2.AsyncClient(timeout=15.0) as client:
        response = await client.get(f"{base}/search", params={"q": "langgraph", "format": "json"})
    assert response.status_code == 200, response.text[:200]
    payload = response.json()
    assert isinstance(payload.get("results"), list)
    assert payload["results"], "SearXNG JSON returned zero results"


@pytest.mark.skipif(not os.environ.get("SEARXNG_URL"), reason="SEARXNG_URL not set")
async def test_searxng_html_search_page_renders_results() -> None:
    """Playwright opens the HTML search page and sees rendered result links."""
    from playwright.async_api import async_playwright

    base = os.environ["SEARXNG_URL"].rstrip("/")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            response = await page.goto(f"{base}/?q=langgraph", wait_until="domcontentloaded")
            assert response is not None and response.ok
            # Simple theme marks organic hits with a.url_header (SearXNG default theme).
            await page.locator("a.url_header").first.wait_for(timeout=15_000)
            assert await page.locator("a.url_header").count() >= 1
        finally:
            await browser.close()


@pytest.mark.skipif(not os.environ.get("VANE_URL"), reason="VANE_URL not set")
async def test_vane_ui_loads_search_composer() -> None:
    """Playwright opens the Vane (Next.js) UI and finds the search composer.

    Vane install docs: https://github.com/ItzCrazyKns/Vane#non-docker-installation
    — after ``npm run start`` the setup/search screen is served on port 3000.
    """
    from playwright.async_api import async_playwright

    base = os.environ["VANE_URL"].rstrip("/")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            response = await page.goto(base, wait_until="domcontentloaded")
            assert response is not None and response.ok
            # First run shows the setup form; afterwards the search composer.
            # Either way the app renders at least one text input.
            await page.locator("input, textarea").first.wait_for(timeout=30_000)
            assert await page.locator("input, textarea").count() >= 1
        finally:
            await browser.close()
