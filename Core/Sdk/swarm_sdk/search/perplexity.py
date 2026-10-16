"""
Perplexity AI Playwright Automation Engine & SDK Tool.

Enables automated, headless web searches through Perplexity AI (https://www.perplexity.ai),
extracting synthesized text answers, rich source citations, and related follow-up queries.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from swarm_sdk.search.perplexity_parse import (
    extract_related_queries,
    extract_sources,
    normalize_result,
)

try:
    # Optional "scrape" extra, not part of the quality-gate environment.
    from playwright.async_api import (  # ty: ignore[unresolved-import]
        BrowserContext,
        Page,
        async_playwright,
    )
    from playwright.async_api import (
        Error as PlaywrightError,
    )
except ImportError:
    raise ImportError(
        "Playwright is required to use PerplexitySearchEngine. "
        "Install it via: pip install playwright && playwright install chromium"
    )

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
)

DEFAULT_STORAGE_PATH = Path.home() / ".perplexity" / "session_state.json"


class PerplexitySearchEngine:
    """
    Search engine that automates queries on Perplexity AI using Playwright.
    Handles stealth evasions, cookie consents, response streaming, source parsing,
    and follow-up extraction.
    """

    def __init__(
        self,
        headless: bool = True,
        timeout: int = 40000,
        user_agent: str = DEFAULT_USER_AGENT,
        storage_state_path: Path | str | None = None,
        session_cookie: str | None = None,
    ) -> None:
        """Configure the browser session: headless mode, timeout, user agent and credentials."""
        self.headless = headless
        self.timeout = timeout
        self.user_agent = user_agent
        self.storage_state_path = (
            Path(storage_state_path)
            if storage_state_path
            else (
                DEFAULT_STORAGE_PATH
                if DEFAULT_STORAGE_PATH.exists()
                else Path("/Users/usuario/Swarm/.perplexity_state.json")
            )
        )
        self.session_cookie = session_cookie or os.environ.get("PERPLEXITY_SESSION_COOKIE")

    async def search_async(
        self,
        query: str,
        focus: str = "web",
    ) -> dict[str, Any]:
        """
        Execute an asynchronous search on Perplexity AI.

        Args:
            query: The search query string.
            focus: Search focus mode ('web', 'academic', 'writing', 'youtube', etc.).

        Returns:
            Dict containing:
                - 'query': Original search query
                - 'url': Perplexity search results URL
                - 'answer': Full synthesized answer text
                - 'sources': List of cited sources [{'title', 'url', 'domain', 'snippet'}]
                - 'related_queries': List of suggested follow-up questions
                - 'rate_limited': True if anonymous request limit was reached
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-infobars",
                ],
            )

            # Load existing storage state if available
            storage_path_str = (
                str(self.storage_state_path)
                if self.storage_state_path and self.storage_state_path.exists()
                else None
            )

            context: BrowserContext = await browser.new_context(
                storage_state=storage_path_str,
                user_agent=self.user_agent,
                viewport={"width": 1280, "height": 900},
                locale="en-US",
                timezone_id="America/New_York",
            )

            # Inject stealth properties
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                window.chrome = { runtime: {} };
            """)

            # Add session cookie if provided
            if self.session_cookie:
                await context.add_cookies(
                    [
                        {
                            "name": "pplx.session-id",
                            "value": self.session_cookie,
                            "domain": ".perplexity.ai",
                            "path": "/",
                        }
                    ]
                )

            page: Page = await context.new_page()
            page.set_default_timeout(self.timeout)

            try:
                # 1. Navigate to Perplexity root
                await page.goto("https://www.perplexity.ai", wait_until="domcontentloaded")
                await page.wait_for_timeout(1500)

                # Check for Cloudflare challenge
                title = await page.title()
                if "Just a moment" in title or "Um momento" in title:
                    await page.wait_for_timeout(4000)

                # 2. Dismiss cookie dialog if present
                try:
                    cookie_btn = page.get_by_role(
                        "button", name=re.compile(r"Only necessary|Allow all|Accept", re.I)
                    )
                    if await cookie_btn.is_visible(timeout=2000):
                        await cookie_btn.click()
                        await page.wait_for_timeout(400)
                except PlaywrightError:
                    logger.warning("Cookie consent dialog not dismissed", exc_info=True)

                # 3. Dismiss any sign-in welcome prompt if present
                try:
                    dismiss_btn = page.get_by_role("button", name="Dismiss")
                    if await dismiss_btn.is_visible(timeout=1000):
                        await dismiss_btn.click()
                except PlaywrightError:
                    logger.warning("Sign-in welcome prompt not dismissed", exc_info=True)

                # 4. Input query into main search area (#ask-input)
                search_input = page.locator("#ask-input")
                await search_input.wait_for(state="visible", timeout=12000)
                await search_input.click()
                await page.wait_for_timeout(200)

                # Type query sequentially
                await search_input.press_sequentially(query, delay=20)
                await page.wait_for_timeout(500)

                # 5. Submit query
                try:
                    submit_btn = page.get_by_role("button", name="Submit")
                    if await submit_btn.is_visible(timeout=2000):
                        await submit_btn.click()
                    else:
                        await page.keyboard.press("Enter")
                except PlaywrightError:
                    logger.debug("Submit button not found; pressing Enter", exc_info=True)
                    await page.keyboard.press("Enter")

                # 6. Wait for result URL
                await page.wait_for_url(re.compile(r"/search/"), timeout=20000)

                # 7. Wait for answer prose container and streaming completion
                prose_locator = page.locator(".prose")
                await prose_locator.first.wait_for(state="visible", timeout=25000)

                last_text = ""
                stable_count = 0
                for _ in range(40):
                    await page.wait_for_timeout(600)
                    current_text = await prose_locator.first.inner_text()
                    if current_text and current_text == last_text and len(current_text) > 30:
                        stable_count += 1
                        if stable_count >= 3:
                            break
                    else:
                        stable_count = 0
                        last_text = current_text

                answer_text = await prose_locator.first.inner_text()
                is_rate_limited = "Sign up and repeat your request" in answer_text

                # 8. Extract related / follow-up queries
                related_queries = await extract_related_queries(page)

                # 9. Extract sources from Links tab
                sources = await extract_sources(page)

                # Save successful session state
                if not is_rate_limited and self.storage_state_path:
                    try:
                        self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
                        await context.storage_state(path=str(self.storage_state_path))
                    except OSError, PlaywrightError:
                        logger.warning(
                            "Could not save session state to %s",
                            self.storage_state_path,
                            exc_info=True,
                        )

                return normalize_result(query, page.url, answer_text, sources, related_queries)

            finally:
                await browser.close()

    def search(self, query: str, focus: str = "web") -> dict[str, Any]:
        """Synchronous wrapper for search_async."""
        return asyncio.run(self.search_async(query=query, focus=focus))


async def ask_perplexity(
    query: str,
    focus: str = "web",
    headless: bool = True,
    session_cookie: str | None = None,
) -> dict[str, Any]:
    """
    Convenience function to search Perplexity AI.

    Usage:
        result = await ask_perplexity("What are the key features introduced in Python 3.14?")
        print(result["answer"])
    """
    engine = PerplexitySearchEngine(headless=headless, session_cookie=session_cookie)
    return await engine.search_async(query=query, focus=focus)


def ask_perplexity_sync(
    query: str,
    focus: str = "web",
    headless: bool = True,
    session_cookie: str | None = None,
) -> dict[str, Any]:
    """Synchronous helper for ask_perplexity."""
    return asyncio.run(
        ask_perplexity(query=query, focus=focus, headless=headless, session_cookie=session_cookie)
    )


def cli_main() -> None:
    """CLI entrypoint for Perplexity search."""
    parser = argparse.ArgumentParser(
        description="Perplexity AI Search CLI - Query the web with Perplexity synthesis"
    )
    parser.add_argument("query", type=str, help="Search query to submit to Perplexity")
    parser.add_argument(
        "--focus", type=str, default="web", help="Search focus (web, academic, etc.)"
    )
    parser.add_argument("--json", action="store_true", help="Output raw JSON results")
    parser.add_argument("--headed", action="store_true", help="Run browser in headed mode")
    parser.add_argument(
        "--session-cookie", type=str, default=None, help="Optional pplx.session-id cookie value"
    )

    args = parser.parse_args()

    engine = PerplexitySearchEngine(
        headless=not args.headed,
        session_cookie=args.session_cookie,
    )

    try:
        result = engine.search(query=args.query, focus=args.focus)
    except Exception as exc:
        print(f"Error executing search: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    print("\n" + "=" * 70)
    print(f"🔍 PERPLEXITY SEARCH: {result['query']}")
    print(f"🔗 URL: {result['url']}")
    print("=" * 70)

    if result.get("rate_limited"):
        print("\n⚠️ Note: Anonymous rate limit encountered ('Sign up and repeat your request').")
        print(
            "To bypass: Provide PERPLEXITY_SESSION_COOKIE in environment or use --session-cookie.\n"
        )

    print(f"\n📝 ANSWER:\n{result['answer']}\n")

    sources = result.get("sources", [])
    if sources:
        print(f"📚 SOURCES ({len(sources)}):")
        for idx, src in enumerate(sources, 1):
            title = src.get("title") or src.get("domain") or "Link"
            domain = f" [{src.get('domain')}]" if src.get("domain") else ""
            print(f"  {idx}. {title}{domain}")
            print(f"     URL: {src.get('url')}")
            if src.get("snippet"):
                print(f"     Snippet: {src['snippet'][:120]}...")
        print()

    related = result.get("related_queries", [])
    if related:
        print("💡 RELATED QUESTIONS:")
        for q in related:
            print(f"  - {q}")
        print()


if __name__ == "__main__":
    cli_main()
