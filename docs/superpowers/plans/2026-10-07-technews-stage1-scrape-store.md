# TechNews Stage 1 — Sources, Store, Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect headlines and short excerpts from 30 Big Tech companies, git repos, hardware, code and AI sources into a deduplicated SQLite store, with a `technews` CLI to verify sources and run a scrape.

**Architecture:** A standalone uv project `TechNews/` (own `pyproject.toml`, own lock) holding package `technews`. A guarded `Fetcher` (timeout, robots.txt, per-host rate limit, transient retries) feeds three collectors (RSS/Atom, Hacker News API, web-search fallback) that all return `Article` values; `Store` upserts them into SQLite. Later stages (predict, newsletter, humanize, site) read only the store.

**Tech Stack:** Python >=3.14.8, httpx (sync, `MockTransport` in tests), feedparser 6, selectolax, PyYAML, SQLite (stdlib), argparse, pytest.

**Spec:** `docs/superpowers/specs/2026-10-07-technews-design.md` (amended by this plan, see "Spec amendments").

## Spec amendments (decided while planning, from evidence)

1. **Location is `TechNews/` (top-level standalone project), not `src/technews/`.** Measured: `uv run` at the repo root fails to resolve (`onnxruntime-openvino` has no cp314 wheel, pulled by the `embed` extra), and `.venv` lacks pytest. A standalone project resolves cleanly (`uv pip compile` of its deps on 3.14 succeeded) and does not touch the root `pyproject.toml` or `uv.lock`. This matches the repo's existing top-level packages (`Prediction/`, `Main/`).
2. **No `github.py`.** GitHub release feeds (`https://github.com/<owner>/<repo>/releases.atom`) are plain Atom, handled by the feed collector.
3. **No `jinja2` yet.** It is needed only in stage 5 and is added then.
4. **Web-search fallback** is an injected `SearchFn`. The default lazily imports `swarm_sdk.search.duckduckgo` and raises `SearchUnavailable` when the root project is not importable (it is not, inside the standalone env, unless on `PYTHONPATH`).

## Global Constraints

- Python `>=3.14.8`; `from __future__ import annotations` is NOT used (lazy annotations on 3.14); built-in generics and `X | None`.
- Ruff: line length 100, rules `E,F,I,UP`, double quotes.
- Fetcher: timeout on every request (15 s), honest User-Agent `TechNewsBot/0.1`, robots.txt honored, per-host rate limit (default 1.0 s), retries only on transient errors (transport errors, HTTP 429/500/502/503/504), no login or paywall bypass.
- Excerpt: at most 300 characters, plain text, never full article text.
- Dedupe by canonical URL and by content hash.
- No secrets in code or YAML. No `print` in library code (CLI output only in `cli.py`); `logger = logging.getLogger(__name__)`.
- Nothing is sent or published; the CLI only fetches and writes the local SQLite file.

## Review Focus

1. A feed entry missing `link`, `title` or any date: skipped (no link/title) or stored with `published=None`; never an exception. (Task 5)
2. Excerpt edge cases: exactly 300 chars, 301 chars, HTML entities, emoji/non-ASCII, empty input. (Task 1)
3. robots.txt answers 5xx or is unreachable: treat as disallowed; 404 means allowed. (Task 4)
4. Same story under `HTTP://Example.com/a/?utm_source=x#frag` and `https://example.com/a`: one row. (Tasks 1, 3)
5. One source raising (network error, bad XML, deleted HN item `null`) must not stop the others, and the report must say which failed and why. (Tasks 5, 6)

## File Structure

```
TechNews/
  pyproject.toml            project, deps, ruff, pytest, script entry
  .gitignore                data/, .venv/, .ruff_cache/, .pytest_cache/
  sources.yaml              source registry (30 Big Tech + git + hardware + code + AI)
  src/technews/
    __init__.py             version only
    __main__.py             python -m technews
    models.py               Source, Article, Category
    text.py                 canonical_url, make_excerpt, content_hash
    sources.py              load_sources(path) -> list[Source]
    store.py                Store (SQLite upsert/query)
    scrape/
      __init__.py           collect_articles, scrape_all, check_source, reports
      fetch.py              Fetcher, FetchError, RobotsDisallowed, make_client
      feeds.py              parse_feed
      hn.py                 collect_hn
      search.py             SearchFn, SearchUnavailable, default_search, collect_search
    cli.py                  `technews sources check | scrape`
  tests/
    conftest.py             fixtures path helper
    fixtures/sample.rss, sample.atom
    test_text.py test_sources.py test_store.py test_fetch.py
    test_feeds.py test_hn.py test_search.py test_scrape.py test_cli.py
```

---

### Task 1: Project scaffold, models, text helpers

**Files:**
- Create: `TechNews/pyproject.toml`, `TechNews/.gitignore`, `TechNews/src/technews/__init__.py`, `TechNews/src/technews/__main__.py`, `TechNews/src/technews/models.py`, `TechNews/src/technews/text.py`
- Test: `TechNews/tests/test_text.py`

**Interfaces:**
- Produces:
  - `models.Category = Literal["bigtech", "git", "hardware", "code", "ai"]`
  - `models.SourceKind = Literal["feed", "hn", "search"]`
  - `models.Source(name: str, category: Category, kind: SourceKind, url: str | None = None, query: str | None = None, enabled: bool = True, limit: int = 20)` (frozen dataclass, slots). `url` is the feed URL for `feed`; `query` is the search string for `search`; `hn` uses neither.
  - `models.Article(url: str, source: str, category: Category, title: str, published: str | None, excerpt: str, tags: tuple[str, ...] = ())` (frozen dataclass, slots). `published` is ISO 8601 UTC like `2026-10-07T12:00:00+00:00`.
  - `text.canonical_url(url: str) -> str`, `text.make_excerpt(raw: str, limit: int = 300) -> str`, `text.content_hash(title: str, excerpt: str) -> str`

- [ ] **Step 1: Create the project files**

`TechNews/pyproject.toml`:

```toml
[project]
name = "technews"
version = "0.1.0"
description = "TechNews pipeline: scrape, store, predict, newsletter, humanize, site."
requires-python = ">=3.14.8"
dependencies = [
    "feedparser>=6.0",
    "httpx>=0.28",
    "selectolax>=0.3",
    "pyyaml>=6.0",
]

[dependency-groups]
dev = ["pytest>=8", "ruff>=0.8"]

[project.scripts]
technews = "technews.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/technews"]

[tool.ruff]
line-length = 100
target-version = "py314"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]

[tool.ruff.format]
quote-style = "double"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`TechNews/.gitignore`:

```
data/
.venv/
.ruff_cache/
.pytest_cache/
__pycache__/
```

`TechNews/src/technews/__init__.py`:

```python
"""TechNews pipeline: scrape, store, predict, newsletter, humanize, site."""

__version__ = "0.1.0"
```

`TechNews/src/technews/__main__.py`:

```python
"""Run the CLI with ``python -m technews``."""

from technews.cli import main

raise SystemExit(main())
```

`TechNews/src/technews/models.py`:

```python
"""Value objects shared by every stage."""

from dataclasses import dataclass
from typing import Literal

type Category = Literal["bigtech", "git", "hardware", "code", "ai"]
type SourceKind = Literal["feed", "hn", "search"]

CATEGORIES: tuple[str, ...] = ("bigtech", "git", "hardware", "code", "ai")
SOURCE_KINDS: tuple[str, ...] = ("feed", "hn", "search")


@dataclass(frozen=True, slots=True)
class Source:
    """One configured news source."""

    name: str
    category: Category
    kind: SourceKind
    url: str | None = None
    query: str | None = None
    enabled: bool = True
    limit: int = 20


@dataclass(frozen=True, slots=True)
class Article:
    """One collected headline; ``published`` is ISO 8601 UTC or None."""

    url: str
    source: str
    category: Category
    title: str
    published: str | None
    excerpt: str
    tags: tuple[str, ...] = ()
```

- [ ] **Step 2: Write the failing tests**

`TechNews/tests/test_text.py`:

```python
import pytest

from technews.text import canonical_url, content_hash, make_excerpt


def test_canonical_url_strips_tracking_fragment_slash_and_case():
    messy = "HTTP://Example.COM/a/?utm_source=x&id=7&utm_medium=y#frag"
    assert canonical_url(messy) == "http://example.com/a?id=7"


def test_canonical_url_same_story_two_spellings_match():
    a = canonical_url("HTTP://Example.com/a/?utm_source=x#frag")
    b = canonical_url("http://example.com/a")
    assert a == b


def test_canonical_url_keeps_root_path():
    assert canonical_url("https://example.com/") == "https://example.com/"


def test_canonical_url_sorts_query_keys():
    assert canonical_url("https://e.com/p?b=2&a=1") == "https://e.com/p?a=1&b=2"


def test_excerpt_strips_html_and_entities():
    assert make_excerpt("<p>Fish &amp; <b>chips</b></p>") == "Fish & chips"


def test_excerpt_collapses_whitespace():
    assert make_excerpt("a \n\n  b\t c") == "a b c"


def test_excerpt_empty():
    assert make_excerpt("") == ""


def test_excerpt_exactly_limit_is_untouched():
    text = "x" * 300
    assert make_excerpt(text) == text


def test_excerpt_over_limit_truncated_at_word_with_ellipsis():
    text = ("word " * 100).strip()  # 499 chars
    out = make_excerpt(text)
    assert len(out) <= 300
    assert out.endswith("…")
    assert not out[:-1].endswith(" ")


def test_excerpt_301_chars_no_spaces_hard_cut():
    out = make_excerpt("y" * 301)
    assert len(out) == 300
    assert out.endswith("…")


def test_excerpt_non_ascii_and_emoji_counted_as_characters():
    text = "ação 🚀 " * 100
    out = make_excerpt(text)
    assert len(out) <= 300
    assert "🚀" in out


def test_content_hash_stable_and_sensitive():
    assert content_hash("T", "e") == content_hash("T", "e")
    assert content_hash("T", "e") != content_hash("T", "f")


@pytest.mark.parametrize("raw", ["<script>alert(1)</script>hi", "<style>p{}</style>hi"])
def test_excerpt_drops_script_and_style_content(raw):
    assert make_excerpt(raw) == "hi"
```

- [ ] **Step 3: Sync env and run tests to verify they fail**

Run: `cd TechNews && uv sync && uv run pytest tests/test_text.py -q --tb=short`
Expected: `uv sync` succeeds; pytest FAILS with `ModuleNotFoundError: No module named 'technews.text'` (or ImportError for the names).

- [ ] **Step 4: Write the implementation**

`TechNews/src/technews/text.py`:

```python
"""Pure text helpers: URL canonicalization, excerpts, hashing."""

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from selectolax.parser import HTMLParser

EXCERPT_LIMIT = 300
_ELLIPSIS = "…"
_WS = re.compile(r"\s+")


def canonical_url(url: str) -> str:
    """Return a stable form of ``url`` for deduplication.

    Lowercases scheme and host, drops the fragment and ``utm_*`` parameters, sorts the
    remaining query keys and removes a trailing slash from non-root paths.
    """
    parts = urlsplit(url.strip())
    query = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_")
    )
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def make_excerpt(raw: str, limit: int = EXCERPT_LIMIT) -> str:
    """Return plain text from ``raw`` HTML, at most ``limit`` characters.

    Truncation happens at a word boundary when one exists, and ends with an ellipsis.
    """
    if not raw:
        return ""
    tree = HTMLParser(raw)
    for node in tree.css("script, style"):
        node.decompose()
    text = _WS.sub(" ", tree.text(separator=" ")).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > 0:
        cut = cut[:space]
    return cut.rstrip() + _ELLIPSIS


def content_hash(title: str, excerpt: str) -> str:
    """Return a SHA-256 hex digest of the normalized title and excerpt."""
    norm = _WS.sub(" ", f"{title}\n{excerpt}").strip().lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()
```

- [ ] **Step 5: Run tests and lint**

Run: `cd TechNews && uv run pytest tests/test_text.py -q --tb=short && uv run ruff format src tests && uv run ruff check src tests`
Expected: all tests PASS; ruff clean. If `test_excerpt_strips_html_and_entities` fails because selectolax joins text without the expected spacing (`"Fish & chips"`), fix `make_excerpt` (the `" ".join` of text nodes plus the whitespace collapse already normalizes it); do not change the test.

- [ ] **Step 6: Commit**

```bash
git add TechNews/pyproject.toml TechNews/uv.lock TechNews/.gitignore TechNews/src TechNews/tests
git commit -m "feat(technews): scaffold standalone project, models, text helpers"
```

---

### Task 2: Source registry

**Files:**
- Create: `TechNews/src/technews/sources.py`, `TechNews/sources.yaml`
- Test: `TechNews/tests/test_sources.py`

**Interfaces:**
- Consumes: `models.Source`, `models.CATEGORIES`, `models.SOURCE_KINDS`.
- Produces: `sources.SourceConfigError(Exception)`, `sources.load_sources(path: Path) -> list[Source]` (returns every entry, enabled or not; raises `SourceConfigError` with the entry name and reason).

- [ ] **Step 1: Write the failing tests**

`TechNews/tests/test_sources.py`:

```python
from pathlib import Path

import pytest

from technews.sources import SourceConfigError, load_sources


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "sources.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_loads_all_kinds(tmp_path):
    path = write(
        tmp_path,
        """
sources:
  - {name: A, category: ai, kind: feed, url: "https://a.example/feed"}
  - {name: HN, category: code, kind: hn, limit: 5}
  - {name: Apple, category: bigtech, kind: search, query: "site:apple.com/newsroom"}
  - {name: Off, category: ai, kind: feed, url: "https://o.example/f", enabled: false}
""",
    )
    got = load_sources(path)
    assert [s.name for s in got] == ["A", "HN", "Apple", "Off"]
    assert got[1].limit == 5
    assert got[3].enabled is False
    assert got[0].url == "https://a.example/feed"


def test_empty_file_is_error(tmp_path):
    with pytest.raises(SourceConfigError, match="no sources"):
        load_sources(write(tmp_path, ""))


def test_empty_list_is_error(tmp_path):
    with pytest.raises(SourceConfigError, match="no sources"):
        load_sources(write(tmp_path, "sources: []"))


def test_unknown_category_names_the_entry(tmp_path):
    path = write(tmp_path, "sources:\n  - {name: X, category: sports, kind: hn}\n")
    with pytest.raises(SourceConfigError, match="X.*category"):
        load_sources(path)


def test_feed_requires_url(tmp_path):
    path = write(tmp_path, "sources:\n  - {name: X, category: ai, kind: feed}\n")
    with pytest.raises(SourceConfigError, match="X.*url"):
        load_sources(path)


def test_search_requires_query(tmp_path):
    path = write(tmp_path, "sources:\n  - {name: X, category: ai, kind: search}\n")
    with pytest.raises(SourceConfigError, match="X.*query"):
        load_sources(path)


def test_duplicate_names_rejected(tmp_path):
    path = write(
        tmp_path,
        "sources:\n  - {name: X, category: ai, kind: hn}\n  - {name: X, category: ai, kind: hn}\n",
    )
    with pytest.raises(SourceConfigError, match="duplicate.*X"):
        load_sources(path)


def test_non_http_feed_url_rejected(tmp_path):
    path = write(tmp_path, "sources:\n  - {name: X, category: ai, kind: feed, url: 'file:///etc/passwd'}\n")
    with pytest.raises(SourceConfigError, match="X.*http"):
        load_sources(path)


def test_shipped_registry_is_valid_and_covers_every_category():
    shipped = Path(__file__).parent.parent / "sources.yaml"
    got = load_sources(shipped)
    assert {s.category for s in got} == {"bigtech", "git", "hardware", "code", "ai"}
    assert sum(1 for s in got if s.category == "bigtech") >= 30
```

- [ ] **Step 2: Run to verify failure**

Run: `cd TechNews && uv run pytest tests/test_sources.py -q --tb=short`
Expected: FAIL with `ModuleNotFoundError: No module named 'technews.sources'`.

- [ ] **Step 3: Implement the loader**

`TechNews/src/technews/sources.py`:

```python
"""Load and validate the source registry (``sources.yaml``)."""

from pathlib import Path

import yaml

from technews.models import CATEGORIES, SOURCE_KINDS, Source


class SourceConfigError(Exception):
    """The source registry is missing, malformed or inconsistent."""


def load_sources(path: Path) -> list[Source]:
    """Return every source in ``path`` (enabled or not), validated.

    Raises:
        SourceConfigError: with the entry name and reason on any invalid entry.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as err:
        raise SourceConfigError(f"cannot read {path}: {err}") from err
    entries = (data or {}).get("sources") if isinstance(data, dict) or data is None else None
    if not entries:
        raise SourceConfigError(f"no sources in {path}")
    out: list[Source] = []
    seen: set[str] = set()
    for raw in entries:
        source = _parse_entry(raw)
        if source.name in seen:
            raise SourceConfigError(f"duplicate source name: {source.name}")
        seen.add(source.name)
        out.append(source)
    return out


def _parse_entry(raw: object) -> Source:
    if not isinstance(raw, dict) or not raw.get("name"):
        raise SourceConfigError(f"source entry needs a name: {raw!r}")
    name = str(raw["name"])
    category, kind = raw.get("category"), raw.get("kind")
    if category not in CATEGORIES:
        raise SourceConfigError(f"{name}: bad category {category!r}, expected one of {CATEGORIES}")
    if kind not in SOURCE_KINDS:
        raise SourceConfigError(f"{name}: bad kind {kind!r}, expected one of {SOURCE_KINDS}")
    url, query = raw.get("url"), raw.get("query")
    if kind == "feed":
        if not url:
            raise SourceConfigError(f"{name}: kind feed requires url")
        if not str(url).startswith(("http://", "https://")):
            raise SourceConfigError(f"{name}: url must be http(s): {url}")
    if kind == "search" and not query:
        raise SourceConfigError(f"{name}: kind search requires query")
    return Source(
        name=name,
        category=category,
        kind=kind,
        url=url,
        query=query,
        enabled=bool(raw.get("enabled", True)),
        limit=int(raw.get("limit", 20)),
    )
```

- [ ] **Step 4: Write `TechNews/sources.yaml`**

Every entry is a *candidate*; Task 6 runs `technews sources check` and the engineer disables dead ones. Feed URLs below come from memory and are unverified until then. Entries with only a `query` are the Big Tech fallback (the `site:` path is the newsroom domain and also unverified).

```yaml
# Source registry. Every URL/query is a candidate until `technews sources check` passes.
# Set `enabled: false` for dead entries; do not delete them.
sources:
  # --- Big Tech (30). Feed where one is expected, otherwise site: web-search fallback.
  - {name: Apple, category: bigtech, kind: search, query: "site:apple.com/newsroom"}
  - {name: Microsoft, category: bigtech, kind: feed, url: "https://blogs.microsoft.com/feed/"}
  - {name: Google, category: bigtech, kind: feed, url: "https://blog.google/rss/"}
  - {name: Amazon, category: bigtech, kind: feed, url: "https://aws.amazon.com/blogs/aws/feed/"}
  - {name: Meta, category: bigtech, kind: feed, url: "https://engineering.fb.com/feed/"}
  - {name: Nvidia, category: bigtech, kind: feed, url: "https://blogs.nvidia.com/feed/"}
  - {name: Tesla, category: bigtech, kind: search, query: "site:tesla.com/blog"}
  - {name: Netflix, category: bigtech, kind: feed, url: "https://netflixtechblog.com/feed"}
  - {name: Oracle, category: bigtech, kind: search, query: "site:oracle.com/news"}
  - {name: IBM, category: bigtech, kind: search, query: "site:newsroom.ibm.com"}
  - {name: Intel, category: bigtech, kind: search, query: "site:intel.com newsroom"}
  - {name: AMD, category: bigtech, kind: search, query: "site:amd.com newsroom"}
  - {name: Qualcomm, category: bigtech, kind: search, query: "site:qualcomm.com/news"}
  - {name: Broadcom, category: bigtech, kind: search, query: "site:broadcom.com/company/news"}
  - {name: Cisco, category: bigtech, kind: search, query: "site:newsroom.cisco.com"}
  - {name: Salesforce, category: bigtech, kind: search, query: "site:salesforce.com/news"}
  - {name: Adobe, category: bigtech, kind: search, query: "site:blog.adobe.com"}
  - {name: SAP, category: bigtech, kind: search, query: "site:news.sap.com"}
  - {name: Samsung, category: bigtech, kind: search, query: "site:news.samsung.com"}
  - {name: Sony, category: bigtech, kind: search, query: "site:sony.com/en/SonyInfo/News"}
  - {name: TSMC, category: bigtech, kind: search, query: "site:pr.tsmc.com"}
  - {name: ASML, category: bigtech, kind: search, query: "site:asml.com/en/news"}
  - {name: OpenAI, category: bigtech, kind: feed, url: "https://openai.com/news/rss.xml"}
  - {name: Anthropic, category: bigtech, kind: search, query: "site:anthropic.com/news"}
  - {name: Cloudflare, category: bigtech, kind: feed, url: "https://blog.cloudflare.com/rss/"}
  - {name: Stripe, category: bigtech, kind: search, query: "site:stripe.com/blog"}
  - {name: GitHub, category: bigtech, kind: feed, url: "https://github.blog/feed/"}
  - {name: GitLab, category: bigtech, kind: search, query: "site:about.gitlab.com/blog"}
  - {name: Mozilla, category: bigtech, kind: feed, url: "https://blog.mozilla.org/feed/"}
  - {name: Red Hat, category: bigtech, kind: search, query: "site:redhat.com/en/blog"}
  # --- Git repos: releases Atom feeds (watchlist; edit freely)
  - {name: "git:python/cpython", category: git, kind: feed, url: "https://github.com/python/cpython/releases.atom"}
  - {name: "git:rust-lang/rust", category: git, kind: feed, url: "https://github.com/rust-lang/rust/releases.atom"}
  - {name: "git:llvm/llvm-project", category: git, kind: feed, url: "https://github.com/llvm/llvm-project/releases.atom"}
  - {name: "git:torvalds/linux", category: git, kind: feed, url: "https://github.com/torvalds/linux/tags.atom"}
  - {name: "git:ggml-org/llama.cpp", category: git, kind: feed, url: "https://github.com/ggml-org/llama.cpp/releases.atom"}
  - {name: "git:astral-sh/uv", category: git, kind: feed, url: "https://github.com/astral-sh/uv/releases.atom"}
  # --- Hardware news
  - {name: Tom's Hardware, category: hardware, kind: feed, url: "https://www.tomshardware.com/feeds/all"}
  - {name: ServeTheHome, category: hardware, kind: feed, url: "https://www.servethehome.com/feed/"}
  - {name: Phoronix, category: hardware, kind: feed, url: "https://www.phoronix.com/rss.php"}
  # --- Code news
  - {name: Hacker News, category: code, kind: hn, limit: 20}
  - {name: LWN, category: code, kind: feed, url: "https://lwn.net/headlines/rss"}
  - {name: Rust Blog, category: code, kind: feed, url: "https://blog.rust-lang.org/feed.xml"}
  # --- AI news
  - {name: Hugging Face Blog, category: ai, kind: feed, url: "https://huggingface.co/blog/feed.xml"}
  - {name: arXiv cs.AI, category: ai, kind: feed, url: "https://export.arxiv.org/rss/cs.AI"}
  - {name: Google DeepMind, category: ai, kind: feed, url: "https://deepmind.google/blog/rss.xml"}
```

- [ ] **Step 5: Run tests and lint**

Run: `cd TechNews && uv run pytest tests/test_sources.py -q --tb=short && uv run ruff format src tests && uv run ruff check src tests`
Expected: all PASS (shipped registry has 30 bigtech entries and every category), ruff clean.

- [ ] **Step 6: Commit**

```bash
git add TechNews/src/technews/sources.py TechNews/sources.yaml TechNews/tests/test_sources.py
git commit -m "feat(technews): source registry with 30 Big Tech and category sources"
```

---

### Task 3: SQLite store

**Files:**
- Create: `TechNews/src/technews/store.py`
- Test: `TechNews/tests/test_store.py`

**Interfaces:**
- Consumes: `models.Article`, `text.canonical_url`, `text.content_hash`.
- Produces: `store.Store(path: Path | str)` with `.add(article: Article) -> bool` (True if a new row was inserted), `.add_many(articles: Iterable[Article]) -> int` (count inserted), `.recent(limit: int = 50, category: str | None = None) -> list[Article]` (newest first, `published` descending with NULLs last then insertion order), `.count() -> int`, `.close()`, and context-manager support. Stored `url` is the canonical form.

- [ ] **Step 1: Write the failing tests**

`TechNews/tests/test_store.py`:

```python
import sqlite3

from technews.models import Article
from technews.store import Store


def art(url="https://e.com/a", title="T", excerpt="E", published="2026-10-07T00:00:00+00:00",
        category="ai", source="S", tags=()):
    return Article(url=url, source=source, category=category, title=title,
                   published=published, excerpt=excerpt, tags=tags)


def test_add_new_then_duplicate(tmp_path):
    with Store(tmp_path / "t.db") as store:
        assert store.add(art()) is True
        assert store.add(art()) is False
        assert store.count() == 1


def test_same_story_two_url_spellings_is_one_row(tmp_path):
    with Store(tmp_path / "t.db") as store:
        assert store.add(art(url="HTTP://Example.com/a/?utm_source=x#frag", title="X")) is True
        assert store.add(art(url="http://example.com/a", title="Y")) is False
        assert store.count() == 1
        assert store.recent()[0].url == "http://example.com/a"


def test_syndicated_copy_with_same_title_and_excerpt_is_one_row(tmp_path):
    with Store(tmp_path / "t.db") as store:
        assert store.add(art(url="https://a.com/1", title="Same", excerpt="Same")) is True
        assert store.add(art(url="https://b.com/2", title="Same", excerpt="Same")) is False


def test_add_many_returns_inserted_count(tmp_path):
    with Store(tmp_path / "t.db") as store:
        n = store.add_many([art(url="https://e.com/1", title="1"), art(url="https://e.com/2", title="2"),
                            art(url="https://e.com/1", title="1")])
        assert n == 2


def test_recent_orders_newest_first_nulls_last_and_filters_category(tmp_path):
    with Store(tmp_path / "t.db") as store:
        store.add(art(url="https://e.com/old", title="old", published="2026-10-01T00:00:00+00:00"))
        store.add(art(url="https://e.com/new", title="new", published="2026-10-05T00:00:00+00:00"))
        store.add(art(url="https://e.com/none", title="none", published=None))
        store.add(art(url="https://e.com/hw", title="hw", category="hardware",
                      published="2026-10-06T00:00:00+00:00"))
        assert [a.title for a in store.recent()] == ["hw", "new", "old", "none"]
        assert [a.title for a in store.recent(category="ai")] == ["new", "old", "none"]
        assert len(store.recent(limit=2)) == 2


def test_roundtrip_preserves_tags_and_unicode(tmp_path):
    with Store(tmp_path / "t.db") as store:
        store.add(art(title="Ação 🚀", tags=("gpu", "ia")))
        got = store.recent()[0]
        assert got.title == "Ação 🚀"
        assert got.tags == ("gpu", "ia")


def test_persists_across_reopen(tmp_path):
    path = tmp_path / "t.db"
    with Store(path) as store:
        store.add(art())
    with Store(path) as store:
        assert store.count() == 1


def test_creates_parent_directory(tmp_path):
    with Store(tmp_path / "nested" / "dir" / "t.db") as store:
        assert store.count() == 0


def test_uses_parameterized_queries_for_hostile_title(tmp_path):
    with Store(tmp_path / "t.db") as store:
        store.add(art(title="x'); DROP TABLE articles;--"))
        assert store.count() == 1
    conn = sqlite3.connect(tmp_path / "t.db")
    assert conn.execute("select count(*) from articles").fetchone()[0] == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `cd TechNews && uv run pytest tests/test_store.py -q --tb=short`
Expected: FAIL with `ModuleNotFoundError: No module named 'technews.store'`.

- [ ] **Step 3: Implement**

`TechNews/src/technews/store.py`:

```python
"""SQLite store: the only interface between pipeline stages."""

import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Self

from technews.models import Article
from technews.text import canonical_url, content_hash

_SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    published TEXT,
    excerpt TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    tags TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published);
CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category);
"""

_TAG_SEP = "\x1f"


class Store:
    """Deduplicating article store backed by one SQLite file."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.executescript(_SCHEMA)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the connection."""
        self._conn.close()

    def add(self, article: Article) -> bool:
        """Insert ``article``; return False when its URL or content already exists."""
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO articles "
            "(url, source, category, title, published, excerpt, content_hash, tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                canonical_url(article.url),
                article.source,
                article.category,
                article.title,
                article.published,
                article.excerpt,
                content_hash(article.title, article.excerpt),
                _TAG_SEP.join(article.tags),
            ),
        )
        self._conn.commit()
        return cur.rowcount == 1

    def add_many(self, articles: Iterable[Article]) -> int:
        """Insert each article; return how many were new."""
        return sum(1 for article in articles if self.add(article))

    def count(self) -> int:
        """Return the number of stored articles."""
        return self._conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]

    def recent(self, limit: int = 50, category: str | None = None) -> list[Article]:
        """Return articles newest first (undated last), optionally for one category."""
        sql = "SELECT url, source, category, title, published, excerpt, tags FROM articles"
        args: list[object] = []
        if category is not None:
            sql += " WHERE category = ?"
            args.append(category)
        sql += " ORDER BY published IS NULL, published DESC, id DESC LIMIT ?"
        args.append(limit)
        rows = self._conn.execute(sql, args).fetchall()
        return [
            Article(
                url=url,
                source=source,
                category=cat,
                title=title,
                published=published,
                excerpt=excerpt,
                tags=tuple(t for t in tags.split(_TAG_SEP) if t),
            )
            for url, source, cat, title, published, excerpt, tags in rows
        ]
```

- [ ] **Step 4: Run tests and lint**

Run: `cd TechNews && uv run pytest tests/test_store.py -q --tb=short && uv run ruff format src tests && uv run ruff check src tests`
Expected: all PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add TechNews/src/technews/store.py TechNews/tests/test_store.py
git commit -m "feat(technews): deduplicating SQLite article store"
```

---

### Task 4: Guarded fetcher

**Files:**
- Create: `TechNews/src/technews/scrape/__init__.py` (empty docstring-only for now), `TechNews/src/technews/scrape/fetch.py`
- Test: `TechNews/tests/test_fetch.py`

**Interfaces:**
- Produces:
  - `fetch.USER_AGENT = "TechNewsBot/0.1 (+https://github.com/dantenho)"`
  - `fetch.FetchError(Exception)`, `fetch.RobotsDisallowed(FetchError)`
  - `fetch.make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client` (timeout 15 s, UA header, follow redirects)
  - `fetch.Fetcher(client: httpx.Client, *, min_interval: float = 1.0, retries: int = 2, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep)` with `.get(url: str) -> httpx.Response` (raises `RobotsDisallowed`, or `FetchError` on non-2xx after retries / transport failure) and `.get_bytes(url) -> bytes` helper.
  - robots.txt rules: fetched once per host (`scheme://host/robots.txt`); status 200 → parse; 4xx → allow all; 5xx or transport error → disallow all (cached for the run).

- [ ] **Step 1: Write the failing tests**

`TechNews/tests/test_fetch.py`:

```python
import httpx
import pytest

from technews.scrape.fetch import USER_AGENT, FetchError, Fetcher, RobotsDisallowed, make_client


class Clock:
    def __init__(self):
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def build(handler, **kw):
    clock = Clock()
    client = make_client(httpx.MockTransport(handler))
    return Fetcher(client, clock=clock, sleep=clock.sleep, **kw), clock


def ok_robots(request, body="User-agent: *\nAllow: /\n"):
    return httpx.Response(200, text=body)


def test_get_returns_body_and_sends_user_agent():
    seen = {}

    def handler(request):
        if request.url.path == "/robots.txt":
            return ok_robots(request)
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, text="hello")

    fetcher, _ = build(handler)
    assert fetcher.get("https://a.example/x").text == "hello"
    assert seen["ua"] == USER_AGENT


def test_robots_disallow_blocks_without_fetching_target():
    hits = []

    def handler(request):
        hits.append(request.url.path)
        if request.url.path == "/robots.txt":
            return ok_robots(request, "User-agent: *\nDisallow: /private\n")
        return httpx.Response(200, text="secret")

    fetcher, _ = build(handler)
    with pytest.raises(RobotsDisallowed):
        fetcher.get("https://a.example/private/x")
    assert "/private/x" not in hits


def test_robots_404_means_allowed():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text="ok")

    fetcher, _ = build(handler)
    assert fetcher.get("https://a.example/x").text == "ok"


@pytest.mark.parametrize("status", [500, 503])
def test_robots_5xx_means_disallowed(status):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(status)
        return httpx.Response(200, text="ok")

    fetcher, _ = build(handler)
    with pytest.raises(RobotsDisallowed):
        fetcher.get("https://a.example/x")


def test_robots_unreachable_means_disallowed():
    def handler(request):
        if request.url.path == "/robots.txt":
            raise httpx.ConnectError("down")
        return httpx.Response(200, text="ok")

    fetcher, _ = build(handler)
    with pytest.raises(RobotsDisallowed):
        fetcher.get("https://a.example/x")


def test_robots_fetched_once_per_host():
    calls = {"robots": 0}

    def handler(request):
        if request.url.path == "/robots.txt":
            calls["robots"] += 1
            return ok_robots(request)
        return httpx.Response(200, text="ok")

    fetcher, _ = build(handler)
    fetcher.get("https://a.example/1")
    fetcher.get("https://a.example/2")
    assert calls["robots"] == 1


def test_rate_limit_waits_between_requests_to_same_host_only():
    def handler(request):
        if request.url.path == "/robots.txt":
            return ok_robots(request)
        return httpx.Response(200, text="ok")

    fetcher, clock = build(handler, min_interval=1.0)
    fetcher.get("https://a.example/1")
    fetcher.get("https://a.example/2")
    # robots.txt (t=0) + first target (waits 1.0) + second target (waits 1.0) = 2.0
    assert sum(clock.slept) == pytest.approx(2.0)
    clock.slept.clear()
    fetcher.get("https://b.example/1")
    assert sum(clock.slept) == 0


def test_retries_transient_status_then_succeeds():
    state = {"n": 0}

    def handler(request):
        if request.url.path == "/robots.txt":
            return ok_robots(request)
        state["n"] += 1
        return httpx.Response(503) if state["n"] < 3 else httpx.Response(200, text="ok")

    fetcher, _ = build(handler, retries=2)
    assert fetcher.get("https://a.example/x").text == "ok"
    assert state["n"] == 3


def test_gives_up_after_retries_with_fetch_error():
    def handler(request):
        if request.url.path == "/robots.txt":
            return ok_robots(request)
        return httpx.Response(503)

    fetcher, _ = build(handler, retries=1)
    with pytest.raises(FetchError, match="503"):
        fetcher.get("https://a.example/x")


def test_404_is_not_retried():
    state = {"n": 0}

    def handler(request):
        if request.url.path == "/robots.txt":
            return ok_robots(request)
        state["n"] += 1
        return httpx.Response(404)

    fetcher, _ = build(handler, retries=2)
    with pytest.raises(FetchError, match="404"):
        fetcher.get("https://a.example/x")
    assert state["n"] == 1


def test_transport_error_wrapped_in_fetch_error():
    def handler(request):
        if request.url.path == "/robots.txt":
            return ok_robots(request)
        raise httpx.ConnectError("boom")

    fetcher, _ = build(handler, retries=0)
    with pytest.raises(FetchError, match="boom"):
        fetcher.get("https://a.example/x")


def test_non_http_scheme_rejected():
    fetcher, _ = build(lambda r: httpx.Response(200))
    with pytest.raises(FetchError, match="scheme"):
        fetcher.get("file:///etc/passwd")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd TechNews && uv run pytest tests/test_fetch.py -q --tb=short`
Expected: FAIL with `ModuleNotFoundError: No module named 'technews.scrape'`.

- [ ] **Step 3: Implement**

`TechNews/src/technews/scrape/__init__.py`:

```python
"""Collectors that turn configured sources into articles."""
```

`TechNews/src/technews/scrape/fetch.py`:

```python
"""Guarded HTTP: robots.txt, per-host rate limit, transient retries, timeout."""

import logging
import time
from collections.abc import Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "TechNewsBot/0.1 (+https://github.com/dantenho)"
TIMEOUT_SECONDS = 15.0
_TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})


class FetchError(Exception):
    """A request failed permanently (non-2xx after retries, or transport failure)."""


class RobotsDisallowed(FetchError):
    """robots.txt forbids (or could not be read to permit) the request."""


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """Return an ``httpx.Client`` with our User-Agent, redirects and a timeout."""
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=TIMEOUT_SECONDS,
        transport=transport,
    )


class Fetcher:
    """Polite GET: honors robots.txt, spaces requests per host, retries transient failures."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        min_interval: float = 1.0,
        retries: int = 2,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._min_interval = min_interval
        self._retries = retries
        self._clock = clock
        self._sleep = sleep
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}

    def get(self, url: str) -> httpx.Response:
        """GET ``url`` and return a 2xx response.

        Raises:
            RobotsDisallowed: robots.txt forbids it, or robots.txt is unreadable (5xx/network).
            FetchError: scheme not http(s), non-2xx after retries, or transport failure.
        """
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise FetchError(f"unsupported scheme or host: {url}")
        origin = f"{parts.scheme}://{parts.netloc}"
        if not self._allowed(origin, url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")
        return self._request(origin, url)

    def get_bytes(self, url: str) -> bytes:
        """Return the body of :meth:`get` as bytes."""
        return self.get(url).content

    def _allowed(self, origin: str, url: str) -> bool:
        if origin not in self._robots:
            self._robots[origin] = self._load_robots(origin)
        parser = self._robots[origin]
        return parser is not None and parser.can_fetch(USER_AGENT, url)

    def _load_robots(self, origin: str) -> RobotFileParser | None:
        """Return a parser, an allow-all parser (4xx), or None (5xx/unreachable = deny)."""
        parser = RobotFileParser()
        try:
            resp = self._request(origin, f"{origin}/robots.txt", check_status=False)
        except FetchError:
            logger.warning("robots.txt unreachable for %s: treating as disallowed", origin)
            return None
        if resp.status_code == 200:
            parser.parse(resp.text.splitlines())
            return parser
        if 400 <= resp.status_code < 500:
            parser.parse(["User-agent: *", "Allow: /"])
            return parser
        logger.warning("robots.txt %s for %s: treating as disallowed", resp.status_code, origin)
        return None

    def _request(self, origin: str, url: str, *, check_status: bool = True) -> httpx.Response:
        last_error = "no attempt"
        for attempt in range(self._retries + 1):
            self._wait(origin)
            try:
                resp = self._client.get(url)
            except httpx.TransportError as err:
                last_error = str(err)
                logger.info("transport error for %s (attempt %d): %s", url, attempt + 1, err)
                continue
            if not check_status:
                if resp.status_code in _TRANSIENT_STATUS and attempt < self._retries:
                    last_error = f"HTTP {resp.status_code}"
                    continue
                return resp
            if resp.is_success:
                return resp
            last_error = f"HTTP {resp.status_code}"
            if resp.status_code not in _TRANSIENT_STATUS:
                break
        raise FetchError(f"{url}: {last_error}")

    def _wait(self, origin: str) -> None:
        last = self._last_hit.get(origin)
        if last is not None:
            remaining = self._min_interval - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last_hit[origin] = self._clock()
```

Note: with `check_status=False` and a persistent 5xx after retries, the loop falls out and raises `FetchError`, which `_load_robots` maps to "disallowed" — that is the intended 5xx behavior. A 4xx or 200 returns immediately.

- [ ] **Step 4: Run tests and lint**

Run: `cd TechNews && uv run pytest tests/test_fetch.py -q --tb=short && uv run ruff format src tests && uv run ruff check src tests`
Expected: all PASS. The robots.txt request counts as a host hit by design (polite), which is why the same-host wait in the rate-limit test is 2.0 s.

- [ ] **Step 5: Commit**

```bash
git add TechNews/src/technews/scrape TechNews/tests/test_fetch.py
git commit -m "feat(technews): guarded fetcher with robots, rate limit and retries"
```

---

### Task 5: Collectors (feeds, Hacker News, search fallback)

**Files:**
- Create: `TechNews/src/technews/scrape/feeds.py`, `TechNews/src/technews/scrape/hn.py`, `TechNews/src/technews/scrape/search.py`, `TechNews/tests/fixtures/sample.rss`, `TechNews/tests/fixtures/sample.atom`
- Test: `TechNews/tests/test_feeds.py`, `TechNews/tests/test_hn.py`, `TechNews/tests/test_search.py`

**Interfaces:**
- Consumes: `models.Source`, `models.Article`, `text.make_excerpt`, `fetch.Fetcher` (`.get_bytes(url)`, `.get(url)`).
- Produces:
  - `feeds.ParseError(Exception)`; `feeds.parse_feed(body: bytes, source: Source) -> list[Article]` (skips entries lacking link or title; `published=None` if no usable date; raises `ParseError` when the body yields no entries and feedparser flagged it malformed; truncates to `source.limit`).
  - `hn.collect_hn(fetcher: Fetcher, source: Source) -> list[Article]` (top stories via `https://hacker-news.firebaseio.com/v0/`; skips `null`, deleted, dead, non-story and url-less items).
  - `search.SearchFn = Callable[[str, int], list[dict[str, str]]]` (query, max results → dicts with `title`, `url`, `snippet`); `search.SearchUnavailable(Exception)`; `search.default_search() -> SearchFn`; `search.collect_search(source: Source, search_fn: SearchFn) -> list[Article]`.

- [ ] **Step 1: Write fixtures**

`TechNews/tests/fixtures/sample.rss`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Sample</title>
    <item>
      <title>GPU prices fall</title>
      <link>https://example.com/gpu?utm_source=rss</link>
      <description>&lt;p&gt;Prices &amp;amp; supply improve.&lt;/p&gt;</description>
      <pubDate>Tue, 07 Oct 2026 12:00:00 GMT</pubDate>
      <category>GPU</category>
      <category>Hardware</category>
    </item>
    <item>
      <title>No link here</title>
      <description>skipped</description>
    </item>
    <item>
      <link>https://example.com/no-title</link>
      <description>skipped too</description>
    </item>
    <item>
      <title>Undated post</title>
      <link>https://example.com/undated</link>
      <description>No date at all</description>
    </item>
  </channel>
</rss>
```

`TechNews/tests/fixtures/sample.atom`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Releases</title>
  <entry>
    <title>v1.2.3</title>
    <link href="https://github.com/o/r/releases/tag/v1.2.3"/>
    <updated>2026-10-06T08:30:00Z</updated>
    <content type="html">&lt;p&gt;Fixes &lt;b&gt;bugs&lt;/b&gt;&lt;/p&gt;</content>
  </entry>
  <entry>
    <title>v1.2.2</title>
    <link href="https://github.com/o/r/releases/tag/v1.2.2"/>
    <updated>2026-09-30T08:30:00Z</updated>
    <summary>Older</summary>
  </entry>
</feed>
```

- [ ] **Step 2: Write the failing tests**

`TechNews/tests/test_feeds.py`:

```python
from pathlib import Path

import pytest

from technews.models import Source
from technews.scrape.feeds import ParseError, parse_feed

FIX = Path(__file__).parent / "fixtures"
SRC = Source(name="S", category="hardware", kind="feed", url="https://example.com/feed")


def test_rss_entries_mapped_and_incomplete_skipped():
    arts = parse_feed((FIX / "sample.rss").read_bytes(), SRC)
    assert [a.title for a in arts] == ["GPU prices fall", "Undated post"]
    first = arts[0]
    assert first.url == "https://example.com/gpu?utm_source=rss"
    assert first.source == "S" and first.category == "hardware"
    assert first.published == "2026-10-07T12:00:00+00:00"
    assert first.excerpt == "Prices & supply improve."
    assert first.tags == ("gpu", "hardware")


def test_undated_entry_has_none_published_without_error():
    arts = parse_feed((FIX / "sample.rss").read_bytes(), SRC)
    assert arts[1].published is None


def test_atom_uses_updated_and_content():
    arts = parse_feed((FIX / "sample.atom").read_bytes(), SRC)
    assert arts[0].title == "v1.2.3"
    assert arts[0].published == "2026-10-06T08:30:00+00:00"
    assert arts[0].excerpt == "Fixes bugs"
    assert arts[1].excerpt == "Older"


def test_limit_applied():
    src = Source(name="S", category="git", kind="feed", url="https://e.com/f", limit=1)
    assert len(parse_feed((FIX / "sample.atom").read_bytes(), src)) == 1


def test_garbage_body_raises_parse_error():
    with pytest.raises(ParseError):
        parse_feed(b"<html><body>not a feed", SRC)


def test_empty_valid_feed_returns_empty_list():
    body = b'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'
    assert parse_feed(body, SRC) == []


def test_excerpt_capped_at_300():
    long = "word " * 200
    body = (
        '<?xml version="1.0"?><rss version="2.0"><channel><item><title>T</title>'
        f"<link>https://e.com/1</link><description>{long}</description></item></channel></rss>"
    ).encode()
    assert len(parse_feed(body, SRC)[0].excerpt) <= 300
```

`TechNews/tests/test_hn.py`:

```python
import json

import httpx

from technews.models import Source
from technews.scrape.fetch import Fetcher, make_client
from technews.scrape.hn import collect_hn

SRC = Source(name="HN", category="code", kind="hn", limit=5)
BASE = "https://hacker-news.firebaseio.com/v0"


def fetcher_for(items: dict[int, object], top: list[int]) -> Fetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/v0/topstories.json":
            return httpx.Response(200, json=top)
        item_id = int(path.rsplit("/", 1)[1].removesuffix(".json"))
        return httpx.Response(200, content=json.dumps(items.get(item_id)))

    return Fetcher(make_client(httpx.MockTransport(handler)), min_interval=0.0, sleep=lambda s: None)


def test_collects_stories_and_skips_bad_items():
    items = {
        1: {"id": 1, "type": "story", "title": "Good", "url": "https://e.com/1", "time": 1790000000},
        2: None,  # deleted/unavailable item comes back as JSON null
        3: {"id": 3, "type": "story", "title": "Ask HN: no url", "time": 1790000001},
        4: {"id": 4, "type": "job", "title": "Job", "url": "https://e.com/4", "time": 1790000002},
        5: {"id": 5, "type": "story", "title": "Dead", "url": "https://e.com/5", "dead": True},
        6: {"id": 6, "type": "story", "title": "Gone", "url": "https://e.com/6", "deleted": True},
    }
    arts = collect_hn(fetcher_for(items, [1, 2, 3, 4, 5, 6]), SRC)
    assert [a.title for a in arts] == ["Good"]
    assert arts[0].published == "2026-09-21T06:13:20+00:00"
    assert arts[0].category == "code" and arts[0].source == "HN"


def test_respects_limit_on_ids_fetched():
    items = {i: {"id": i, "type": "story", "title": f"t{i}", "url": f"https://e.com/{i}", "time": 1790000000}
             for i in range(1, 11)}
    arts = collect_hn(fetcher_for(items, list(range(1, 11))), SRC)
    assert len(arts) == 5
```

`TechNews/tests/test_search.py`:

```python
import pytest

from technews.models import Source
from technews.scrape.search import SearchUnavailable, collect_search, default_search

SRC = Source(name="Apple", category="bigtech", kind="search", query="site:apple.com/newsroom", limit=3)


def test_maps_hits_to_articles_and_respects_limit():
    calls = []

    def fake(query: str, n: int):
        calls.append((query, n))
        return [
            {"title": "One", "url": "https://apple.com/newsroom/1", "snippet": "<b>s1</b>"},
            {"title": "Two", "url": "https://apple.com/newsroom/2", "snippet": "s2"},
            {"title": "", "url": "https://apple.com/newsroom/3", "snippet": "no title"},
            {"title": "Four", "url": "", "snippet": "no url"},
            {"title": "Five", "url": "https://apple.com/newsroom/5", "snippet": "s5"},
            {"title": "Six", "url": "https://apple.com/newsroom/6", "snippet": "s6"},
        ]

    arts = collect_search(SRC, fake)
    assert calls == [("site:apple.com/newsroom", 3)]
    assert [a.title for a in arts] == ["One", "Two", "Five"]
    assert arts[0].excerpt == "s1" and arts[0].published is None
    assert arts[0].source == "Apple" and arts[0].category == "bigtech"


def test_default_search_unavailable_without_swarm_sdk(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def blocked(name, *a, **k):
        if name.startswith("swarm_sdk"):
            raise ImportError(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(SearchUnavailable):
        default_search()
```

- [ ] **Step 3: Run to verify failure**

Run: `cd TechNews && uv run pytest tests/test_feeds.py tests/test_hn.py tests/test_search.py -q --tb=short`
Expected: FAIL with `ModuleNotFoundError` for `technews.scrape.feeds`, `.hn`, `.search`.

- [ ] **Step 4: Implement feeds**

`TechNews/src/technews/scrape/feeds.py`:

```python
"""RSS/Atom collector (also covers GitHub ``releases.atom``)."""

import calendar
import logging
from datetime import UTC, datetime

import feedparser

from technews.models import Article, Source
from technews.text import make_excerpt

logger = logging.getLogger(__name__)


class ParseError(Exception):
    """The body is not a parseable feed."""


def parse_feed(body: bytes, source: Source) -> list[Article]:
    """Return up to ``source.limit`` articles from an RSS/Atom ``body``.

    Entries without a link or title are skipped; a missing date gives ``published=None``.

    Raises:
        ParseError: the body is malformed and produced no entries.
    """
    parsed = feedparser.parse(body)
    if parsed.bozo and not parsed.entries:
        raise ParseError(f"{source.name}: not a valid feed ({parsed.get('bozo_exception')})")
    out: list[Article] = []
    for entry in parsed.entries:
        link, title = entry.get("link"), (entry.get("title") or "").strip()
        if not link or not title:
            logger.debug("%s: skipping entry without link/title", source.name)
            continue
        out.append(
            Article(
                url=link,
                source=source.name,
                category=source.category,
                title=title,
                published=_iso(entry),
                excerpt=make_excerpt(_body(entry)),
                tags=tuple(
                    t["term"].strip().lower() for t in entry.get("tags", []) if t.get("term")
                ),
            )
        )
        if len(out) >= source.limit:
            break
    return out


def _body(entry: feedparser.FeedParserDict) -> str:
    content = entry.get("content")
    if content:
        return content[0].get("value", "")
    return entry.get("summary", "") or ""


def _iso(entry: feedparser.FeedParserDict) -> str | None:
    stamp = entry.get("published_parsed") or entry.get("updated_parsed")
    if not stamp:
        return None
    return datetime.fromtimestamp(calendar.timegm(stamp), UTC).isoformat()
```

- [ ] **Step 5: Implement Hacker News**

`TechNews/src/technews/scrape/hn.py`:

```python
"""Hacker News collector (public Firebase API, no key)."""

import json
import logging
from datetime import UTC, datetime

from technews.models import Article, Source
from technews.scrape.fetch import Fetcher

logger = logging.getLogger(__name__)

API = "https://hacker-news.firebaseio.com/v0"


def collect_hn(fetcher: Fetcher, source: Source) -> list[Article]:
    """Return up to ``source.limit`` top stories that link out.

    Deleted, dead, non-story and url-less items (including JSON ``null``) are skipped.
    """
    ids = json.loads(fetcher.get_bytes(f"{API}/topstories.json"))[: source.limit]
    out: list[Article] = []
    for item_id in ids:
        item = json.loads(fetcher.get_bytes(f"{API}/item/{item_id}.json"))
        if not isinstance(item, dict) or item.get("deleted") or item.get("dead"):
            continue
        url, title = item.get("url"), (item.get("title") or "").strip()
        if item.get("type") != "story" or not url or not title:
            continue
        stamp = item.get("time")
        out.append(
            Article(
                url=url,
                source=source.name,
                category=source.category,
                title=title,
                published=datetime.fromtimestamp(stamp, UTC).isoformat() if stamp else None,
                excerpt="",
            )
        )
    return out
```

- [ ] **Step 6: Implement search fallback**

`TechNews/src/technews/scrape/search.py`:

```python
"""Web-search fallback for sources without a feed (``site:`` queries)."""

import asyncio
from collections.abc import Callable

from technews.models import Article, Source
from technews.text import make_excerpt

type SearchFn = Callable[[str, int], list[dict[str, str]]]


class SearchUnavailable(Exception):
    """No web-search backend can be imported in this environment."""


def default_search() -> SearchFn:
    """Return a sync search function backed by ``swarm_sdk.search.duckduckgo``.

    Raises:
        SearchUnavailable: ``swarm_sdk`` is not importable (standalone env without the repo on
            ``PYTHONPATH``).
    """
    try:
        from swarm_sdk.search.duckduckgo import duckduckgo_search
    except ImportError as err:
        raise SearchUnavailable(
            "swarm_sdk.search is not importable; add the repo's src/ to PYTHONPATH"
        ) from err

    def run(query: str, max_results: int) -> list[dict[str, str]]:
        return asyncio.run(duckduckgo_search(query, max_results=max_results))

    return run


def collect_search(source: Source, search_fn: SearchFn) -> list[Article]:
    """Return up to ``source.limit`` articles from ``search_fn(source.query, limit)``.

    Hits without a title or URL are skipped. Search results carry no date.
    """
    hits = search_fn(source.query or "", source.limit)
    out: list[Article] = []
    for hit in hits:
        title, url = (hit.get("title") or "").strip(), (hit.get("url") or "").strip()
        if not title or not url:
            continue
        out.append(
            Article(
                url=url,
                source=source.name,
                category=source.category,
                title=title,
                published=None,
                excerpt=make_excerpt(hit.get("snippet", "")),
            )
        )
        if len(out) >= source.limit:
            break
    return out
```

- [ ] **Step 7: Run tests and lint**

Run: `cd TechNews && uv run pytest tests/test_feeds.py tests/test_hn.py tests/test_search.py -q --tb=short && uv run ruff format src tests && uv run ruff check src tests`
Expected: all PASS, ruff clean. Likely snags to fix in code, not tests: (a) `feedparser` may report `bozo` for the valid RSS fixture because of the `&amp;amp;` description; only raise when there are no entries (already the rule). (b) In `test_garbage_body_raises_parse_error`, if feedparser yields `bozo=0` and no entries for HTML, change the guard to `if not parsed.entries and (parsed.bozo or not parsed.feed)`; keep `test_empty_valid_feed_returns_empty_list` passing (a valid empty feed has `parsed.feed.title`).

- [ ] **Step 8: Commit**

```bash
git add TechNews/src/technews/scrape TechNews/tests
git commit -m "feat(technews): feed, Hacker News and search-fallback collectors"
```

---

### Task 6: Orchestration, CLI and live verification

**Files:**
- Modify: `TechNews/src/technews/scrape/__init__.py`
- Create: `TechNews/src/technews/cli.py`
- Test: `TechNews/tests/test_scrape.py`, `TechNews/tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `scrape.collect_articles(source: Source, fetcher: Fetcher, search_fn: SearchFn | None) -> list[Article]` (dispatches on `source.kind`; for `search` with `search_fn=None` raises `SearchUnavailable`).
  - `scrape.SourceResult(name: str, fetched: int, inserted: int, error: str | None)` (frozen dataclass).
  - `scrape.scrape_all(sources: Sequence[Source], fetcher: Fetcher, store: Store, search_fn: SearchFn | None = None) -> list[SourceResult]` (skips `enabled=False`; catches `FetchError`, `ParseError`, `SearchUnavailable`, `json.JSONDecodeError` per source and records the message; never aborts).
  - `scrape.check_source(source: Source, fetcher: Fetcher, search_fn: SearchFn | None = None) -> SourceResult` (same collection, no store; `fetched` = entry count; `error` set when it fails or returns 0 entries: `"0 entries"`).
  - `cli.main(argv: Sequence[str] | None = None) -> int`: `technews sources check [--sources PATH] [--all]` (prints one line per enabled source, `OK name N entries` or `FAIL name reason`; exit 1 if any failed) and `technews scrape [--sources PATH] [--db PATH]` (prints per-source summary and a total; exit 0 even if some sources failed, exit 1 only if every enabled source failed). Defaults: `--sources TechNews/sources.yaml` resolved relative to the package (`Path(__file__).parents[2] / "sources.yaml"`), `--db TechNews/data/technews.db` (`Path(__file__).parents[2] / "data" / "technews.db"`).

- [ ] **Step 1: Write the failing tests**

`TechNews/tests/test_scrape.py`:

```python
from pathlib import Path

import httpx

from technews.models import Source
from technews.scrape import check_source, scrape_all
from technews.scrape.fetch import Fetcher, make_client
from technews.store import Store

FIX = Path(__file__).parent / "fixtures"
RSS = (FIX / "sample.rss").read_bytes()


def fetcher_with(routes: dict[str, httpx.Response | Exception]) -> Fetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        outcome = routes[str(request.url)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return Fetcher(make_client(httpx.MockTransport(handler)), min_interval=0.0, retries=0,
                   sleep=lambda s: None)


GOOD = Source(name="Good", category="hardware", kind="feed", url="https://good.example/feed")
BAD_XML = Source(name="BadXml", category="ai", kind="feed", url="https://bad.example/feed")
DOWN = Source(name="Down", category="ai", kind="feed", url="https://down.example/feed")
OFF = Source(name="Off", category="ai", kind="feed", url="https://off.example/feed", enabled=False)
SEARCH = Source(name="Srch", category="bigtech", kind="search", query="site:x.com")


def routes():
    return {
        "https://good.example/feed": httpx.Response(200, content=RSS),
        "https://bad.example/feed": httpx.Response(200, content=b"<html>nope"),
        "https://down.example/feed": httpx.ConnectError("boom"),
    }


def test_one_failing_source_does_not_stop_the_others(tmp_path):
    with Store(tmp_path / "t.db") as store:
        results = scrape_all([DOWN, BAD_XML, GOOD, OFF, SEARCH], fetcher_with(routes()), store)
        by_name = {r.name: r for r in results}
        assert set(by_name) == {"Down", "BadXml", "Good", "Srch"}  # disabled source skipped
        assert by_name["Good"].error is None and by_name["Good"].inserted == 2
        assert "boom" in by_name["Down"].error
        assert by_name["BadXml"].error
        assert "search" in by_name["Srch"].error.lower()
        assert store.count() == 2


def test_rescrape_inserts_nothing_new(tmp_path):
    with Store(tmp_path / "t.db") as store:
        scrape_all([GOOD], fetcher_with(routes()), store)
        again = scrape_all([GOOD], fetcher_with(routes()), store)
        assert again[0].fetched == 2 and again[0].inserted == 0


def test_check_source_reports_entry_count_and_zero_entries_as_error():
    ok = check_source(GOOD, fetcher_with(routes()))
    assert ok.error is None and ok.fetched == 2
    empty_body = b'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'
    empty = check_source(GOOD, fetcher_with({"https://good.example/feed": httpx.Response(200, content=empty_body)}))
    assert empty.error == "0 entries"
```

`TechNews/tests/test_cli.py`:

```python
from pathlib import Path

import httpx
import pytest

from technews import cli
from technews.scrape.fetch import Fetcher, make_client

RSS = (Path(__file__).parent / "fixtures" / "sample.rss").read_bytes()

YAML = """
sources:
  - {name: Good, category: hardware, kind: feed, url: "https://good.example/feed"}
  - {name: Down, category: ai, kind: feed, url: "https://down.example/feed"}
"""


@pytest.fixture
def patched(monkeypatch, tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.host == "good.example":
            return httpx.Response(200, content=RSS)
        raise httpx.ConnectError("boom")

    def build_fetcher():
        return Fetcher(make_client(httpx.MockTransport(handler)), min_interval=0.0, retries=0,
                       sleep=lambda s: None)

    monkeypatch.setattr(cli, "build_fetcher", build_fetcher)
    monkeypatch.setattr(cli, "build_search", lambda: None)
    path = tmp_path / "sources.yaml"
    path.write_text(YAML, encoding="utf-8")
    return path


def test_sources_check_exit_1_when_any_fails(patched, capsys):
    code = cli.main(["sources", "check", "--sources", str(patched)])
    out = capsys.readouterr().out
    assert code == 1
    assert "OK Good 2 entries" in out
    assert "FAIL Down" in out and "boom" in out


def test_scrape_partial_failure_exit_0_and_writes_db(patched, tmp_path, capsys):
    db = tmp_path / "out" / "t.db"
    code = cli.main(["scrape", "--sources", str(patched), "--db", str(db)])
    out = capsys.readouterr().out
    assert code == 0
    assert db.exists()
    assert "Good" in out and "inserted 2" in out
    assert "FAIL Down" in out


def test_scrape_exit_1_when_every_source_fails(patched, tmp_path):
    path = tmp_path / "all_down.yaml"
    path.write_text("sources:\n  - {name: Down, category: ai, kind: feed, url: 'https://down.example/f'}\n")
    assert cli.main(["scrape", "--sources", str(path), "--db", str(tmp_path / "t.db")]) == 1


def test_bad_registry_is_clean_error(tmp_path, capsys):
    path = tmp_path / "bad.yaml"
    path.write_text("sources: []")
    assert cli.main(["scrape", "--sources", str(path), "--db", str(tmp_path / "t.db")]) == 2
    assert "no sources" in capsys.readouterr().err
```

- [ ] **Step 2: Run to verify failure**

Run: `cd TechNews && uv run pytest tests/test_scrape.py tests/test_cli.py -q --tb=short`
Expected: FAIL with `ImportError: cannot import name 'check_source'` and `ModuleNotFoundError: technews.cli`.

- [ ] **Step 3: Implement orchestration**

`TechNews/src/technews/scrape/__init__.py` (replace content):

```python
"""Collectors that turn configured sources into articles."""

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from technews.models import Article, Source
from technews.scrape.feeds import ParseError, parse_feed
from technews.scrape.fetch import FetchError, Fetcher
from technews.scrape.hn import collect_hn
from technews.scrape.search import SearchFn, SearchUnavailable, collect_search
from technews.store import Store

logger = logging.getLogger(__name__)

_COLLECT_ERRORS = (FetchError, ParseError, SearchUnavailable, json.JSONDecodeError)


@dataclass(frozen=True, slots=True)
class SourceResult:
    """Outcome of collecting one source."""

    name: str
    fetched: int
    inserted: int
    error: str | None


def collect_articles(
    source: Source, fetcher: Fetcher, search_fn: SearchFn | None
) -> list[Article]:
    """Collect articles for ``source`` using the collector for its kind.

    Raises:
        FetchError, ParseError, SearchUnavailable, json.JSONDecodeError: collection failed.
    """
    match source.kind:
        case "feed":
            return parse_feed(fetcher.get_bytes(source.url or ""), source)
        case "hn":
            return collect_hn(fetcher, source)
        case "search":
            if search_fn is None:
                raise SearchUnavailable("no web-search backend configured for kind=search")
            return collect_search(source, search_fn)


def scrape_all(
    sources: Sequence[Source],
    fetcher: Fetcher,
    store: Store,
    search_fn: SearchFn | None = None,
) -> list[SourceResult]:
    """Collect every enabled source into ``store``; a failing source never stops the rest."""
    results: list[SourceResult] = []
    for source in sources:
        if not source.enabled:
            continue
        try:
            articles = collect_articles(source, fetcher, search_fn)
        except _COLLECT_ERRORS as err:
            logger.warning("source %s failed: %s", source.name, err)
            results.append(SourceResult(source.name, 0, 0, str(err)))
            continue
        results.append(SourceResult(source.name, len(articles), store.add_many(articles), None))
    return results


def check_source(
    source: Source, fetcher: Fetcher, search_fn: SearchFn | None = None
) -> SourceResult:
    """Collect ``source`` without storing; zero entries counts as a failure."""
    try:
        articles = collect_articles(source, fetcher, search_fn)
    except _COLLECT_ERRORS as err:
        return SourceResult(source.name, 0, 0, str(err))
    if not articles:
        return SourceResult(source.name, 0, 0, "0 entries")
    return SourceResult(source.name, len(articles), 0, None)
```

- [ ] **Step 4: Implement the CLI**

`TechNews/src/technews/cli.py`:

```python
"""``technews`` command line: ``sources check`` and ``scrape``."""

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from technews.scrape import check_source, scrape_all
from technews.scrape.fetch import Fetcher, make_client
from technews.scrape.search import SearchFn, SearchUnavailable, default_search
from technews.sources import SourceConfigError, load_sources
from technews.store import Store

_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCES = _ROOT / "sources.yaml"
DEFAULT_DB = _ROOT / "data" / "technews.db"


def build_fetcher() -> Fetcher:
    """Return the production fetcher (network, robots, rate limit)."""
    return Fetcher(make_client())


def build_search() -> SearchFn | None:
    """Return the web-search backend, or None when it is not importable."""
    try:
        return default_search()
    except SearchUnavailable:
        return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="technews")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("sources", help="inspect the source registry")
    check_sub = check.add_subparsers(dest="action", required=True)
    check_run = check_sub.add_parser("check", help="fetch every enabled source once")
    check_run.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    scrape = sub.add_parser("scrape", help="collect all enabled sources into the store")
    scrape.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    scrape.add_argument("--db", type=Path, default=DEFAULT_DB)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI; return the process exit code."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    args = _parser().parse_args(argv)
    try:
        sources = load_sources(args.sources)
    except SourceConfigError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    fetcher, search_fn = build_fetcher(), build_search()
    if args.command == "sources":
        results = [check_source(s, fetcher, search_fn) for s in sources if s.enabled]
        for r in results:
            print(f"FAIL {r.name}: {r.error}" if r.error else f"OK {r.name} {r.fetched} entries")
        return 1 if any(r.error for r in results) else 0
    with Store(args.db) as store:
        results = scrape_all(sources, fetcher, store, search_fn)
        for r in results:
            if r.error:
                print(f"FAIL {r.name}: {r.error}")
            else:
                print(f"{r.name}: fetched {r.fetched}, inserted {r.inserted}")
        print(f"total inserted {sum(r.inserted for r in results)}, stored {store.count()}")
    return 1 if results and all(r.error for r in results) else 0
```

- [ ] **Step 5: Run the whole suite and lint**

Run: `cd TechNews && uv run pytest -q --tb=short && uv run ruff format --check src tests && uv run ruff check src tests && uv run python -m compileall -q src`
Expected: all tests PASS; format check, ruff and compileall clean. If the exact string `inserted 2` in `test_scrape_partial_failure_exit_0_and_writes_db` mismatches the CLI line `Good: fetched 2, inserted 2`, it already matches via substring; do not change the assertion.

- [ ] **Step 6: Live verification (manual, not part of the suite)**

Run each, record the output in the report, and do not retry a failing command more than once:

```bash
cd TechNews && uv run technews sources check 2>&1 | tee /tmp/technews-check.txt
```

Expected: a mix of `OK` and `FAIL` lines. Candidate feeds/queries that fail are *expected data*, not bugs. For each `FAIL`, set `enabled: false` in `sources.yaml` (keep the entry) and note the reason in the report. Search-kind entries print `FAIL ... SearchUnavailable` in the standalone env unless run with `PYTHONPATH=../src` and the root deps importable; if that import also fails because `swarm_sdk.search.duckduckgo` needs `trafilatura`, report it and add `trafilatura` as a dependency of `TechNews` only if the search path is wanted in stage 1 (check PyPI first); otherwise leave search entries enabled-but-failing and flag them. Then:

```bash
cd TechNews && uv run technews scrape && uv run python -c "
from technews.store import Store; from technews.cli import DEFAULT_DB
s = Store(DEFAULT_DB); print(s.count()); [print(a.category, a.source, a.title[:70]) for a in s.recent(8)]"
```

Expected: nonzero stored count and recent headlines across several categories; running `technews scrape` a second time reports `inserted 0` (or near 0) per source (dedupe proof).

- [ ] **Step 7: Commit**

```bash
git add TechNews/src TechNews/tests TechNews/sources.yaml
git commit -m "feat(technews): scrape orchestration, sources check and scrape CLI"
```

---

## Self-Review

**Spec coverage:** sources.yaml with five categories and 30 Big Tech (Task 2) ✔; guarded fetcher with timeout/robots/rate limit/retry (Task 4) ✔; feeds, HN, git releases-as-Atom, search fallback (Task 5) ✔; SQLite store with dedupe by canonical URL and hash, excerpt ≤300 (Tasks 1, 3) ✔; `sources check` and `scrape` CLI (Task 6) ✔; feed URLs verified by running, not trusted from memory (Task 6 step 6) ✔. Stages 2–5 are intentionally out of this plan (each gets its own plan after review).

**Placeholder scan:** none; every code step has full code. The one conditional in Task 4 step 4 and Task 5 step 7 names a concrete trace/guard to apply, not a vague "fix".

**Type consistency:** `Source`, `Article`, `Store.add/add_many/recent/count`, `Fetcher.get/get_bytes`, `SearchFn`, `SourceResult`, `collect_articles`, `scrape_all`, `check_source`, `build_fetcher`, `build_search` are defined once and used with the same signatures downstream.

**Not run:** no code in this plan has been executed; test expectations were traced by hand (rate-limit total 2.0 s) and the feedparser garbage-body guard in Task 5 step 7 is the most likely place for a first-run adjustment. Only the dependency resolution (`uv pip compile` of the TechNews deps on Python 3.14) was run.
