"""Per-host crawl politeness: concurrency cap, minimum interval, and robots.txt."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from WebSearch.frontend.websearchers import shared_http_client


@dataclass
class Politeness:
    """Bounded crawl politeness.

    Args:
        min_interval_s: Minimum wall time between requests to the same host.
        max_concurrency: Maximum concurrent requests to the same host.
        respect_robots: Whether to fetch and honor ``robots.txt``.
        user_agent: User-agent string passed to ``robots.txt`` checks.
    """

    min_interval_s: float = 1.0
    max_concurrency: int = 2
    respect_robots: bool = True
    user_agent: str = "WebSearchBot"
    _host_limiters: dict[str, _HostLimiter] = field(default_factory=dict, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _robots: dict[str, RobotFileParser | None] = field(default_factory=dict, init=False)
    _robots_lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def fetch[T](
        self,
        url: str,
        getter: Callable[[str], tuple[bytes, T | None]],
    ) -> tuple[bytes, T | None]:
        """Fetch ``url`` after applying robots, concurrency, and interval limits.

        Args:
            url: Absolute http(s) URL.
            getter: Low-level fetcher returning ``(body, crawler_name)``.

        Returns:
            The getter's result.

        Raises:
            OSError: If ``robots.txt`` blocks the URL or the fetch fails.
        """
        if self.respect_robots and not self.robots_allowed(url):
            raise OSError(f"robots.txt disallows {url}")

        limiter = self._limiter_for(url)
        with limiter:
            return getter(url)

    def robots_allowed(self, url: str) -> bool:
        """Return whether ``url`` is allowed by the host's ``robots.txt``.

        A missing or unreadable ``robots.txt`` is treated as permissive so that
        transient failures do not silently drop pages.
        """
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if not host:
            return False
        robots_url = f"{parsed.scheme}://{host}/robots.txt"
        with self._robots_lock:
            parser = self._robots.get(robots_url)
            if parser is None:
                parser = self._load_robots(robots_url)
                self._robots[robots_url] = parser
        if parser is None:
            return True
        return parser.can_fetch(self.user_agent, url)

    def _load_robots(self, robots_url: str) -> RobotFileParser | None:
        try:
            response = shared_http_client().get(robots_url, timeout=2.0, follow_redirects=True)
            response.raise_for_status()
        except Exception:  # noqa: BLE001 - robots fetch failure is permissive
            return None
        try:
            lines = response.text.splitlines()
        except Exception:  # noqa: BLE001
            return None
        parser = RobotFileParser()
        parser.parse(lines)
        return parser

    def _limiter_for(self, url: str) -> _HostLimiter:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        with self._lock:
            limiter = self._host_limiters.get(host)
            if limiter is None:
                limiter = _HostLimiter(self.min_interval_s, self.max_concurrency)
                self._host_limiters[host] = limiter
            return limiter


@dataclass
class _HostLimiter:
    """One host's concurrency semaphore and minimum-interval lock."""

    min_interval_s: float
    max_concurrency: int
    _semaphore: threading.Semaphore = field(init=False)
    _lock: threading.Lock = field(init=False)
    _last_at: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        self._semaphore = threading.Semaphore(self.max_concurrency)
        self._lock = threading.Lock()

    def __enter__(self) -> _HostLimiter:
        self._semaphore.acquire()
        with self._lock:
            elapsed = time.monotonic() - self._last_at
            if elapsed < self.min_interval_s:
                time.sleep(self.min_interval_s - elapsed)
            self._last_at = time.monotonic()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._semaphore.release()


#: Module-level default used by :func:`crawl_then_scrape`.
_DEFAULT_POLITENESS = Politeness()


def polite_fetch[T](
    url: str,
    getter: Callable[[str], tuple[bytes, T | None]],
    *,
    politeness: Politeness | None = None,
) -> tuple[bytes, T | None]:
    """Fetch ``url`` through the default (or supplied) politeness layer."""
    layer = politeness if politeness is not None else _DEFAULT_POLITENESS
    return layer.fetch(url, getter)
