"""
Result parsing and normalization helpers for the Perplexity search engine.

Holds the in-page JavaScript extraction snippets (related queries and cited
sources) and the async wrappers that run them against a Playwright page.
Browser-session lifecycle lives in :mod:`swarm_sdk.search.perplexity`.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    # Optional "scrape" extra, not part of the quality-gate environment.
    from playwright.async_api import (  # ty: ignore[unresolved-import]
        Error as PlaywrightError,
    )
    from playwright.async_api import (  # ty: ignore[unresolved-import]
        Page,
    )
except ImportError:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "Playwright is required to use PerplexitySearchEngine. "
        "Install it via: pip install playwright && playwright install chromium"
    )

logger = logging.getLogger(__name__)

__all__ = ["SOURCES_JS", "RELATED_QUERIES_JS", "extract_related_queries", "extract_sources"]

# JavaScript run inside the page to collect follow-up question labels.
RELATED_QUERIES_JS = """() => {
    const buttons = Array.from(document.querySelectorAll('button[aria-label]'));
    const excluded = new Set([
        'Copy', 'Share', 'Helpful', 'Not helpful', 'Fork', 'More actions',
        'Edit query', 'Copy query', 'Sign in', 'Dismiss', 'Collapse pane',
        'Expand pane', 'Collapse sidebar', 'Create project', 'Filter projects',
        'Collapse Projects', 'Collapse Sessions', 'Session actions', 'Submit',
        'Dictation', 'Model', 'Add files or tools', 'Search', 'Computer',
        'View plans', 'Scroll to end'
    ]);
    const results = [];
    for (const b of buttons) {
        const label = (b.getAttribute('aria-label') || '').trim();
        if (!label || excluded.has(label) || label.length < 5) continue;
        if (label.startsWith('Sources') || label.endsWith('sources')) continue;
        results.push(label);
    }
    return Array.from(new Set(results));
}"""

# JavaScript run inside the page to collect cited sources from anchor elements.
SOURCES_JS = """() => {
    const results = [];
    const anchors = Array.from(document.querySelectorAll('a[href]'));
    for (const a of anchors) {
        const href = a.href;
        if (!href.startsWith('http') || href.includes('perplexity.ai')
            || href.includes('cloudflare.com')) {
            continue;
        }
        const lines = a.innerText.split('\\n')
            .map(s => s.trim()).filter(Boolean);
        const domain = lines[0] || '';
        const title = lines.length > 2
            ? lines[2] : (lines[1] || lines[0] || href);
        const snippet = lines.length > 3 ? lines.slice(3).join(' ') : '';
        results.push({
            url: href,
            domain: domain,
            title: title,
            snippet: snippet
        });
    }
    return results;
}"""


async def extract_related_queries(page: Page) -> list[str]:
    """Extract related / follow-up query labels from the rendered results page."""
    try:
        related: list[str] = await page.evaluate(RELATED_QUERIES_JS)
        return related
    except PlaywrightError:
        logger.warning("Could not extract related queries from page", exc_info=True)
        return []


async def extract_sources(page: Page) -> list[dict[str, str]]:
    """Extract cited sources from the results page's Links tab."""
    sources: list[dict[str, str]] = []
    try:
        links_tab = page.get_by_role("tab", name="Links")
        if await links_tab.is_visible(timeout=3000):
            await links_tab.click()
            await page.wait_for_timeout(1000)
            sources = await page.evaluate(SOURCES_JS)
    except PlaywrightError:
        logger.warning("Could not extract sources from Links tab", exc_info=True)
    return sources


def normalize_result(
    query: str,
    page_url: str,
    answer_text: str,
    sources: list[dict[str, str]],
    related_queries: list[str],
) -> dict[str, Any]:
    """Assemble the final search-result dict with the rate-limit flag."""
    return {
        "query": query,
        "url": page_url,
        "answer": answer_text,
        "sources": sources,
        "related_queries": related_queries,
        "rate_limited": "Sign up and repeat your request" in answer_text,
    }
