# WebSearch Prefilter, Normalization, Near-Dedupe and Sink Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `parallel_search` drop junk hits before fusion, clean titles and snippets, merge near-duplicate hits, and hand the final hits to an optional sink.

**Architecture:** Hit-level stages are pure functions in `frontend/` (`prefilter.py`, `hits.py`) that operate on `SearchHit`; `parallel_search` stays the single pipeline (`search -> prefilter -> RRF fuse -> URL dedupe -> normalize -> near-dedupe -> cap -> sink`). `PrefilterPolicy` lives in `frontend/providers.py` and loads from a new `prefilter:` block in `providers.yaml`. The sink is a `Protocol` with a no-op default; WebSearch never imports anything outside itself.

**Tech Stack:** Python 3.14, stdlib only (`hashlib`, `re`, `dataclasses`, `urllib.parse`), PyYAML (already used), pytest.

**Spec:** `docs/superpowers/specs/2026-10-01-websearch-prefilter-design.md`. Task 1 amends it first: the spec put the stages in `backend/` and added `midend/pipeline.py`, but `backend` already imports `frontend.providers` (so `frontend` importing `backend` from `parallel_search` would close a cycle through package inits) and `search_hits`/`search_brief` already share `parallel_search`. The default `max_distance` also moves from 3 to 6 (measured, see Task 4).

## Global Constraints

- Python 3.14 (`target-version py314`), typed public API, stdlib `logging` (`logger = logging.getLogger(__name__)`), no new runtime dependency.
- WebSearch is a standalone extra: nothing under `WebSearch/` (code, docstrings, `providers.yaml`, README, spec) imports or refers to any host application, agent framework or consumer.
- Default behavior of `parallel_search` and `search_brief` is unchanged unless a caller opts in to the sink; prefilter, normalize and near-dedupe run by default with a permissive policy.
- Deterministic, pure functions; no network, no embeddings model in WebSearch.
- Per-hit failures reject that hit with a reason and never abort the batch; `sink.store` failures with `OSError` are logged and the search results are still returned; other sink exceptions propagate.
- Config errors in `prefilter:` raise `ValueError` naming the field.
- Lint: no new `# noqa`, `# type: ignore` or skip/xfail.

**Working-tree note.** `README.md`, `frontend/__init__.py`, `frontend/http.py`, `frontend/providers.py` and `frontend/README.md` already hold uncommitted changes from the earlier code-review fixes. This plan patches three of them. Each patch below was generated against the current working tree and checked with `git apply --check`. **Do not `git add` those files wholesale.** The plan has no commit steps; Task 5 ends with a status check so the owner decides how to commit.

**Commands used throughout** (this worktree has no `pyproject.toml`, so the parent project's ruff settings are passed explicitly):

```bash
uv run --no-project --with pytest --with pyyaml --with httpx python -m pytest tests -q --tb=short
ruff format --line-length 100 --target-version py314 --check tests frontend
ruff check --line-length 100 --target-version py314 --select E,F,I,UP --config 'lint.isort.known-first-party=["WebSearch"]' tests frontend agent_tools.py
```

## Review Focus

- A hit with an unparsable URL such as `http://[::1` must be rejected as `bad_url`, never raise. Pinned in Task 3 (`test_each_rejection_reason`).
- The provider that carried the call's `api_tokens` total may have its hit rejected; the total must still reach the caller, once, on the first hit. Pinned in Task 5 (`test_api_tokens_total_survives_prefilter_and_sits_on_the_first_hit`).
- Every hit rejected must return `[]` and must not call the sink. Pinned in Task 5 (`test_all_hits_rejected_returns_empty_and_skips_the_sink`).
- A sink that fails with `OSError` must not lose the search; a sink that raises a programming error (`ValueError`) must surface it. Pinned in Task 5 (`test_sink_oserror_still_returns_results`, `test_sink_programming_error_propagates`).
- Titles with a separator that is not the site name, a title that is only a suffix, empty text and non-ASCII text must come through unchanged or cleanly. Pinned in Task 4 (`test_other_separator_text_is_kept`, `test_title_that_is_only_a_suffix_is_kept`, `test_normalize_handles_empty_and_non_ascii`).

---

### Task 1: Spec amendment, test harness, hit and sink types

**Files:**

- Modify: `docs/superpowers/specs/2026-10-01-websearch-prefilter-design.md`
- Modify: `frontend/models.py`
- Create: `tests/conftest.py`
- Create: `tests/test_models.py`

**Interfaces:**

- Consumes: existing `SearchHit(title, url, snippet, searcher_id, api_tokens=0)` in `frontend/models.py`.
- Produces: `SearchHit.also_from: tuple[str, ...] = ()`; `SinkReport(stored: int, skipped: int = 0, detail: str = "")`; `ResultSink` Protocol with `store(self, hits: Sequence[SearchHit]) -> SinkReport`; `NullSink` with the same method returning `SinkReport(stored=0)`. All exported from `WebSearch.frontend.models`.

- [ ] **Step 1: Add the test harness.** The checkout directory is not named `WebSearch`, so this conftest registers it under that name.

```python
"""Make the checkout importable as ``WebSearch`` whatever its directory is called."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if "WebSearch" not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        "WebSearch", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["WebSearch"] = module
    spec.loader.exec_module(module)
```

- [ ] **Step 2: Write the failing test**

```python
from WebSearch.frontend import SearchHit
from WebSearch.frontend.models import NullSink, SinkReport


def test_search_hit_also_from_defaults_to_empty() -> None:
    assert SearchHit("t", "https://a.example", "s", "brave").also_from == ()


def test_null_sink_stores_nothing() -> None:
    hit = SearchHit("t", "https://a.example", "s", "brave")
    assert NullSink().store([hit]) == SinkReport(stored=0)
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run --no-project --with pytest --with pyyaml --with httpx python -m pytest tests/test_models.py -q --tb=short`
Expected: ERROR at collection, `ImportError: cannot import name 'NullSink'`.

- [ ] **Step 4: Apply the model change**

```bash
git apply <<'PATCH'
--- a/frontend/models.py
+++ b/frontend/models.py
@@ -21,6 +21,8 @@
     searcher_id: str
     #: Tokens the search API reported for the call; set on the first hit only.
     api_tokens: int = 0
+    #: Searcher ids whose near-duplicate hit was merged into this one.
+    also_from: tuple[str, ...] = ()


 class WebSearcher(Protocol):
@@ -29,6 +31,32 @@
     def search(self, query: str) -> Sequence[SearchHit]: ...


+@dataclass(frozen=True, slots=True)
+class SinkReport:
+    """Outcome of one :meth:`ResultSink.store` call.
+
+    ``detail`` is free text the sink may use to say how it ran; WebSearch never
+    interprets it.
+    """
+
+    stored: int
+    skipped: int = 0
+    detail: str = ""
+
+
+class ResultSink(Protocol):
+    """Receives the final, cleaned hits (for example to index them)."""
+
+    def store(self, hits: Sequence[SearchHit]) -> SinkReport: ...
+
+
+class NullSink:
+    """Sink that stores nothing."""
+
+    def store(self, hits: Sequence[SearchHit]) -> SinkReport:
+        return SinkReport(stored=0)
+
+
 def type_is_hit(value: object) -> bool:
     """Return whether *value* is a ``SearchHit``.

@@ -61,4 +89,13 @@
     return unique


-__all__ = ["SearchFn", "SearchHit", "WebSearcher", "dedupe_hits", "type_is_hit"]
+__all__ = [
+    "NullSink",
+    "ResultSink",
+    "SearchFn",
+    "SearchHit",
+    "SinkReport",
+    "WebSearcher",
+    "dedupe_hits",
+    "type_is_hit",
+]
PATCH
```

- [ ] **Step 5: Run it to verify it passes**

Run: `uv run --no-project --with pytest --with pyyaml --with httpx python -m pytest tests/test_models.py -q --tb=short`
Expected: 2 passed.

- [ ] **Step 6: Amend the spec** (layering, `near_distance`, default distance, token total)

```bash
git apply <<'PATCH'
--- a/docs/superpowers/specs/2026-10-01-websearch-prefilter-design.md
+++ b/docs/superpowers/specs/2026-10-01-websearch-prefilter-design.md
@@ -26,13 +26,14 @@

 ## Components

-### `backend/prefilter.py`
+### `frontend/prefilter.py`

 - `PrefilterPolicy` (frozen, slots dataclass): `schemes` (default `http`,
   `https`), `blocked_domains` (tuple, suffix match), `min_snippet_chars` (int,
   default 0), `require_title` (bool, default True).
-  Loaded from a new optional `prefilter:` block in `providers.yaml`; numeric
-  fields use the same fail-fast coercion as `crawl:`.
+  Defined in `frontend/providers.py` next to `CrawlSpec` and loaded from a new
+  optional `prefilter:` block in `providers.yaml`; numeric fields use the same
+  fail-fast coercion as `crawl:`.
 - `Rejected` (frozen dataclass): `hit: SearchHit`, `reason: RejectReason`.
   `RejectReason` is a `Literal`: `bad_url`, `scheme`, `blocked_domain`,
   `empty`, `short_snippet`.
@@ -43,17 +44,19 @@
   unwrap redirect (replacing the hit URL), then apply checks in the order
   listed in `RejectReason`. A failure on one hit rejects that hit only.

-### `backend/hits.py`
+### `frontend/hits.py`

 - `normalize_hit(hit) -> SearchHit`: `normalize_text` on title and snippet;
   strip a trailing site-name suffix (`" | X"`, `" - X"`, `" – X"`) only when `X`
   matches the hit's own registrable-domain label (case-insensitive), so titles
   that merely contain a separator are kept.
-- `near_dedupe(hits, *, max_distance=3) -> list[SearchHit]`: 64-bit SimHash over
+- `near_dedupe(hits, *, max_distance=6) -> list[SearchHit]`: 64-bit SimHash over
   word 3-shingles of `title + " " + snippet`; a hit within `max_distance`
   Hamming bits of an earlier kept hit is dropped. Input order is rank order, so
   the best-ranked hit survives. Hits with fewer than 3 tokens are never merged
-  (too little signal). The survivor records the dropped searcher ids in
+  (too little signal). The default of 6 was measured on 64-bit SimHashes of
+  short title+snippet text: an appended word gives distance 5, a swapped phrase
+  9, an unrelated hit 29. The survivor records the dropped searcher ids in
   `SearchHit.also_from: tuple[str, ...]` (new field, default `()`).

 ### `ResultSink`
@@ -77,10 +80,12 @@
 `detail` is free text the sink may use to report how it ran (for example which
 embedder it used). WebSearch never interprets it.

-### `midend/pipeline.py`
+### Layering

-Orchestrates the post-search stages so `parallel_search` and `search_brief`
-share one path.
+`backend` already imports `frontend.providers`, so the hit-level stages live in
+`frontend` (they operate on `SearchHit`) and call `backend.normalize` for text.
+There is no separate pipeline module: `parallel_search` is the single path and
+`search_hits` / `search_brief` inherit it.

 ## Data flow

@@ -90,7 +95,10 @@
```

Prefilter runs before fusion so a junk URL cannot gain rank from consensus.
\-`parallel_search(..., sink: ResultSink | None = None)`; `None` skips the sink. +`parallel_search(..., near_distance: int | None = 6, sink: ResultSink | None = None)`; +`near_distance=None` disables near-dedupe and `sink=None` skips the sink. The API
+token total reported by the providers is summed before prefiltering and placed
+on the first final hit, so rejecting the hit that carried it loses no accounting.
Rejected hits are logged at DEBUG with their reason and returned by
`prefilter_hits` for callers that want them.

PATCH

`````

Check: `rg -n -i "swarm|midend/pipeline|backend/prefilter|backend/hits" docs/superpowers/specs/2026-10-01-websearch-prefilter-design.md` prints nothing.

---

### Task 2: `PrefilterPolicy` config

**Files:**
- Modify: `frontend/providers.py`
- Modify: `providers.yaml`
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: `_coerce_number` already in `frontend/providers.py`.
- Produces: `PrefilterPolicy(schemes: tuple[str, ...] = ("http", "https"), blocked_domains: tuple[str, ...] = (), min_snippet_chars: int = 0, require_title: bool = True)` frozen dataclass; `ProvidersConfig.prefilter: PrefilterPolicy` (default `PrefilterPolicy()`); `load_providers` parses the optional `prefilter:` block (schemes and domains lowercased, leading dots stripped; empty `schemes` falls back to the default; a non-numeric `min_snippet_chars` raises `ValueError` naming `prefilter.min_snippet_chars`).

- [ ] **Step 1: Write the failing test**

````python
from pathlib import Path

import pytest

from WebSearch.frontend.providers import PrefilterPolicy, load_providers


def _load(tmp_path: Path, text: str):
    path = tmp_path / "providers.yaml"
    path.write_text(text, encoding="utf-8")
    return load_providers(path)


def test_prefilter_defaults_without_block(tmp_path: Path) -> None:
    assert _load(tmp_path, "version: 1\n").prefilter == PrefilterPolicy()


def test_prefilter_block_is_parsed_and_normalized(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        "prefilter:\n"
        "  schemes: [HTTPS]\n"
        "  blocked_domains: ['.Spam.Example', '']\n"
        "  min_snippet_chars: '12'\n"
        "  require_title: false\n",
    )
    assert cfg.prefilter == PrefilterPolicy(
        schemes=("https",),
        blocked_domains=("spam.example",),
        min_snippet_chars=12,
        require_title=False,
    )


def test_prefilter_empty_schemes_fall_back_to_default(tmp_path: Path) -> None:
    assert _load(tmp_path, "prefilter:\n  schemes: []\n").prefilter.schemes == ("http", "https")


def test_prefilter_bad_number_names_the_field(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"prefilter\.min_snippet_chars"):
        _load(tmp_path, "prefilter:\n  min_snippet_chars: abc\n")


def test_packaged_providers_yaml_has_permissive_prefilter() -> None:
    assert load_providers().prefilter == PrefilterPolicy()
`````

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --no-project --with pytest --with pyyaml --with httpx python -m pytest tests/test_config.py -q --tb=short`
Expected: ERROR at collection, `ImportError: cannot import name 'PrefilterPolicy'`.

- [ ] **Step 3: Apply the config change**

```bash
git apply <<'PATCH'
--- a/frontend/providers.py
+++ b/frontend/providers.py
@@ -44,11 +44,20 @@


 @dataclass(frozen=True, slots=True)
+class PrefilterPolicy:
+    schemes: tuple[str, ...] = ("http", "https")
+    blocked_domains: tuple[str, ...] = ()
+    min_snippet_chars: int = 0
+    require_title: bool = True
+
+
+@dataclass(frozen=True, slots=True)
 class ProvidersConfig:
     version: int
     searchers: tuple[SearcherSpec, ...]
     extractor_order: tuple[ExtractorName, ...]
     crawl: CrawlSpec = field(default_factory=CrawlSpec)
+    prefilter: PrefilterPolicy = field(default_factory=PrefilterPolicy)


 def providers_yaml_path() -> Path:
@@ -130,6 +139,8 @@
         schemes = tuple(str(s) for s in schemes_val) or ("http", "https")
     else:
         schemes = ("http", "https")
+    prefilter_block = raw.get("prefilter")
+    prefilter_raw: dict[str, object] = prefilter_block if isinstance(prefilter_block, dict) else {}
     return ProvidersConfig(
         version=_coerce_number(raw.get("version"), int, 1, "version"),
         searchers=tuple(searchers),
@@ -141,9 +152,30 @@
             schemes=schemes,
             crawler_order=crawler_order,
         ),
+        prefilter=_parse_prefilter(prefilter_raw),
     )


+def _str_tuple(value: object) -> tuple[str, ...]:
+    """Lowercased, stripped, non-empty strings of a yaml list; anything else → ``()``."""
+    if not isinstance(value, list):
+        return ()
+    return tuple(text for item in value if (text := str(item).strip().lower().lstrip(".")))
+
+
+def _parse_prefilter(raw: dict[str, object]) -> PrefilterPolicy:
+    """Build a :class:`PrefilterPolicy` from the ``prefilter:`` yaml block."""
+    require_title = raw.get("require_title")
+    return PrefilterPolicy(
+        schemes=_str_tuple(raw.get("schemes")) or ("http", "https"),
+        blocked_domains=_str_tuple(raw.get("blocked_domains")),
+        min_snippet_chars=_coerce_number(
+            raw.get("min_snippet_chars"), int, 0, "prefilter.min_snippet_chars"
+        ),
+        require_title=require_title if isinstance(require_title, bool) else True,
+    )
+
+
 def _coerce_number[N: (int, float)](
     value: object, cast: Callable[[Any], N], default: N, label: str
 ) -> N:
@@ -196,6 +228,7 @@
     "CrawlerName",
     "CrawlSpec",
     "ExtractorName",
+    "PrefilterPolicy",
     "ProvidersConfig",
     "SearcherKind",
     "SearcherSpec",
PATCH
```

```bash
git apply <<'PATCH'
--- a/providers.yaml
+++ b/providers.yaml
@@ -62,3 +62,11 @@
   schemes:
     - http
     - https
+
+prefilter:
+  schemes:
+    - http
+    - https
+  blocked_domains: []
+  min_snippet_chars: 0
+  require_title: true
PATCH
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run --no-project --with pytest --with pyyaml --with httpx python -m pytest tests/test_models.py tests/test_config.py -q --tb=short`
Expected: 7 passed.

---

### Task 3: Prefilter

**Files:**

- Create: `frontend/prefilter.py`
- Create: `tests/test_prefilter.py`

**Interfaces:**

- Consumes: `SearchHit`, `PrefilterPolicy`.
- Produces: `unwrap_redirect(url: str) -> str`; `Rejected(hit: SearchHit, reason: RejectReason)`; `type RejectReason = Literal["bad_url", "scheme", "blocked_domain", "empty", "short_snippet"]`; `prefilter_hits(hits: Sequence[SearchHit], policy: PrefilterPolicy) -> tuple[list[SearchHit], list[Rejected]]`.

- [ ] **Step 1: Write the failing test**

```python
import pytest

from WebSearch.frontend import SearchHit
from WebSearch.frontend.prefilter import prefilter_hits, unwrap_redirect
from WebSearch.frontend.providers import PrefilterPolicy

POLICY = PrefilterPolicy(blocked_domains=("spam.example",), min_snippet_chars=5)


def _hit(
    url: str = "https://good.example/a", title: str = "T", snippet: str = "long enough"
) -> SearchHit:
    return SearchHit(title=title, url=url, snippet=snippet, searcher_id="brave")


@pytest.mark.parametrize(
    ("hit", "reason"),
    [
        (_hit(url="http://[::1"), "bad_url"),
        (_hit(url="javascript:alert(1)"), "bad_url"),
        (_hit(url=""), "bad_url"),
        (_hit(url="ftp://good.example/file"), "scheme"),
        (_hit(url="https://spam.example/x"), "blocked_domain"),
        (_hit(url="https://www.spam.example/x"), "blocked_domain"),
        (_hit(title="  ", snippet="long enough"), "empty"),
        (_hit(title="", snippet=""), "empty"),
        (_hit(snippet="abc"), "short_snippet"),
    ],
)
def test_each_rejection_reason(hit: SearchHit, reason: str) -> None:
    kept, rejected = prefilter_hits([hit], POLICY)
    assert kept == []
    assert [r.reason for r in rejected] == [reason]
    assert rejected[0].hit is hit


def test_lookalike_domain_is_not_blocked() -> None:
    kept, _ = prefilter_hits([_hit(url="https://notspam.example/x")], POLICY)
    assert len(kept) == 1


def test_snippet_only_hit_passes_when_title_not_required() -> None:
    policy = PrefilterPolicy(require_title=False)
    kept, _ = prefilter_hits([_hit(title="", snippet="has text")], policy)
    assert len(kept) == 1


def test_one_bad_hit_does_not_affect_the_rest_and_order_is_kept() -> None:
    first, bad, last = (
        _hit(url="https://a.example"),
        _hit(url="http://[::1"),
        _hit(url="https://b.example"),
    )
    kept, rejected = prefilter_hits([first, bad, last], POLICY)
    assert kept == [first, last]
    assert [r.hit for r in rejected] == [bad]


def test_unwrap_google_redirect() -> None:
    url = "https://www.google.com/url?q=https%3A%2F%2Ftarget.example%2Fpage&sa=U"
    assert unwrap_redirect(url) == "https://target.example/page"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/url?q=https://target.example",
        "https://www.google.com/url?q=javascript:alert(1)",
        "https://www.google.com/search?q=https://target.example",
        "http://[::1",
        "https://good.example/a",
    ],
)
def test_unwrap_leaves_other_urls_alone(url: str) -> None:
    assert unwrap_redirect(url) == url


def test_prefilter_replaces_redirect_url_with_target() -> None:
    hit = _hit(url="https://www.google.com/url?q=https://target.example/p")
    kept, _ = prefilter_hits([hit], POLICY)
    assert [h.url for h in kept] == ["https://target.example/p"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --no-project --with pytest --with pyyaml --with httpx python -m pytest tests/test_prefilter.py -q --tb=short`
Expected: ERROR at collection, `ModuleNotFoundError: No module named 'WebSearch.frontend.prefilter'`.

- [ ] **Step 3: Write the implementation**

```python
"""Prefilter: drop unusable search hits before fusion can reward them."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from WebSearch.frontend.models import SearchHit
from WebSearch.frontend.providers import PrefilterPolicy

logger = logging.getLogger(__name__)

type RejectReason = Literal["bad_url", "scheme", "blocked_domain", "empty", "short_snippet"]

_GOOGLE_HOST = re.compile(r"(www\.)?google\.[a-z.]+")


@dataclass(frozen=True, slots=True)
class Rejected:
    hit: SearchHit
    reason: RejectReason


def unwrap_redirect(url: str) -> str:
    """Return the target of a ``google.*/url?q=...`` tracking redirect.

    Args:
        url (str): Hit URL.

    Returns:
        str: The wrapped ``http(s)`` target, or *url* unchanged when it is not
        a recognised redirect or cannot be parsed.
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url
    if parts.path != "/url" or not _GOOGLE_HOST.fullmatch(parts.hostname or ""):
        return url
    query = parse_qs(parts.query)
    for key in ("q", "url"):
        for target in query.get(key, []):
            if target.startswith(("http://", "https://")):
                return target
    return url


def _reject_reason(hit: SearchHit, policy: PrefilterPolicy) -> RejectReason | None:
    """Return why *hit* must be dropped, or ``None`` to keep it."""
    try:
        parts = urlsplit(hit.url.strip())
        host = parts.hostname
    except ValueError:
        return "bad_url"
    if not host:
        return "bad_url"
    if parts.scheme.lower() not in policy.schemes:
        return "scheme"
    if any(host == domain or host.endswith(f".{domain}") for domain in policy.blocked_domains):
        return "blocked_domain"
    title, snippet = hit.title.strip(), hit.snippet.strip()
    if (policy.require_title and not title) or not (title or snippet):
        return "empty"
    if len(snippet) < policy.min_snippet_chars:
        return "short_snippet"
    return None


def prefilter_hits(
    hits: Sequence[SearchHit], policy: PrefilterPolicy
) -> tuple[list[SearchHit], list[Rejected]]:
    """Unwrap tracking redirects, then drop hits the *policy* rejects.

    Checks run in this order and the first failure wins: unparsable URL,
    scheme outside the allowlist, blocked domain, empty title/snippet, short
    snippet. One bad hit never affects the others.

    Args:
        hits (Sequence[SearchHit]): Hits in rank order.
        policy (PrefilterPolicy): Limits to enforce.

    Returns:
        tuple[list[SearchHit], list[Rejected]]: Kept hits (rank order preserved,
        redirect URLs replaced by their targets) and the rejected hits with a reason.
    """
    kept: list[SearchHit] = []
    rejected: list[Rejected] = []
    for hit in hits:
        target = unwrap_redirect(hit.url)
        candidate = hit if target == hit.url else replace(hit, url=target)
        reason = _reject_reason(candidate, policy)
        if reason is None:
            kept.append(candidate)
        else:
            logger.debug("prefilter rejected %s: %s", hit.url, reason)
            rejected.append(Rejected(hit=hit, reason=reason))
    return kept, rejected


__all__ = ["RejectReason", "Rejected", "prefilter_hits", "unwrap_redirect"]
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run --no-project --with pytest --with pyyaml --with httpx python -m pytest tests/test_prefilter.py -q --tb=short`
Expected: 19 passed.

---

### Task 4: Hit normalization and near-dedupe

**Files:**

- Create: `frontend/hits.py`
- Create: `tests/test_hits.py`

**Interfaces:**

- Consumes: `SearchHit` (with `also_from`), `normalize_text` from `WebSearch.backend.normalize`.
- Produces: `normalize_hit(hit: SearchHit) -> SearchHit`; `near_dedupe(hits: Sequence[SearchHit], *, max_distance: int = 6) -> list[SearchHit]`. Default `6` was measured on 64-bit SimHashes of short title+snippet text: an appended word gives distance 5, a swapped phrase 9, an unrelated hit 29.

- [ ] **Step 1: Write the failing test**

```python
from WebSearch.frontend import SearchHit
from WebSearch.frontend.hits import near_dedupe, normalize_hit

BASE = (
    "Python 3.14 release notes: free-threaded build, deferred annotations, "
    "t-strings, and a new zstd compression module for the standard library"
)


def _hit(
    title: str = "Title",
    snippet: str = "snippet",
    url: str = "https://example.com/a",
    searcher_id: str = "brave",
) -> SearchHit:
    return SearchHit(title=title, url=url, snippet=snippet, searcher_id=searcher_id)


def test_normalize_cleans_title_and_snippet() -> None:
    hit = normalize_hit(_hit(title="  Café &amp; Bar​  ", snippet="a  b\n\na b"))
    assert (hit.title, hit.snippet) == ("Café & Bar", "a b")


def test_site_suffix_is_stripped_when_it_names_the_host() -> None:
    hit = normalize_hit(_hit(title="Intro to asyncio | Example", url="https://www.example.com/a"))
    assert hit.title == "Intro to asyncio"


def test_site_suffix_with_spaces_and_dash_variants() -> None:
    hit = normalize_hit(
        _hit(title="Best answer – Stack Overflow", url="https://stackoverflow.com/q/1")
    )
    assert hit.title == "Best answer"


def test_site_suffix_matches_a_subdomain_label() -> None:
    hit = normalize_hit(
        _hit(title="asyncio - Python", url="https://docs.python.org/3/library/asyncio.html")
    )
    assert hit.title == "asyncio"


def test_other_separator_text_is_kept() -> None:
    hit = normalize_hit(_hit(title="Pros | Cons of rust", url="https://example.com/a"))
    assert hit.title == "Pros | Cons of rust"


def test_title_that_is_only_a_suffix_is_kept() -> None:
    hit = normalize_hit(_hit(title="| Example", url="https://example.com/a"))
    assert hit.title == "| Example"


def test_normalize_handles_empty_and_non_ascii() -> None:
    hit = normalize_hit(_hit(title="", snippet="日本語のテキスト"))
    assert (hit.title, hit.snippet) == ("", "日本語のテキスト")


def test_near_dedupe_merges_identical_text_and_records_other_searchers() -> None:
    first = _hit(BASE, "", "https://a.example/1", "brave")
    second = _hit(BASE, "", "https://b.example/2", "tavily")
    third = _hit(BASE, "", "https://c.example/3", "tavily")
    out = near_dedupe([first, second, third])
    assert [h.url for h in out] == ["https://a.example/1"]
    assert out[0].also_from == ("tavily",)


def test_near_dedupe_same_searcher_is_not_listed_in_also_from() -> None:
    out = near_dedupe(
        [_hit(BASE, "", "https://a.example/1"), _hit(BASE, "", "https://b.example/2")]
    )
    assert len(out) == 1
    assert out[0].also_from == ()


def test_near_dedupe_merges_a_lightly_edited_copy() -> None:
    edited = _hit(BASE + " today", "", "https://b.example/2", "tavily")
    out = near_dedupe([_hit(BASE, "", "https://a.example/1"), edited])
    assert [h.url for h in out] == ["https://a.example/1"]


def test_near_dedupe_keeps_a_different_hit() -> None:
    other = _hit(
        "How to bake sourdough bread at home with a cast iron dutch oven and a long cold proof",
        "",
        "https://b.example/2",
    )
    out = near_dedupe([_hit(BASE, "", "https://a.example/1"), other])
    assert len(out) == 2


def test_near_dedupe_never_merges_short_texts() -> None:
    out = near_dedupe(
        [_hit("Python", "", "https://a.example/1"), _hit("Python", "", "https://b.example/2")]
    )
    assert len(out) == 2


def test_near_dedupe_zero_distance_keeps_an_edited_copy() -> None:
    edited = _hit(BASE + " today", "", "https://b.example/2", "tavily")
    assert len(near_dedupe([_hit(BASE, "", "https://a.example/1"), edited], max_distance=0)) == 2


def test_near_dedupe_handles_empty_input() -> None:
    assert near_dedupe([]) == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --no-project --with pytest --with pyyaml --with httpx python -m pytest tests/test_hits.py -q --tb=short`
Expected: ERROR at collection, `ModuleNotFoundError: No module named 'WebSearch.frontend.hits'`.

- [ ] **Step 3: Write the implementation**

```python
"""Hit-level cleanup: title/snippet normalization and near-duplicate removal."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import replace
from urllib.parse import urlsplit

from WebSearch.backend.normalize import normalize_text
from WebSearch.frontend.models import SearchHit

#: " | ", " - ", en/em dash and middle dot between a title and a site name.
_SEPARATOR = re.compile(r"\s+[|–—·-]\s+")
_NON_ALNUM = re.compile(r"[\W_]+")
_TOKEN = re.compile(r"\w+")
_SHINGLE = 3
_BITS = 64


def _alnum(text: str) -> str:
    return _NON_ALNUM.sub("", text.casefold())


def _site_keys(url: str) -> set[str]:
    """Alphanumeric forms of the host labels (TLD excluded) and of the whole host."""
    try:
        host = (urlsplit(url).hostname or "").removeprefix("www.")
    except ValueError:
        return set()
    keys = {_alnum(label) for label in host.split(".")[:-1]}
    keys.add(_alnum(host))
    keys.discard("")
    return keys


def _strip_site_suffix(title: str, url: str) -> str:
    """Drop a trailing ``" | Site"`` when *Site* names the hit's own host."""
    matches = list(_SEPARATOR.finditer(title))
    if not matches:
        return title
    last = matches[-1]
    head, tail = title[: last.start()].rstrip(), title[last.end() :]
    return head if head and _alnum(tail) in _site_keys(url) else title


def normalize_hit(hit: SearchHit) -> SearchHit:
    """Canonicalize a hit's title and snippet.

    Both go through :func:`normalize_text`. A trailing site-name suffix is
    stripped from the title only when it matches the hit's own host, so titles
    that merely contain a separator are kept.

    Args:
        hit (SearchHit): Raw hit.

    Returns:
        SearchHit: Copy with cleaned ``title`` and ``snippet``.
    """
    title = _strip_site_suffix(normalize_text(hit.title), hit.url)
    return replace(hit, title=title, snippet=normalize_text(hit.snippet))


def _simhash(text: str) -> int | None:
    """64-bit SimHash over word 3-shingles; ``None`` when the text is too short."""
    tokens = _TOKEN.findall(text.casefold())
    if len(tokens) < _SHINGLE:
        return None
    votes = [0] * _BITS
    for start in range(len(tokens) - _SHINGLE + 1):
        digest = hashlib.blake2b(
            " ".join(tokens[start : start + _SHINGLE]).encode(), digest_size=_BITS // 8
        ).digest()
        value = int.from_bytes(digest, "big")
        for bit in range(_BITS):
            votes[bit] += 1 if (value >> bit) & 1 else -1
    return sum(1 << bit for bit, vote in enumerate(votes) if vote > 0)


def near_dedupe(hits: Sequence[SearchHit], *, max_distance: int = 6) -> list[SearchHit]:
    """Drop hits whose title+snippet is a near-duplicate of an earlier hit.

    Similarity is the Hamming distance between 64-bit SimHashes. Hits with
    fewer than three words carry too little signal and are never merged. The
    earlier (better-ranked) hit survives and records the searcher ids of the
    hits merged into it in ``also_from``.

    Args:
        hits (Sequence[SearchHit]): Hits in rank order.
        max_distance (int): Largest Hamming distance counted as a duplicate.

    Returns:
        list[SearchHit]: Hits with near-duplicates removed, order preserved.
    """
    kept: list[SearchHit] = []
    prints: list[int | None] = []
    merged: list[list[str]] = []
    for hit in hits:
        fingerprint = _simhash(f"{hit.title} {hit.snippet}")
        match = None
        if fingerprint is not None:
            match = next(
                (
                    index
                    for index, other in enumerate(prints)
                    if other is not None and (fingerprint ^ other).bit_count() <= max_distance
                ),
                None,
            )
        if match is None:
            kept.append(hit)
            prints.append(fingerprint)
            merged.append([])
        elif hit.searcher_id != kept[match].searcher_id and hit.searcher_id not in merged[match]:
            merged[match].append(hit.searcher_id)
    return [
        replace(hit, also_from=(*hit.also_from, *ids)) if ids else hit
        for hit, ids in zip(kept, merged, strict=True)
    ]


__all__ = ["near_dedupe", "normalize_hit"]
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run --no-project --with pytest --with pyyaml --with httpx python -m pytest tests/test_hits.py -q --tb=short`
Expected: all pass (14 tests).

---

### Task 5: Wire the stages into `parallel_search`

**Files:**

- Modify: `frontend/websearchers.py`
- Modify: `frontend/__init__.py`
- Modify: `agent_tools.py` (docstring only)
- Modify: `README.md`
- Create: `tests/test_pipeline.py`

**Interfaces:**

- Consumes: everything from Tasks 1-4.
- Produces: `parallel_search(..., fuse=True, near_distance: int | None = 6, sink: ResultSink | None = None)`. Order: prefilter each provider batch with `config.prefilter`, RRF fuse, URL dedupe, `normalize_hit`, `near_dedupe` (skipped when `near_distance is None`), cap to `limit`, move the summed `api_tokens` onto the first hit, then `sink.store(hits)` when there are hits (`OSError` logged, others propagate). New package exports: `NullSink`, `PrefilterPolicy`, `ResultSink`, `SinkReport`, `near_dedupe`, `normalize_hit`, `prefilter_hits`.

- [ ] **Step 1: Write the failing test**

```python
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from WebSearch.frontend import SearchHit, parallel_search
from WebSearch.frontend.models import SinkReport
from WebSearch.frontend.providers import PrefilterPolicy, ProvidersConfig, SearcherSpec

ROOT = Path(__file__).resolve().parents[1]


def _config(*ids: str, policy: PrefilterPolicy | None = None) -> ProvidersConfig:
    return ProvidersConfig(
        version=1,
        searchers=tuple(SearcherSpec(id=i, kind="websearcher") for i in ids),
        extractor_order=("regex",),
        prefilter=policy or PrefilterPolicy(),
    )


def _backend(hits: Sequence[SearchHit]):
    return lambda query, spec: [replace(h, searcher_id=spec.id) for h in hits]


def _hit(
    url: str, title: str = "Some title", snippet: str = "a reasonably long snippet", tokens: int = 0
) -> SearchHit:
    return SearchHit(title=title, url=url, snippet=snippet, searcher_id="x", api_tokens=tokens)


class _RecordingSink:
    def __init__(self) -> None:
        self.calls: list[list[SearchHit]] = []

    def store(self, hits: Sequence[SearchHit]) -> SinkReport:
        self.calls.append(list(hits))
        return SinkReport(stored=len(hits))


class _FailingSink:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def store(self, hits: Sequence[SearchHit]) -> SinkReport:
        raise self.error


def test_junk_hit_returned_by_two_providers_does_not_outrank_a_clean_hit() -> None:
    junk, clean = _hit("https://spam.example/x"), _hit("https://good.example/y")
    cfg = _config("a", "b", policy=PrefilterPolicy(blocked_domains=("spam.example",)))
    backends = {"a": _backend([junk, clean]), "b": _backend([junk])}
    assert [h.url for h in parallel_search("q", config=cfg, backends=backends)] == [
        "https://good.example/y"
    ]


def test_all_hits_rejected_returns_empty_and_skips_the_sink() -> None:
    sink = _RecordingSink()
    cfg = _config("a", policy=PrefilterPolicy(schemes=("ftp",)))
    assert (
        parallel_search(
            "q", config=cfg, backends={"a": _backend([_hit("https://a.example")])}, sink=sink
        )
        == []
    )
    assert sink.calls == []


def test_titles_are_normalized_and_near_duplicates_removed_before_the_cap() -> None:
    dup_a = _hit(
        "https://a.example/1",
        title="Python 3.14 release notes free-threaded build and t-strings overview",
        snippet="",
    )
    dup_b = _hit(
        "https://b.example/2",
        title="Python 3.14 release notes free-threaded build and t-strings overview",
        snippet="",
    )
    other = _hit(
        "https://c.example/3",
        title="Sourdough bread with a cast iron dutch oven overnight",
        snippet="",
    )
    out = parallel_search(
        "q", config=_config("a"), backends={"a": _backend([dup_a, dup_b, other])}, limit=2
    )
    assert [h.url for h in out] == ["https://a.example/1", "https://c.example/3"]


def test_near_distance_none_disables_near_dedupe() -> None:
    twin = "Python 3.14 release notes free-threaded build and t-strings overview"
    hits = [
        _hit("https://a.example/1", title=twin, snippet=""),
        _hit("https://b.example/2", title=twin, snippet=""),
    ]
    out = parallel_search(
        "q", config=_config("a"), backends={"a": _backend(hits)}, near_distance=None
    )
    assert len(out) == 2


def test_sink_receives_the_final_capped_list() -> None:
    sink = _RecordingSink()
    hits = [
        _hit(f"https://h{i}.example/", title=f"Distinct result number {i} about topic {i}")
        for i in range(4)
    ]
    out = parallel_search(
        "q", config=_config("a"), backends={"a": _backend(hits)}, limit=2, sink=sink
    )
    assert sink.calls == [out]
    assert len(out) == 2


def test_sink_oserror_still_returns_results() -> None:
    out = parallel_search(
        "q",
        config=_config("a"),
        backends={"a": _backend([_hit("https://a.example/")])},
        sink=_FailingSink(OSError("disk full")),
    )
    assert [h.url for h in out] == ["https://a.example/"]


def test_sink_programming_error_propagates() -> None:
    with pytest.raises(ValueError, match="bug"):
        parallel_search(
            "q",
            config=_config("a"),
            backends={"a": _backend([_hit("https://a.example/")])},
            sink=_FailingSink(ValueError("bug")),
        )


def test_api_tokens_total_survives_prefilter_and_sits_on_the_first_hit() -> None:
    rejected_head = _hit("https://spam.example/x", tokens=30)
    kept = _hit("https://good.example/y", tokens=0)
    cfg = _config("a", "b", policy=PrefilterPolicy(blocked_domains=("spam.example",)))
    backends = {
        "a": _backend([rejected_head, kept]),
        "b": _backend(
            [
                replace(
                    _hit(
                        "https://other.example/z", title="A completely different page about bread"
                    ),
                    api_tokens=12,
                )
            ]
        ),
    }
    out = parallel_search("q", config=cfg, backends=backends)
    assert sum(h.api_tokens for h in out) == 42
    assert out[0].api_tokens == 42


@pytest.mark.parametrize("first", ["frontend", "backend"])
def test_either_package_can_be_imported_first(first: str) -> None:
    code = (
        "import sys; sys.path.insert(0, 'tests'); import conftest; "
        f"import WebSearch.{first}; import WebSearch.frontend, WebSearch.backend"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --no-project --with pytest --with pyyaml --with httpx python -m pytest tests/test_pipeline.py -q --tb=short`
Expected: FAIL/ERROR: `parallel_search() got an unexpected keyword argument 'sink'` and junk-hit tests failing.

- [ ] **Step 3: Apply the pipeline change and exports**

```bash
git apply <<'PATCH'
--- a/frontend/websearchers.py
+++ b/frontend/websearchers.py
@@ -5,8 +5,11 @@
 import logging
 from collections.abc import Mapping, Sequence
 from concurrent.futures import ThreadPoolExecutor, as_completed
+from dataclasses import replace

-from WebSearch.frontend.models import SearchFn, SearchHit, dedupe_hits
+from WebSearch.frontend.hits import near_dedupe, normalize_hit
+from WebSearch.frontend.models import ResultSink, SearchFn, SearchHit, dedupe_hits
+from WebSearch.frontend.prefilter import prefilter_hits
 from WebSearch.frontend.providers import ProvidersConfig, SearcherSpec, load_providers
 from WebSearch.urls import normalize_url

@@ -117,6 +120,8 @@
     timeout_s: float = 30.0,
     limit: int = 0,
     fuse: bool = True,
+    near_distance: int | None = 6,
+    sink: ResultSink | None = None,
 ) -> list[SearchHit]:
     """Send one ``query`` to every configured searcher at once and merge the hits.

@@ -124,9 +129,14 @@
     error contributes no hits and does not affect the others. If the overall
     ``timeout_s`` budget expires, unfinished searchers are abandoned and the
     finished batches still answer. Merged hits are consensus-ranked (RRF across
-    per-provider rankings) unless ``fuse=False`` keeps plain YAML order, then
-    deduplicated by canonical URL and capped to ``limit`` (0 = no cap).
+    per-provider rankings) unless ``fuse=False`` keeps plain YAML order.

+    Each provider's batch is prefiltered first (``config.prefilter``) so junk
+    cannot gain rank from consensus. After fusion the hits are deduplicated by
+    canonical URL, normalized, near-deduplicated, capped to ``limit`` (0 = no
+    cap) and handed to ``sink``. A sink that raises ``OSError`` is logged and
+    the hits are still returned.
+
     Args:
         query (str): User query (a dork string works as-is).
         config (ProvidersConfig | None): Registry; default ``load_providers()``.
@@ -138,6 +148,9 @@
         limit (int): Max merged hits; ``0`` returns everything.
         fuse (bool): RRF consensus ranking across providers (default) instead
             of raw YAML-order concatenation.
+        near_distance (int | None): Largest SimHash Hamming distance counted
+            as a near-duplicate; ``None`` disables near-dedupe.
+        sink (ResultSink | None): Receives the final hits when there are any.

     Returns:
         list[SearchHit]: Unique hits from all searchers, best first.
@@ -177,9 +190,30 @@
     finally:
         executor.shutdown(wait=False)
     batches = [by_index[index] for index in sorted(by_index)]
-    merged = _rrf_fuse(batches) if fuse else [hit for batch in batches for hit in batch]
-    hits = dedupe_hits(merged)
-    return hits[:limit] if limit and limit > 0 else hits
+    api_tokens = sum(hit.api_tokens for batch in batches for hit in batch)
+    clean = [prefilter_hits(batch, cfg.prefilter)[0] for batch in batches]
+    merged = _rrf_fuse(clean) if fuse else [hit for batch in clean for hit in batch]
+    hits = [normalize_hit(hit) for hit in dedupe_hits(merged)]
+    if near_distance is not None:
+        hits = near_dedupe(hits, max_distance=near_distance)
+    if limit and limit > 0:
+        hits = hits[:limit]
+    if hits and api_tokens:
+        hits = [replace(hit, api_tokens=0) for hit in hits]
+        hits[0] = replace(hits[0], api_tokens=api_tokens)
+    if sink is not None and hits:
+        _store(sink, hits)
+    return hits


+def _store(sink: ResultSink, hits: Sequence[SearchHit]) -> None:
+    """Hand *hits* to *sink*; a transient I/O failure never loses the search."""
+    try:
+        report = sink.store(hits)
+    except OSError:
+        logger.exception("result sink failed; returning hits unstored")
+        return
+    logger.debug("sink stored=%d skipped=%d %s", report.stored, report.skipped, report.detail)
+
+
 __all__ = ["_rrf_fuse", "parallel_search", "registry_search", "searcher_ids"]
PATCH
```

```bash
git apply <<'PATCH'
--- a/frontend/__init__.py
+++ b/frontend/__init__.py
@@ -4,11 +4,21 @@

 from WebSearch.frontend.apis import builtin_searchers
 from WebSearch.frontend.dorks import DorkError, any_of, dork
-from WebSearch.frontend.models import SearchFn, SearchHit, dedupe_hits
+from WebSearch.frontend.hits import near_dedupe, normalize_hit
+from WebSearch.frontend.models import (
+    NullSink,
+    ResultSink,
+    SearchFn,
+    SearchHit,
+    SinkReport,
+    dedupe_hits,
+)
+from WebSearch.frontend.prefilter import prefilter_hits
 from WebSearch.frontend.providers import (
     CrawlerName,
     CrawlSpec,
     ExtractorName,
+    PrefilterPolicy,
     ProvidersConfig,
     SearcherSpec,
     get_searcher,
@@ -21,17 +31,24 @@
     "CrawlSpec",
     "DorkError",
     "ExtractorName",
+    "NullSink",
+    "PrefilterPolicy",
     "ProvidersConfig",
+    "ResultSink",
     "SearchFn",
     "SearchHit",
     "SearcherSpec",
+    "SinkReport",
     "any_of",
     "builtin_searchers",
     "dedupe_hits",
     "dork",
     "get_searcher",
     "load_providers",
+    "near_dedupe",
+    "normalize_hit",
     "parallel_search",
+    "prefilter_hits",
     "registry_search",
     "searcher_ids",
 ]
PATCH
```

- [ ] **Step 4: Reword the one docstring that named a consumer, and document the feature**

```bash
git apply <<'PATCH'
--- a/agent_tools.py
+++ b/agent_tools.py
@@ -1,6 +1,6 @@
 """Agent-facing search tooling: one query in, one token-lean brief out.

-Wraps the multi-provider pipeline for swarm agents: parallel search across
+Wraps the multi-provider pipeline for LLM agents: parallel search across
 every configured provider, consensus-ranked (RRF), deduplicated by canonical
 URL, then rendered as a numbered brief sized for a prompt budget. Agents that
 prefer structured data use :func:`search_hits`; agents that want to paste
PATCH
```

````bash
git apply <<'PATCH'
--- a/README.md
+++ b/README.md
@@ -18,6 +18,10 @@

 One query fans out to **every** configured searcher in parallel (`parallel_search`, threads). Batches are assembled in YAML order (deterministic regardless of completion timing), then **fused with reciprocal-rank fusion**: a URL found by several providers outranks one found by a single provider; `fuse=False` restores raw YAML-order concatenation. Results are deduplicated by canonical URL (`www.`, fragments, trailing `/`, `utm_*`/`gclid` ignored) and capped with `limit`. The whole fan-out runs under one wall-clock budget (`timeout_s`, default 30): slow searchers are abandoned and the finished batches still answer, so a hung provider can never stall an agent. `run_pipeline(query, parallel=False)` restores ordered failover (first searcher with hits wins). A failing searcher contributes no hits and never blocks the others.

+### Result cleanup
+
+Before fusion each provider's batch passes a **prefilter** (`prefilter:` block in `providers.yaml`: scheme allowlist, `blocked_domains`, `min_snippet_chars`, `require_title`; Google `/url?q=` redirects are unwrapped). Rejected hits never reach RRF, so junk cannot win on consensus. After URL dedupe, titles and snippets are normalized (site-name suffixes such as `" | Example"` are stripped only when they name the hit's own host) and **near-duplicates** (SimHash over title + snippet, `near_distance=6`, `None` disables) are merged; the survivor lists the other searcher ids in `also_from`. Pass `sink=` (any object with `store(hits) -> SinkReport`) to `parallel_search` to receive the final hits, for example to index them; a sink that raises `OSError` is logged and the hits are still returned. The API token total of the call sits on the first hit.
+
 ### Agent tooling

 ```python
PATCH
````

- [ ] **Step 5: Run the whole suite**

Run: `uv run --no-project --with pytest --with pyyaml --with httpx python -m pytest tests -q --tb=short`
Expected: 50 passed.

- [ ] **Step 6: Run the gate**

```bash
ruff format --line-length 100 --target-version py314 --check tests frontend/prefilter.py frontend/hits.py frontend/models.py frontend/websearchers.py
ruff check --line-length 100 --target-version py314 --select E,F,I,UP --config 'lint.isort.known-first-party=["WebSearch"]' tests frontend agent_tools.py
python3 -m compileall -q .
```

Expected: `N files already formatted`, `All checks passed!`, no compileall output.

- [ ] **Step 7: Verify the stages matter (mutation check)** in a scratch copy, not in the worktree: remove the prefilter call, then the `near_dedupe` call, then the token move, and confirm each makes at least one test fail (measured while writing this plan: 2, 1 and 1 failures).

- [ ] **Step 8: Report status without committing**

Run: `git status --short`
Expected: new `docs/superpowers/plans/`, `tests/`, `frontend/prefilter.py`, `frontend/hits.py`; modified `README.md`, `agent_tools.py`, `frontend/__init__.py`, `frontend/models.py`, `frontend/providers.py`, `frontend/websearchers.py`, `providers.yaml`, the spec, plus the pre-existing WIP files. Hand the list to the owner; they choose how to commit around the pre-existing WIP.
