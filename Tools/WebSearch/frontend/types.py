"""Data types and protocols for the WebSearch frontend."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

SearcherKind = Literal["docs", "websearcher"]
ExtractorName = Literal["selectolax", "selectolax_regex", "regex", "trafilatura", "bs4"]
CrawlerName = Literal[
    "httpx", "httpx2", "requests", "aiohttp", "curl_cffi", "scrapy", "playwright", "crawlee"
]

_EXTRACTORS: tuple[ExtractorName, ...] = (
    "selectolax",
    "selectolax_regex",
    "regex",
    "trafilatura",
    "bs4",
)
_CRAWLERS: tuple[CrawlerName, ...] = (
    "httpx",
    "httpx2",
    "requests",
    "aiohttp",
    "curl_cffi",
    "scrapy",
    "playwright",
    "crawlee",
)


@dataclass(frozen=True, slots=True)
class SearcherSpec:
    """One ``searchers:`` entry of ``providers.yaml``."""

    id: str
    kind: SearcherKind
    api_key_env: str | None = None
    engine: str | None = None
    description: str = ""
    base_url: str | None = None
    base_url_env: str | None = None
    #: ``native`` sends the dork as typed; ``translate`` maps operators to API fields.
    dork: str = "native"
    #: Extra key env names tried in order when the primary key is missing, rejected (401/403)
    #: or out of quota (429). Only ``google_search`` rotates on failure today.
    api_key_fallback_envs: tuple[str, ...] = ()
    #: Whether the searcher is active. Disabled searchers are skipped and reported as
    #: ``disabled``; they never need a key.
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class LlmSpec:
    """``llm:`` block: chat model and browsing budgets for ``--browse``."""

    model: str = ""
    max_steps: int = 12
    max_pages: int = 4
    max_chars: int = 6000


@dataclass(frozen=True, slots=True)
class CrawlSpec:
    """``crawl:`` block: limits applied while fetching search-hit URLs."""

    timeout_s: float = 20.0
    max_bytes: int = 1_048_576
    max_urls: int = 8
    schemes: tuple[str, ...] = ("http", "https")
    crawler_order: tuple[CrawlerName, ...] = _CRAWLERS


@dataclass(frozen=True, slots=True)
class PrefilterPolicy:
    """``prefilter:`` block: rules that reject hits before extraction."""

    schemes: tuple[str, ...] = ("http", "https")
    blocked_domains: tuple[str, ...] = ()
    min_snippet_chars: int = 0
    require_title: bool = True


@dataclass(frozen=True, slots=True)
class ProvidersConfig:
    """Parsed ``providers.yaml``: searchers, crawl/extract settings, model rosters."""

    version: int
    searchers: tuple[SearcherSpec, ...]
    extractor_order: tuple[ExtractorName, ...] = _EXTRACTORS
    crawl: CrawlSpec = CrawlSpec()
    prefilter: PrefilterPolicy = PrefilterPolicy()
    dork_presets: dict[str, dict[str, Any]] = None  # type: ignore[assignment]
    llm: LlmSpec = LlmSpec()
    autonomous_playwright: tuple[str, ...] = ()
    autonomous_dedupe: tuple[str, ...] = ()
    autonomous_summarize: tuple[str, ...] = ()
    autonomous_memory: tuple[str, ...] = ()
    autonomous_decision: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.dork_presets is None:
            object.__setattr__(self, "dork_presets", {})


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One search result from any provider."""

    title: str
    url: str
    snippet: str
    searcher_id: str
    #: Additional searcher ids that returned the same canonical URL.
    also_from: tuple[str, ...] = ()
    #: Per-call API token usage; zero for cache hits and free providers.
    api_tokens: int = 0
    #: The query this hit was retrieved for; set by ``agent_tools.score_hits``.
    query: str = ""
    #: Lexical relevance of this hit to ``query`` in ``[0.0, 1.0]`` (0.0 = unscored).
    relevance: float = 0.0


SearcherStatusName = Literal[
    "ok", "empty", "no_key", "unreachable", "error", "not_implemented", "disabled"
]


@dataclass(frozen=True, slots=True)
class SearcherStatus:
    """Outcome of one searcher invocation."""

    status: SearcherStatusName
    hint: str = ""


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Full result of a multi-searcher query."""

    query: str
    hits: tuple[SearchHit, ...]
    status: dict[str, SearcherStatus]
    timings_ms: dict[str, float]
    tokens: int
    pages: tuple[object, ...] = ()
    docs: tuple[object, ...] = ()


class WebSearcher(Protocol):
    """A searcher bound to its registry spec."""

    spec: SearcherSpec

    def search(self, query: str) -> Sequence[SearchHit]: ...


@dataclass(frozen=True, slots=True)
class SinkReport:
    """Outcome of one :meth:`ResultSink.store` call.

    ``detail`` is free text the sink may use to say how it ran; WebSearch never
    interprets it.
    """

    stored: int
    skipped: int = 0
    detail: str = ""


class ResultSink(Protocol):
    """Receives the final, cleaned hits (for example to index them)."""

    def store(self, hits: Sequence[SearchHit]) -> SinkReport: ...


class NullSink:
    """Sink that stores nothing."""

    def store(self, hits: Sequence[SearchHit]) -> SinkReport:
        """Return a zero-count report without persisting hits."""
        return SinkReport(stored=0)


# Callable signature for a search backend.
SearchFn = Callable[[str, "SearcherSpec"], list["SearchHit"]]
