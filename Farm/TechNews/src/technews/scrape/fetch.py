"""Guarded HTTP fetcher: robots.txt, per-host rate limiting, transient retries."""

import time
from collections.abc import Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "TechNewsBot/0.1 (+https://github.com/dantenho)"

_TIMEOUT_S = 15.0
#: 429 plus 5xx are retried; every other non-2xx fails immediately.
_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})
_SCHEMES = ("http", "https")


class FetchError(Exception):
    """A fetch failed: bad URL, non-2xx status after retries, or transport error."""


class RobotsDisallowed(FetchError):
    """The target URL is disallowed by the site's robots.txt rules."""


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """Return a client with the pipeline defaults: 15 s timeout, bot UA, redirects."""
    return httpx.Client(
        transport=transport,
        timeout=_TIMEOUT_S,
        headers={"user-agent": USER_AGENT},
        follow_redirects=True,
    )


class Fetcher:
    """Polite fetcher: one robots.txt per run, per-host rate limit, transient retries.

    robots.txt is fetched once per Fetcher run and reused for every host, so a
    run that already checked robots never waits or re-fetches for a new host
    (each source is expected to use its own Fetcher). The rate limiter counts
    every request a host sees, robots.txt included.
    """

    def __init__(
        self,
        client: httpx.Client,
        *,
        min_interval: float = 1.0,
        retries: int = 2,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Configure a fetcher over an existing client.

        Args:
            client: HTTP client to issue requests with (tests inject a mock transport).
            min_interval: Minimum seconds between two requests to the same host.
            retries: Extra attempts after a transient (429/5xx/transport) failure.
            clock: Monotonic clock source, injectable for deterministic tests.
            sleep: Blocking sleep used to honour ``min_interval`` and backoff.
        """
        self._client = client
        self._min_interval = min_interval
        self._retries = retries
        self._clock = clock
        self._sleep = sleep
        self._last_request: dict[str, float] = {}
        self._robots: RobotFileParser | None = None
        self._robots_fetched = False

    def get(self, url: str) -> httpx.Response:
        """Fetch ``url`` and return the 2xx response.

        Raises RobotsDisallowed when robots.txt forbids the URL, FetchError for a
        non-http(s) scheme, a non-2xx status (after retries on 429/5xx), or a
        transport error (after retries).
        """
        parts = urlsplit(url)
        if parts.scheme not in _SCHEMES:
            raise FetchError(f"unsupported URL scheme {parts.scheme!r}: {url}")
        robots = self._robots_rules(parts)
        if not robots.can_fetch(USER_AGENT, url):
            raise RobotsDisallowed(url)
        return self._get_with_retries(url)

    def get_bytes(self, url: str) -> bytes:
        """Fetch ``url`` and return the response body as bytes."""
        return self.get(url).content

    def _robots_rules(self, parts: object) -> RobotFileParser:
        """Return the run-level robots rules, fetching them on first use.

        Status 200 parses the rules, 4xx allows everything, and a 5xx or a
        transport error disallows everything (fail closed); the outcome is
        cached for the run either way.
        """
        if self._robots_fetched:
            assert self._robots is not None
            return self._robots
        self._robots_fetched = True
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        parser = RobotFileParser()
        try:
            self._throttle(parts.netloc)
            response = self._client.get(robots_url)
            if response.status_code == 200:
                parser.parse(response.text.splitlines())
            elif response.status_code >= 500:
                parser.disallow_all = True
            else:
                # 4xx: no robots file, so everything is allowed.
                parser.allow_all = True
        except httpx.HTTPError:
            parser.disallow_all = True
        self._robots = parser
        return parser

    def _get_with_retries(self, url: str) -> httpx.Response:
        """GET ``url``, retrying transport errors and 429/5xx responses."""
        attempts = self._retries + 1
        for attempt in range(1, attempts + 1):
            self._throttle(urlsplit(url).netloc)
            try:
                response = self._client.get(url)
            except httpx.TransportError as exc:
                if attempt == attempts:
                    raise FetchError(f"GET {url} failed after {attempts} attempts: {exc}") from exc
                continue
            if response.status_code in _TRANSIENT_STATUSES and attempt < attempts:
                continue
            if response.is_success:
                return response
            raise FetchError(f"GET {url} failed with HTTP {response.status_code}")
        raise FetchError(f"GET {url} failed after {attempts} attempts")

    def _throttle(self, host: str) -> None:
        """Sleep until ``min_interval`` has passed since the last request to ``host``."""
        now = self._clock()
        last = self._last_request.get(host)
        if last is not None:
            wait = self._min_interval - (now - last)
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
        self._last_request[host] = now
