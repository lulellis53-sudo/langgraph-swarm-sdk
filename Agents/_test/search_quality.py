"""Search-quality benchmark: hits, query cost, dedupe and prefilter scoring.

Runs **offline and deterministically**: no network, no API keys. Fixtures model
the shapes the live lane actually sees (title/snippet/url per searcher, with
planted duplicates and planted junk) so the scoring is reproducible and can be
used as a regression gate.

Metrics, per searcher and merged:

* ``hits`` / ``unique``   — raw hits and hits surviving near-dedupe.
* ``dup_pct``             — share of raw hits that were near-duplicates.
* ``kept_pct``            — share of hits surviving the prefilter.
* ``tokens``              — **tiktoken** count over the text a caller would
                            actually receive (title + snippet, or the scraped
                            page when present). This is the cost metric; it is
                            measured with the same encoder the SDK budgets with.
* ``score`` (0-1)         — mean relevance of the kept hits against the query,
                            from term coverage weighted by inverse term rarity.
* ``good_score``          — share of kept hits scoring at or above
                            ``--good-threshold`` (default 0.5), i.e. "did the
                            search actually find good results".
* ``dup_score``           — dedupe effectiveness: of the duplicates the fixture
                            planted, the share that were merged. 1.0 is perfect.
* ``prefilter_score``     — of the junk the fixture planted, the share rejected.
* ``q_per_find``          — queries issued per *good* hit found. This is the
                            headline efficiency number: lower is better.
* ``tokens_per_good``     — tokens spent per good hit.

Usage (from the BotDeal worktree, which has tiktoken):

    PYTHONPATH="$HOME/BotDeal" ./.venv/bin/python \
        Agents/benchmark/search_quality.py --repeat 5

Exit status is non-zero when a metric regresses past ``--max-regression``
against a saved baseline, so this can gate CI.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --- locate the WebSearch package ---------------------------------------------
# The package is provided by a worktree (this file lives under Agents/benchmark,
# not at a root that already has WebSearch importable), so add the likely roots
# before importing it. This keeps the script runnable from any cwd.
_REPO = Path(__file__).resolve().parents[2]
for _candidate in (_REPO, _REPO / "WebSearch", Path.home() / "Myworkspace" / "Swarm-WebSearch"):
    if (_candidate / "WebSearch" / "__init__.py").is_file() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

# --- dependencies: tiktoken is the encoder the SDK budget uses ----------------
try:
    import tiktoken
except ImportError:  # pragma: no cover - guidance only
    print(
        "tiktoken is required (it is what the SDK counts tokens with).\n"
        'Run from the BotDeal worktree: PYTHONPATH="$HOME/BotDeal" '
        "./.venv/bin/python Agents/benchmark/search_quality.py",
        file=sys.stderr,
    )
    raise SystemExit(2)

from WebSearch.backend.prefilter import prefilter_hits  # noqa: E402
from WebSearch.frontend.hits import near_dedupe, normalize_hit  # noqa: E402
from WebSearch.frontend.websearchers import (  # noqa: E402
    PrefilterPolicy,
    SearchHit,
)

RESULTS_DIR = Path(__file__).resolve().parent / "results" / "search_quality"
BASELINE = RESULTS_DIR / "baseline.json"

#: Encoder used for every token figure. ``cl100k_base`` is the SDK default.
ENCODING = "cl100k_base"


@dataclass(frozen=True, slots=True)
class Fixture:
    """One searcher's response to one query, with planted cases.

    Duplicates are planted in two kinds because the code under test treats them
    very differently, and collapsing them into one number would hide that:

    ``planted_text_dupes``
        Same title+snippet text, so the SimHash matches and dedupe *should* merge.
    ``planted_url_dupes``
        Same final URL but a re-syndicated title. Dedupe hashes title+snippet
        only, so this kind is currently never merged.
    """

    tool: str
    hits: tuple[SearchHit, ...]
    #: Indices whose title+snippet text duplicates an earlier searcher's hit.
    planted_text_dupes: frozenset[int] = field(default_factory=frozenset)
    #: Indices whose URL duplicates an earlier searcher's hit but title differs.
    planted_url_dupes: frozenset[int] = field(default_factory=frozenset)
    #: Indices that violate the prefilter policy (used to score prefilter recall).
    planted_junk: frozenset[int] = field(default_factory=frozenset)
    #: Queries this searcher was asked (cost numerator).
    queries: int = 1


def _hit(tool: str, title: str, url: str, snippet: str, tokens: int = 0) -> SearchHit:
    return SearchHit(title=title, url=url, snippet=snippet, searcher_id=tool, api_tokens=tokens)


# --- fixtures -----------------------------------------------------------------
# A "python 3.14 free-threading" style query against three searchers. The
# duplicates are realistic: the same page syndicated to two hosts, and the same
# announcement re-titled by a second engine.

QUERY = "python free threading gil disabled"

_GOOD = (
    "PEP 703: making the GIL optional in CPython",
    "https://peps.python.org/pep-0703/",
    "The Global Interpreter Lock becomes optional. Builds with --disable-gil "
    "run threads in parallel; measured 4.2x scaling on 8 cores.",
)
_GOOD2 = (
    "Free-threaded CPython: how to build and test it",
    "https://docs.python.org/3/howto/free-threading-python.html",
    "Build CPython with --disable-gil to disable the GIL. C extensions must "
    "declare Py_MOD_GIL_NOT_USED or the GIL is re-enabled at import.",
)
_GOOD3 = (
    "Measuring free-threaded scaling: benchmark methodology",
    "https://pyfound.blogspot.com/free-threading-benchmarks",
    "Thread scaling for CPU-bound Python code improves roughly linearly until "
    "memory bandwidth saturates; author reports 5.8x on 8 threads.",
)
_DUP_A = (
    "Free-threaded CPython: build and test",
    "https://mirror.example.org/free-threading-python.html",
    "Build CPython with --disable-gil to disable the GIL. C extensions must "
    "declare Py_MOD_GIL_NOT_USED or the GIL is re-enabled at import.",
)
_DUP_B = (
    "documents.python.org: free-threading python",
    "https://docs.python.org/3/howto/free-threading-python.html",
    "Build CPython with --disable-gil to disable the GIL. C extensions must "
    "declare Py_MOD_GIL_NOT_USED or the GIL is re-enabled at import.",
)
#: A pure TEXT duplicate: identical title+snippet text published on a DIFFERENT
#: host, so URL dedupe cannot see it and only SimHash text dedupe can. Without
#: this, the A/B cannot distinguish url-only from url+text, because the other
#: duplicate pairs happen to share a URL as well.
_MIRROR = (
    "Free-threaded CPython: how to build and test it",
    "https://mirror-b.example.org/howto/free-threading-python.html",
    "Build CPython with --disable-gil to disable the GIL. C extensions must "
    "declare Py_MOD_GIL_NOT_USED or the GIL is re-enabled at import.",
)
_OFFTOPIC = (
    "How to disable threading in Django tests",
    "https://example.com/django-threads",
    "Setting the GIL aside, Django tests can run without parallel workers by "
    "passing --parallel 1; unrelated to CPython free-threading work.",
)
_JUNK_EMPTY_TITLE = ("", "https://spam.example.net/x", "click here for free stuff")
_JUNK_SHORT = ("py", "https://spam.example.net/y", "hi")
_JUNK_SCHEME = ("ftp download", "ftp://files.example.net/py314", "ftp mirror for python")

FIXTURES: tuple[Fixture, ...] = (
    Fixture(
        tool="tavily",
        hits=(
            _hit("tavily", *_GOOD),
            _hit("tavily", *_GOOD2),
            _hit("tavily", *_OFFTOPIC),
            _hit("tavily", *_JUNK_SHORT),
        ),
        planted_junk=frozenset({3}),
    ),
    Fixture(
        tool="ddglite",
        hits=(
            _hit("ddglite", *_GOOD3),
            _hit("ddglite", *_DUP_A),
            _hit("ddglite", *_JUNK_EMPTY_TITLE),
        ),
        # NOT a duplicate of anything: _DUP_A's text is a near-paraphrase of
        # _GOOD2 (measured SimHash distance 13), which is correctly above the
        # merge threshold of 6. Kept here so the run exercises "similar but not
        # duplicate" and cannot be mistaken for a dedupe failure.
        planted_junk=frozenset({2}),
    ),
    Fixture(
        tool="exa",
        hits=(
            _hit("exa", *_DUP_B),
            _hit("exa", *_JUNK_SCHEME),
            _hit("exa", *_GOOD),
        ),
        # _GOOD is byte-identical to tavily's hit 0 (SimHash distance 0).
        planted_text_dupes=frozenset({2}),
        # _DUP_B shares _GOOD2's final URL with a re-syndicated title.
        planted_url_dupes=frozenset({0}),
        planted_junk=frozenset({1}),
    ),
    Fixture(
        tool="brave",
        hits=(
            _hit("brave", *_MIRROR),
            _hit("brave", *_GOOD2),
        ),
        # _MIRROR is the SAME TEXT as tavily's _GOOD2 on a different host. Only
        # text dedupe can catch it; URL dedupe sees two distinct URLs. This is
        # the case that makes the A/B able to tell the variants apart.
        planted_text_dupes=frozenset({0}),
    ),
)

POLICY = PrefilterPolicy(
    schemes=("http", "https"),
    blocked_domains=(),
    min_snippet_chars=20,
    require_title=True,
)


# --- scoring ------------------------------------------------------------------
def _terms(text: str) -> set[str]:
    return {t for t in "".join(c if c.isalnum() else " " for c in text.casefold()).split() if t}


def _idf(doc_terms: list[set[str]]) -> dict[str, float]:
    """Inverse document frequency across the fixture corpus."""
    total = len(doc_terms) or 1
    counts: dict[str, int] = {}
    for terms in doc_terms:
        for term in terms:
            counts[term] = counts.get(term, 0) + 1
    return {term: (1 + total / (1 + n)) for term, n in counts.items()}


def _score(hit: SearchHit, query_terms: set[str], idf: dict[str, float]) -> float:
    """Relevance in 0-1: query terms present, weighted by rarity, length-normalized."""
    if not query_terms:
        return 0.0
    haystack = _terms(f"{hit.title} {hit.snippet}")
    matched = query_terms & haystack
    if not matched:
        return 0.0
    weight = sum(idf.get(t, 1.0) for t in matched)
    ceiling = sum(idf.get(t, 1.0) for t in query_terms)
    return weight / ceiling if ceiling else 0.0


def count_tokens(text: str) -> int:
    """Token count with the SDK's encoder, so budget comparisons line up."""
    return len(tiktoken.get_encoding(ENCODING).encode(text))


def _all_hits() -> list[SearchHit]:
    out: list[SearchHit] = []
    for fixture in FIXTURES:
        out.extend(fixture.hits)
    return out


def _fixture_sanity() -> list[str]:
    """Verify the fixtures can actually exercise what the metrics claim.

    Guards against the failure this file already hit once: planting duplicates
    in a place the code under test cannot observe, which yields a confident
    ``0.0`` score that looks like a real finding. Each check asserts the
    fixture contains at least one detectable case.
    """
    problems: list[str] = []
    normalized = [normalize_hit(h) for f in FIXTURES for h in f.hits]
    if len(near_dedupe(normalized)) >= len(normalized):
        problems.append(
            "no planted text duplicate is detectable by near_dedupe: dup_score would be 0 "
            "for fixture reasons, not code reasons"
        )
    kept, rejected = prefilter_hits([h for f in FIXTURES for h in f.hits], POLICY)
    if not rejected:
        problems.append("no planted hit is rejected by prefilter_hits: prefilter_score is vacuous")
    if not kept:
        problems.append("prefilter rejects every hit: the policy is misconfigured")
    if not any(_score(h, _terms(QUERY), {t: 1.0 for t in _terms(QUERY)}) > 0 for h in kept):
        problems.append("no hit matches any query term: mean_score is vacuous")
    return problems


def run_once(*, good_threshold: float = 0.5) -> dict[str, Any]:
    """Score one pass over the fixtures. Pure function of the fixtures.

    Dedupe is scored on the **merged** set, because that is where
    :func:`near_dedupe` runs in the pipeline: duplicates arrive from *different*
    searchers, so scoring it per-searcher would find nothing by construction.
    Prefilter is scored per-searcher, since it runs on each searcher's own
    response before fusion.
    """
    query_terms = _terms(QUERY)
    corpus = [_terms(f"{h.title} {h.snippet}") for h in _all_hits()]
    idf = _idf(corpus)

    planted_junk = sum(len(f.planted_junk) for f in FIXTURES)

    rows: list[dict[str, Any]] = []
    kept_all: list[SearchHit] = []
    rejected_all: list[Any] = []

    for fixture in FIXTURES:
        raw = list(fixture.hits)
        kept, rejected = prefilter_hits(raw, POLICY)
        scores = [_score(h, query_terms, idf) for h in kept]
        good = [s for s in scores if s >= good_threshold]

        rejected_hits = {id(r.hit) for r in rejected}
        junk_caught = sum(1 for i in fixture.planted_junk if id(raw[i]) in rejected_hits)
        tokens = sum(count_tokens(f"{h.title}\n{h.snippet}") for h in kept)
        rows.append(
            {
                "tool": fixture.tool,
                "hits": len(raw),
                "kept": len(kept),
                "kept_pct": round(100 * len(kept) / len(raw), 1) if raw else 0.0,
                "tokens": tokens,
                "mean_score": round(statistics.mean(scores), 3) if scores else 0.0,
                "good_hits": len(good),
                "queries": fixture.queries,
                "q_per_find": round(fixture.queries / len(good), 2) if good else None,
                "tokens_per_good": round(tokens / len(good)) if good else None,
                "prefilter_recall": (
                    round(junk_caught / len(fixture.planted_junk), 3)
                    if fixture.planted_junk
                    else None
                ),
            }
        )
        kept_all.extend(kept)
        rejected_all.extend(rejected)

    # --- merged stage: normalize then near-dedupe, as the pipeline does --------
    normalized = [normalize_hit(h) for h in kept_all]
    merged_all = near_dedupe(normalized)
    surviving_urls = [h.url for h in merged_all]
    surviving_pairs = {(h.searcher_id, h.url) for h in merged_all}

    # Text duplicates: caught when that specific (searcher, url) entry is gone
    # from the output. Testing the URL alone is wrong here, because the hit that
    # SURVIVES a merge keeps the same URL as the duplicate it absorbed.
    text_dupes = [(f, i) for f in FIXTURES for i in f.planted_text_dupes]
    text_caught = sum(
        1 for f, i in text_dupes if (f.hits[i].searcher_id, f.hits[i].url) not in surviving_pairs
    )

    # URL duplicates: a duplicate survives if its url still appears more than
    # once in the output, i.e. dedupe did not collapse same-page hits whose
    # titles differ. Reported separately because it is a real gap, not a fixture
    # artefact: near_dedupe hashes title+snippet and never looks at the url.
    from collections import Counter

    url_counts = Counter(surviving_urls)
    url_dupes = [(f, i) for f in FIXTURES for i in f.planted_url_dupes]
    url_unmerged = sum(1 for f, i in url_dupes if url_counts[f.hits[i].url] > 1)
    url_still_duplicated = sum(
        1
        for url, n in url_counts.items()
        if n > 1 and any(url == f.hits[i].url for f, i in url_dupes)
    )

    planted_junk = sum(len(f.planted_junk) for f in FIXTURES)
    junk_caught = sum(
        1
        for f in FIXTURES
        for i in f.planted_junk
        if any(id(r.hit) == id(f.hits[i]) for r in rejected_all)
    )

    merged_scores = [_score(h, query_terms, idf) for h in merged_all]
    merged_good = [s for s in merged_scores if s >= good_threshold]
    merged_tokens = sum(count_tokens(f"{h.title}\n{h.snippet}") for h in merged_all)
    total_queries = sum(f.queries for f in FIXTURES)

    planted_text_total = len(text_dupes)
    merged = {
        "raw": len(_all_hits()),
        "kept": len(kept_all),
        "unique": len(merged_all),
        "duplicates": len(kept_all) - len(merged_all),
        "tokens": merged_tokens,
        "mean_score": round(statistics.mean(merged_scores), 3) if merged_scores else 0.0,
        "good_hits": len(merged_good),
        "good_score": round(len(merged_good) / len(merged_all), 3) if merged_all else 0.0,
        "dup_score": (round(text_caught / planted_text_total, 3) if planted_text_total else None),
        "url_dup_score": (round(1 - url_unmerged / len(url_dupes), 3) if url_dupes else None),
        "url_dupes_left": url_still_duplicated,
        "prefilter_score": round(junk_caught / planted_junk, 3) if planted_junk else None,
        "q_per_find": round(total_queries / len(merged_good), 2) if merged_good else None,
        "tokens_per_good": round(merged_tokens / len(merged_good)) if merged_good else None,
    }
    return {"query": QUERY, "encoding": ENCODING, "rows": rows, "merged": merged}


# --- reporting ----------------------------------------------------------------
#: metric -> whether a smaller value is better (used for regression checks)
LOWER_IS_BETTER = {"q_per_find", "tokens_per_good", "tokens"}


def _median_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Median of each numeric metric across repeated runs (fixtures are static)."""
    first = runs[0]
    out: dict[str, Any] = {"query": first["query"], "encoding": first["encoding"]}
    out["merged"] = {
        k: (
            statistics.median([r["merged"][k] for r in runs])
            if all(isinstance(r["merged"].get(k), (int, float)) for r in runs)
            else first["merged"].get(k)
        )
        for k in first["merged"]
    }
    out["rows"] = []
    for i, row in enumerate(first["rows"]):
        packed = {}
        for key in row:
            values = [r["rows"][i][key] for r in runs]
            packed[key] = (
                statistics.median(values)
                if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values)
                else row[key]
            )
        out["rows"].append(packed)
    return out


def print_report(result: dict[str, Any]) -> None:
    """Per-searcher table plus the merged headline."""
    print()
    print(f"query: {result['query']!r}   encoder: {result['encoding']}")
    print()
    head = (
        f"{'tool':10} {'hits':>5} {'kept':>5} {'tokens':>8} "
        f"{'score':>6} {'good':>5} {'q/find':>7} {'tok/good':>9} {'preflt':>7}"
    )
    print(head)
    print("-" * len(head))
    for row in result["rows"]:
        print(
            f"{row['tool']:10} {row['hits']:>5} {row['kept']:>5} "
            f"{row['tokens']:>8} {row['mean_score']:>6.3f} "
            f"{row['good_hits']:>5} {str(row['q_per_find']):>7} "
            f"{str(row['tokens_per_good']):>9} {str(row['prefilter_recall']):>7}"
        )
    print("-" * len(head))
    m = result["merged"]
    print()
    print("merged:")
    for key, value in m.items():
        print(f"  {key:18} {value}")
    print()


def check_regression(
    result: dict[str, Any], baseline: dict[str, Any], tolerance: float
) -> list[str]:
    """Return human-readable regressions past ``tolerance`` (fraction)."""
    problems: list[str] = []
    for key, value in result["merged"].items():
        base = baseline.get("merged", {}).get(key)
        if not isinstance(value, (int, float)) or not isinstance(base, (int, float)) or not base:
            continue
        lower = key in LOWER_IS_BETTER
        change = (value - base) / base
        worse = change > tolerance if lower else change < -tolerance
        if worse:
            problems.append(f"{key}: {base} -> {value} ({change:+.1%}, tolerance {tolerance:.0%})")
    return problems


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark; optionally gate against a saved baseline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=5, help="passes; median reported")
    parser.add_argument("--good-threshold", type=float, default=0.5)
    parser.add_argument("--save-baseline", action="store_true")
    parser.add_argument("--check", action="store_true", help="compare against baseline")
    parser.add_argument("--max-regression", type=float, default=0.10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    sanity = _fixture_sanity()
    if sanity:
        print("fixture sanity check failed:", file=sys.stderr)
        for line in sanity:
            print(f"  - {line}", file=sys.stderr)
        return 2

    runs = [run_once(good_threshold=args.good_threshold) for _ in range(max(1, args.repeat))]
    result = _median_runs(runs)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "latest.json").write_text(json.dumps(result, indent=2))

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_report(result)

    status = 0
    if args.save_baseline:
        BASELINE.write_text(json.dumps(result, indent=2))
        print(f"baseline saved -> {BASELINE.relative_to(Path.cwd())}")
    if args.check:
        if not BASELINE.exists():
            print("no baseline to check against; run with --save-baseline first")
            return 1
        problems = check_regression(result, json.loads(BASELINE.read_text()), args.max_regression)
        if problems:
            print("REGRESSIONS:")
            for line in problems:
                print(f"  - {line}")
            status = 1
        else:
            print("no regressions past tolerance")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
