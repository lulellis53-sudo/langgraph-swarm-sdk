"""SniperSearch: small decorator-based API over the WebSearch lane.

Wraps the BotDeal harvest search stack in a configurable, registrable API:

- ``SniperSearch`` is the entry point: it holds the provider configuration
  (which search backends to use, hit limit, timeout) and an optional date
  window rendered as ``after:YYYY-MM-DD before:YYYY-MM-DD`` dork bounds.
- Functions decorated with ``@sniper.function()`` become part of the API
  registry and are callable by name via ``sniper.call("name", ...)`` or
  exposed through :meth:`SniperSearch.openapi`.
- Every search goes through :func:`Prediction.harvest.leads_for`, so the
  WebSearch lane's backends, politeness and cache apply unchanged.

Example:
    sniper = SniperSearch(backends=("ddglite", "exa"))
    sniper.window(after="2026-09-01", before="2026-09-30")

    @sniper.function()
    def b650_offers(sniper: SniperSearch, term: str) -> list[dict[str, str]]:
        return sniper.search(f'("{term}") (preco OR oferta) site:kabum.com.br')

    hits = sniper.call("b650_offers", term="B650")
"""

from __future__ import annotations

import datetime as dt
import inspect
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from repeater import normalize_url, repeater

__all__ = [
    "DorkRepeater",
    "ProviderConfig",
    "SearchAPIError",
    "SniperFunction",
    "SniperSearch",
]


class SearchAPIError(Exception):
    """Raised when the sniper API is misused or a registered call fails."""


@dataclass(slots=True)
class ProviderConfig:
    """Search provider configuration for the WebSearch lane.

    Args:
        backends: WebSearch searcher ids to fan out to (e.g. ``ddglite``,
            ``exa``). Empty tuple means "every configured provider".
        limit: Max hits per query.
        timeout_s: Overall wall-clock budget per query.
        fresh: Bypass the WebSearch cache when true.
    """

    backends: tuple[str, ...] = ("ddglite", "exa")
    limit: int = 10
    timeout_s: float = 30.0
    fresh: bool = False

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("limit must be >= 1")
        if self.timeout_s <= 0:
            raise ValueError("timeout_s must be > 0")


@dataclass(slots=True)
class SniperFunction:
    """One registered API function."""

    name: str
    fn: Callable[..., Any]
    description: str


@dataclass(slots=True)
class SniperSearch:
    """Configurable search API over the WebSearch lane.

    Args:
        providers: Provider configuration (backends, limit, timeout, fresh).
        site: Optional ``site:domain`` scoping applied to every query.
    """

    providers: ProviderConfig = field(default_factory=ProviderConfig)
    site: str | None = None
    _after: dt.date | None = field(default=None, repr=False)
    _before: dt.date | None = field(default=None, repr=False)
    _registry: dict[str, SniperFunction] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------ config

    def window(
        self,
        after: dt.date | str | None = None,
        before: dt.date | str | None = None,
    ) -> None:
        """Set the ``after:``/``before:`` dork bounds. Accepts dates or
        ``YYYY-MM-DD`` strings; ``None`` clears a bound."""
        self._after = self._coerce(after, "after")
        self._before = self._coerce(before, "before")
        if self._after and self._before and self._after > self._before:
            raise ValueError(f"after {self._after} is after before {self._before}")

    @staticmethod
    def _coerce(value: dt.date | str | None, name: str) -> dt.date | None:
        if value is None or isinstance(value, dt.date):
            return value
        try:
            return dt.date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{name} must be YYYY-MM-DD, got {value!r}") from exc

    # ------------------------------------------------------------- dork build

    def dork(self, query: str) -> str:
        """Render ``query`` with the configured site and date-window bounds."""
        parts = [f"({part.strip()})" for part in query.split(" OR ") if part.strip()] or [query]
        dorked = "(" + " OR ".join(parts) + ")"
        if self.site:
            dorked = f"{dorked} site:{self.site}"
        if self._after:
            dorked = f"{dorked} after:{self._after.isoformat()}"
        if self._before:
            dorked = f"{dorked} before:{self._before.isoformat()}"
        return dorked

    # ----------------------------------------------------------------- search

    def search(self, query: str, *, raw_dork: bool = False) -> list[dict[str, str]]:
        """Run one search and return hits as ``{url, title, snippet}`` dicts.

        Args:
            query: Search text; dork syntax (``site:``, ``OR``) is allowed.
            raw_dork: When true, skip the automatic site/window decoration.

        Backends come from the WebSearch lane's ``builtin_searchers()``:
        every configured provider when ``providers.backends`` is empty,
        otherwise only the listed ids. Providers without credentials fail
        individually and are skipped by the fan-out.
        """
        from WebSearch import builtin_searchers, load_providers
        from WebSearch.agent_tools import search_hits
        from WebSearch.frontend.websearchers import parallel_search

        table = {
            key: fn
            for key, fn in builtin_searchers().items()
            if not self.providers.backends or key in self.providers.backends
        }
        config = load_providers()
        dorked = query if raw_dork else self.dork(query)
        try:
            if self.providers.fresh:
                hits = parallel_search(
                    dorked,
                    backends=table,
                    limit=self.providers.limit,
                    config=config,
                    timeout_s=self.providers.timeout_s,
                    cache_ttl_s=0.0,
                )
            else:
                hits = search_hits(
                    dorked,
                    backends=table,
                    limit=self.providers.limit,
                    config=config,
                    timeout_s=self.providers.timeout_s,
                )
        except Exception as exc:
            raise SearchAPIError(f"search failed: {type(exc).__name__}: {exc}") from exc
        results: list[dict[str, str]] = []
        for hit in hits[: self.providers.limit]:
            if isinstance(hit, dict):
                results.append(
                    {"url": hit["url"], "title": hit["title"], "snippet": hit["snippet"]}
                )
            elif isinstance(hit, tuple):
                url, title, snippet = hit
                results.append({"url": url, "title": title, "snippet": snippet})
            else:  # WebSearch SearchHit dataclass
                results.append(
                    {"url": hit.url, "title": hit.title, "snippet": hit.snippet}
                )
        return results

    # ------------------------------------------------------------------- API

    def function(
        self,
        name: str | None = None,
        *,
        description: str = "",
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register a function in the API registry.

        The decorated function may accept ``sniper`` as its first positional
        parameter to reach back into this instance.
        """

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            key = name or fn.__name__
            if key in self._registry:
                raise SearchAPIError(f"function {key!r} already registered")
            self._registry[key] = SniperFunction(key, fn, description or fn.__doc__ or "")
            return fn

        return decorator

    def call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """Invoke a registered function by name.

        If the function's first parameter is named ``sniper``/``s`` or
        annotated as :class:`SniperSearch`, this instance is injected
        automatically.
        """
        registered = self._registry.get(name)
        if registered is None:
            raise SearchAPIError(
                f"unknown function {name!r}; registered: {sorted(self._registry)}"
            )
        call_args: tuple[Any, ...] = args
        params = inspect.signature(registered.fn).parameters
        injects_sniper = bool(params) and (
            next(iter(params)) in {"sniper", "s"}
            or params[next(iter(params))].annotation is SniperSearch
        )
        if injects_sniper and not args:
            call_args = (self,)
        try:
            return registered.fn(*call_args, **kwargs)
        except SearchAPIError:
            raise
        except Exception as exc:
            raise SearchAPIError(f"{name} failed: {type(exc).__name__}: {exc}") from exc

    def openapi(self) -> list[dict[str, str]]:
        """Describe the registered functions (name + description)."""
        return [
            {"name": item.name, "description": item.description}
            for item in self._registry.values()
        ]


if __name__ == "__main__":
    sniper = SniperSearch()
    sniper.window(after="2026-10-01", before="2026-10-11")

    @sniper.function(description="B650 motherboard offers on Kabum")
    def b650(s: SniperSearch) -> list[dict[str, str]]:
        return s.search('"placa mae b650" preco')

    for hit in sniper.call("b650"):
        print(hit["url"])


#: Default deal-intent words for the repeater (GoogleDork.MD template block 2).
DEAL_WORDS = "(CUPOM OR CODIGO OR DESCONTO OR PROMO OR %OFF OR PIX)"


@dataclass(slots=True)
class DorkRepeater:
    """Expand a dork template over products x sites x dates x deal words.

    Template placeholders (substituted verbatim, no escaping — dorks are
    operator syntax, not SQL):

    - ``@PRODUCT``  — one product name per query (from ``productnames``)
    - ``@SITE``     — one ``site:`` domain per query (from ``sites``)
    - ``@DEALWORDS``— the deal-intent block, default :data:`DEAL_WORDS`
    - ``@AFTER`` ``@BEFORE`` — ``YYYY-MM-DD`` bounds (from ``data``)

    Example:
        rep = DorkRepeater(sniper)
        for row in rep.repeat(
            '("@PRODUCT") @DEALWORDS site:@SITE after:@AFTER before:@BEFORE',
            productnames=['"rtx 5070 ti"', '"placa mae b650"'],
            sites=["kabum.com.br", "pichau.com.br"],
            data=(dt.date(2026, 10, 11), dt.date(2026, 10, 12)),
        ):
            print(row.product, row.site, len(row.hits))

    Each query retries transient network errors (``repeater.s``) and every
    yielded hit is deduplicated by canonical URL across the whole run.
    """

    sniper: SniperSearch
    deal_words: str = DEAL_WORDS
    retries: int = 2

    def repeat(
        self,
        template: str,
        *,
        productnames: list[str],
        sites: list[str],
        data: tuple[dt.date | str, dt.date | str],
        parameters: dict[str, str] | None = None,
    ) -> Iterator[DorkRow]:
        """Run the template for every product x site combination.

        Args:
            template: Dork with ``@PRODUCT``/``@SITE``/``@DEALWORDS``/
                ``@AFTER``/``@BEFORE`` placeholders (plus any custom ones
                resolved from ``parameters``).
            productnames: Product names/spellings, quoted as needed.
            sites: Bare domains; each query is scoped to one ``site:``.
            data: ``(after, before)`` dates or ``YYYY-MM-DD`` strings.
            parameters: Extra placeholder replacements (key ``X`` replaces
                ``@X``); key ``DEALWORDS`` overrides ``self.deal_words``.
        """
        after, before = (
            self.sniper._coerce(value, "data") for value in data  # noqa: SLF001
        )
        if after is None or before is None:
            raise ValueError("data must supply both after and before dates")
        extra = dict(parameters or {})
        deal_words = extra.pop("DEALWORDS", self.deal_words)
        seen: set[str] = set()
        for product in productnames:
            for site in sites:
                dork = (
                    template.replace("@PRODUCT", product)
                    .replace("@SITE", site)
                    .replace("@DEALWORDS", deal_words)
                    .replace("@AFTER", after.isoformat())
                    .replace("@BEFORE", before.isoformat())
                )
                for key, value in extra.items():
                    dork = dork.replace(f"@{key}", value)
                hits = self._search_with_retry(dork)
                fresh = []
                for hit in hits:
                    canonical = normalize_url(hit["url"])
                    if canonical in seen:
                        continue
                    seen.add(canonical)
                    fresh.append(hit)
                yield DorkRow(
                    product=product,
                    site=site,
                    dork=dork,
                    hits=fresh,
                    after=after,
                    before=before,
                )

    @repeater.s(times=2)
    def _search_with_retry(self, dork: str) -> list[dict[str, str]]:
        """One repeater query; transient errors retried, others raised.

        ``SniperSearch.search`` wraps every failure in ``SearchAPIError``, so
        the message is inspected for network-ish wording and converted to
        ``TimeoutError`` — the exception class ``repeater.s`` retries.
        """
        try:
            return self.sniper.search(dork, raw_dork=True)
        except SearchAPIError as exc:
            message = str(exc)
            if any(word in message for word in ("Timeout", "Connection", "OSError", "HTTP")):
                raise TimeoutError(message) from exc
            raise


@dataclass(slots=True)
class DorkRow:
    """Result of one repeater combination."""

    product: str
    site: str
    dork: str
    hits: list[dict[str, str]]
    after: dt.date
    before: dt.date
