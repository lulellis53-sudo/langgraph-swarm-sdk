"""
DuckDuckGo Web Search & Deep Crawler Suite for Antigravity Swarm.
Integrates:
- httpx (HTTP/2 async client with connection pooling)
- selectolax & bs4 (BeautifulSoup4 fallback DOM parsing, tables, code blocks)
- trafilatura (State-of-the-art article text extraction & readability)
- Crawlee/Scrapy-inspired asynchronous BFS/DFS crawler queue
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup
from selectolax.parser import HTMLParser

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://duckduckgo.com/",
}

TIME_RANGE_MAP = {
    "day": "d",
    "week": "w",
    "month": "m",
    "year": "y",
}


class DuckDuckGoSearcher:
    """Asynchronous search client for DuckDuckGo."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._external_client = client

    async def search(
        self,
        query: str,
        max_results: int = 10,
        time_range: str | None = None,
    ) -> list[dict[str, str]]:
        """Searches DuckDuckGo HTML endpoint and returns clean results."""
        post_data: dict[str, str] = {"q": query, "b": ""}
        if time_range and time_range.lower() in TIME_RANGE_MAP:
            post_data["df"] = TIME_RANGE_MAP[time_range.lower()]

        should_close = False
        client = self._external_client
        if client is None:
            client = httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=12.0)
            should_close = True

        try:
            response = await client.post("https://html.duckduckgo.com/html/", data=post_data)
            if response.status_code != 200:
                return []

            tree = HTMLParser(response.text)
            results: list[dict[str, str]] = []

            for node in tree.css(".result"):
                if len(results) >= max_results:
                    break

                a_tag = node.css_first(".result__title a")
                snippet_node = node.css_first(".result__snippet")
                if not a_tag:
                    continue

                raw_href = a_tag.attributes.get("href") or ""
                if "uddg=" in raw_href:
                    parsed = parse_qs(urlparse(raw_href).query)
                    clean_url = unquote(parsed.get("uddg", [raw_href])[0])
                else:
                    clean_url = raw_href

                title = a_tag.text(strip=True)
                snippet = snippet_node.text(strip=True) if snippet_node else ""

                if clean_url and title:
                    results.append(
                        {
                            "title": title,
                            "url": clean_url,
                            "snippet": snippet,
                        }
                    )

            return results
        finally:
            if should_close:
                await client.aclose()

    async def instant_answer(self, query: str) -> dict[str, Any]:
        """Queries the DuckDuckGo Instant Answer API for encyclopedic/entity data."""
        params = {
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
        }
        should_close = False
        client = self._external_client
        if client is None:
            client = httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=8.0)
            should_close = True

        try:
            response = await client.get("https://api.duckduckgo.com/", params=params)
            if response.status_code != 200:
                return {"error": f"HTTP {response.status_code}"}

            data = response.json()
            related = [
                t.get("Text")
                for t in data.get("RelatedTopics", [])
                if isinstance(t, dict) and "Text" in t
            ]

            return {
                "heading": data.get("Heading", ""),
                "abstract": data.get("AbstractText", ""),
                "abstract_source": data.get("AbstractSource", ""),
                "abstract_url": data.get("AbstractURL", ""),
                "entity": data.get("Entity", ""),
                "related_topics": related[:5],
            }
        finally:
            if should_close:
                await client.aclose()


class ContentExtractor:
    """Hybrid content extractor combining Trafilatura readability with BeautifulSoup4 fallback."""

    @staticmethod
    def extract_with_trafilatura(html: str) -> str | None:
        """Extract the main article text from ``html``; ``None`` if none found."""
        return trafilatura.extract(
            html,
            include_links=True,
            include_formatting=True,
            include_tables=True,
        )

    @staticmethod
    def extract_with_bs4(html: str) -> dict[str, Any]:
        """Fallback DOM extractor for non-article, table-heavy, or documentation pages."""
        soup = BeautifulSoup(html, "html.parser")

        # Strip script, style, navigation, and SVG elements
        for tag in soup(["script", "style", "nav", "footer", "header", "svg", "noscript"]):
            tag.decompose()

        title = soup.title.string.strip() if soup.title and soup.title.string else ""

        # Extract markdown tables if present
        tables_md = []
        for table in soup.find_all("table"):
            rows = []
            for tr in table.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if cells:
                    rows.append(" | ".join(cells))
            if rows:
                tables_md.append("\n".join(rows))

        # Extract code blocks
        code_blocks = [
            pre.get_text(strip=True) for pre in soup.find_all("pre") if pre.get_text(strip=True)
        ]

        # Extract cleaned body text
        body_text = soup.get_text(separator="\n", strip=True)
        # Collapse excessive newlines
        body_text = re.sub(r"\n{3,}", "\n\n", body_text)

        return {
            "title": title,
            "text": body_text,
            "tables": tables_md,
            "code_blocks": code_blocks[:5],
        }

    @classmethod
    def extract(cls, html: str, extract_tables: bool = True) -> dict[str, Any]:
        """Runs hybrid extraction: Trafilatura first; enriches with BS4 if sparse."""
        primary_text = cls.extract_with_trafilatura(html)
        bs4_data = cls.extract_with_bs4(html)

        if primary_text and len(primary_text.strip()) > 150:
            final_content = primary_text
            method = "trafilatura"
        else:
            final_content = bs4_data["text"]
            method = "beautifulsoup4_fallback"

        result: dict[str, Any] = {
            "title": bs4_data["title"],
            "content": final_content,
            "method": method,
        }

        if extract_tables and bs4_data["tables"]:
            result["extracted_tables"] = bs4_data["tables"]

        if bs4_data["code_blocks"]:
            result["code_snippets"] = bs4_data["code_blocks"]

        return result


class CrawleeSpider:
    """High-throughput asynchronous BFS spider modeled after Crawlee and Scrapy."""

    def __init__(
        self,
        max_depth: int = 1,
        max_pages: int = 5,
        concurrency: int = 5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.concurrency = concurrency
        self._external_client = client
        self.visited: set[str] = set()

    def _normalize_url(self, base_url: str, link: str) -> str | None:
        """Resolves relative URLs and strips anchors/tracking queries."""
        try:
            absolute = urljoin(base_url, link)
            parsed = urlparse(absolute)
            if parsed.scheme not in ("http", "https"):
                return None
            # Strip fragments and common analytics tracking
            clean = parsed._replace(fragment="").geturl()
            return clean
        except Exception:
            return None

    def _is_same_domain(self, root_domain: str, candidate_url: str) -> bool:
        """Enforces domain boundaries (Scrapy offsite middleware style)."""
        candidate_domain = urlparse(candidate_url).netloc.lower()
        root_clean = root_domain.lower().removeprefix("www.")
        candidate_clean = candidate_domain.removeprefix("www.")
        return root_clean == candidate_clean or candidate_clean.endswith("." + root_clean)

    async def crawl(
        self,
        start_urls: list[str],
        allowed_domain_only: bool = True,
        max_length: int = 8000,
    ) -> list[dict[str, Any]]:
        """Crawls starting URLs concurrently up to max_depth and max_pages."""
        queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        for u in start_urls:
            queue.put_nowait((u, 0))

        root_domains = {urlparse(u).netloc for u in start_urls if urlparse(u).netloc}
        results: list[dict[str, Any]] = []
        semaphore = asyncio.Semaphore(self.concurrency)

        should_close = False
        client = self._external_client
        if client is None:
            client = httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=12.0)
            should_close = True

        async def worker():
            while not queue.empty() and len(results) < self.max_pages:
                try:
                    url, depth = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                if url in self.visited:
                    queue.task_done()
                    continue

                self.visited.add(url)

                async with semaphore:
                    try:
                        resp = await client.get(url)
                        if resp.status_code == 200:
                            extracted = ContentExtractor.extract(resp.text)
                            content = extracted["content"]
                            if len(content) > max_length:
                                content = content[:max_length] + "\n... [truncated]"
                            extracted["content"] = content
                            extracted["url"] = url
                            extracted["depth"] = depth
                            results.append(extracted)

                            # Enqueue child links if depth allows
                            if depth < self.max_depth and len(results) < self.max_pages:
                                tree = HTMLParser(resp.text)
                                for a in tree.css("a"):
                                    href = a.attributes.get("href")
                                    if href:
                                        child_url = self._normalize_url(url, href)
                                        if child_url and child_url not in self.visited:
                                            if not allowed_domain_only or any(
                                                self._is_same_domain(d, child_url)
                                                for d in root_domains
                                            ):
                                                queue.put_nowait((child_url, depth + 1))
                    except Exception as e:
                        results.append({"url": url, "error": str(e), "depth": depth})
                    finally:
                        queue.task_done()

        try:
            tasks = [asyncio.create_task(worker()) for _ in range(self.concurrency)]
            await asyncio.gather(*tasks)
            return results
        finally:
            if should_close:
                await client.aclose()
