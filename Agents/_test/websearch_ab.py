"""A/B harness for WebSearch dedupe and prefilter strategies.

Compares named *variants* of the dedupe/prefilter stage against the same
fixtures, so a change to the pipeline can be justified with numbers instead of
intuition. Every variant is a pure function of the fixture hits; nothing
touches the network.

The variants exist because the lane ships **two complementary dedupers** and
neither alone is sufficient:

* ``url_only``   — :func:`dedupe_hits`: exact canonical-URL match.
* ``text_only``  — :func:`near_dedupe`: SimHash over title+snippet.
* ``both_*``     — the two composed, in each order.

Measured on the shared fixture set, ``url_only`` keeps 8 of 10 hits and
``text_only`` keeps 9; **only the composition reaches 8 while catching both
kinds**, because they detect different duplicates (same URL/re-titled vs
identical text/mirrored host).

Metrics per variant (same definitions as ``search_quality.py``):

* ``unique``        hits surviving dedupe — lower means more duplicates caught.
* ``dup_score``     share of *planted text* duplicates merged.
* ``url_dup_score`` share of *planted same-URL* duplicates merged.
* ``tokens``        tiktoken count of what a caller would receive afterwards.
* ``prefilter_score`` share of planted junk rejected (prefilter runs first).

Usage (from the BotDeal worktree, which has tiktoken)::

    PYTHONPATH="$HOME/BotDeal" ./.venv/bin/python \
        Agents/benchmark/websearch_ab.py --repeat 5

``--check`` compares against a saved baseline and exits non-zero on regression.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

# Import the shared fixtures/metrics from the sibling benchmark so the two
# harnesses can never drift apart in how they define a metric.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import search_quality as sq  # noqa: E402
from WebSearch.backend.prefilter import prefilter_hits  # noqa: E402
from WebSearch.frontend import dedupe_hits  # noqa: E402
from WebSearch.frontend.hits import near_dedupe, normalize_hit  # noqa: E402
from WebSearch.frontend.websearchers import SearchHit  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results" / "websearch_ab"
BASELINE = RESULTS_DIR / "baseline.json"

Dedupe = Callable[[Sequence[SearchHit]], list[SearchHit]]


def _url_only(hits: Sequence[SearchHit]) -> list[SearchHit]:
    """Canonical-URL dedupe, as the pipeline does today."""
    return dedupe_hits(hits)


def _text_only(hits: Sequence[SearchHit]) -> list[SearchHit]:
    """SimHash text dedupe, on its own."""
    return near_dedupe([normalize_hit(h) for h in hits])


def _url_then_text(hits: Sequence[SearchHit]) -> list[SearchHit]:
    """URL dedupe first, then text dedupe over the survivors."""
    return near_dedupe([normalize_hit(h) for h in dedupe_hits(hits)])


def _text_then_url(hits: Sequence[SearchHit]) -> list[SearchHit]:
    """Text dedupe first, then URL dedupe over the survivors."""
    return dedupe_hits([normalize_hit(h) for h in near_dedupe(hits)])


def _best_copy(hits: Sequence[SearchHit]) -> list[SearchHit]:
    """URL dedupe that keeps the **best** copy of a page, not the first.

    ``dedupe_hits`` keeps whichever copy arrived first, which is the searcher's
    rank order and not a relevance judgement. When the same page arrives twice
    with different titles, the first copy can score worse than the one being
    discarded: measured here, the surviving title scored 0.27 against the
    query while the dropped one scored 0.93. This variant groups by canonical
    URL and keeps the member with the highest query score, so dedupe stops
    costing relevance. It is order-independent, so it also removes the
    asymmetry between ``url_then_text`` and ``text_then_url``.
    """
    from WebSearch.backend.normalize import normalize_url

    query_terms = sq._terms(sq.QUERY)
    idf = sq._idf([sq._terms(f"{h.title} {h.snippet}") for h in hits])
    best: dict[str, SearchHit] = {}
    order: list[str] = []
    for hit in hits:
        key = normalize_url(hit.url)
        if key not in best:
            best[key] = hit
            order.append(key)
        elif sq._score(hit, query_terms, idf) > sq._score(best[key], query_terms, idf):
            # keep the more relevant copy, preserving the group's earliest slot
            keep_also = best[key].also_from
            previous = best[key]
            incoming = tuple(h.searcher_id for h in (previous,) if h.searcher_id != hit.searcher_id)
            best[key] = replace(hit, also_from=(*hit.also_from, *keep_also, *incoming))
    return [best[key] for key in order]


#: variant name -> (callable, one-line description)
VARIANTS: dict[str, tuple[Dedupe, str]] = {
    "url_only": (_url_only, "canonical URL match only (shipped today)"),
    "text_only": (_text_only, "SimHash title+snippet only"),
    "url_then_text": (_url_then_text, "URL then text (catches both kinds)"),
    "text_then_url": (_text_then_url, "text then URL (symmetric check)"),
    "best_copy": (_best_copy, "best-copy URL dedupe (order-independent)"),
}


def _survivors(
    hits: Sequence[SearchHit], dedupe: Dedupe, *, use_prefilter: bool
) -> tuple[list[SearchHit], int, int]:
    """Apply prefilter then dedupe; return (survivors, tokens, dedupe_caught).

    ``dedupe_caught`` counts hits removed *by dedupe*, measured against the
    input to dedupe. Counting against the raw list would conflate prefilter
    rejections with duplicate merges and overstate every variant equally.
    """
    if use_prefilter:
        kept, _rejected = prefilter_hits(hits, sq.POLICY)
    else:
        kept = list(hits)
    deduped = dedupe(kept)
    tokens = sum(sq.count_tokens(f"{h.title}\n{h.snippet}") for h in deduped)
    return deduped, tokens, len(kept) - len(deduped)


def _dedupe_scores(
    survivors: Sequence[SearchHit],
) -> tuple[float | None, float | None, int]:
    """Score planted text and URL duplicates against what survived.

    A text duplicate is *caught* when its specific ``(searcher_id, url)`` entry
    is absent — testing the URL alone is wrong, because the hit that survives a
    merge keeps the same URL as the duplicate it absorbed.
    """
    pairs = {(h.searcher_id, h.url) for h in survivors}
    text_dupes = [(f, i) for f in sq.FIXTURES for i in f.planted_text_dupes]
    url_dupes = [(f, i) for f in sq.FIXTURES for i in f.planted_url_dupes]

    text_caught = sum(
        1 for f, i in text_dupes if (f.hits[i].searcher_id, f.hits[i].url) not in pairs
    )
    counts = Counter(h.url for h in survivors)
    url_caught = sum(1 for f, i in url_dupes if counts[f.hits[i].url] <= 1)

    still_duplicated = sum(1 for url, n in counts.items() if n > 1)
    return (
        round(text_caught / len(text_dupes), 3) if text_dupes else None,
        round(url_caught / len(url_dupes), 3) if url_dupes else None,
        still_duplicated,
    )


def run_once(*, use_prefilter: bool = True, good_threshold: float = 0.5) -> dict[str, Any]:
    """Score every variant over the shared fixtures."""
    raw = [h for f in sq.FIXTURES for h in f.hits]
    query_terms = sq._terms(sq.QUERY)
    idf = sq._idf([sq._terms(f"{h.title} {h.snippet}") for h in raw])

    prefilter_score = None
    if use_prefilter:
        _kept, rejected = prefilter_hits(raw, sq.POLICY)
        planted = sum(len(f.planted_junk) for f in sq.FIXTURES)
        caught = sum(
            1
            for f in sq.FIXTURES
            for i in f.planted_junk
            if any(id(r.hit) == id(f.hits[i]) for r in rejected)
        )
        prefilter_score = round(caught / planted, 3) if planted else None

    rows: list[dict[str, Any]] = []
    for name, (dedupe, description) in VARIANTS.items():
        survivors, tokens, caught = _survivors(raw, dedupe, use_prefilter=use_prefilter)
        scores = [sq._score(h, query_terms, idf) for h in survivors]
        good = [s for s in scores if s >= good_threshold]
        text_score, url_score, still_dup = _dedupe_scores(survivors)
        rows.append(
            {
                "variant": name,
                "description": description,
                "unique": len(survivors),
                "dedupe_caught": caught,
                "tokens": tokens,
                "mean_score": round(statistics.mean(scores), 3) if scores else 0.0,
                "good_hits": len(good),
                "good_score": round(len(good) / len(survivors), 3) if survivors else 0.0,
                "dup_score": text_score,
                "url_dup_score": url_score,
                "url_dupes_left": still_dup,
                "prefilter_score": prefilter_score,
                "q_per_find": round(len(sq.FIXTURES) / len(good), 2) if good else None,
                "tokens_per_good": round(tokens / len(good)) if good else None,
            }
        )
    return {"query": sq.QUERY, "raw": len(raw), "encoding": sq.ENCODING, "rows": rows}


def _median_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Median of each numeric metric across repeats (fixtures are static)."""
    first = runs[0]
    out: dict[str, Any] = {k: first[k] for k in ("query", "raw", "encoding")}
    out["rows"] = []
    for i, row in enumerate(first["rows"]):
        packed: dict[str, Any] = {}
        for key in row:
            values = [r["rows"][i][key] for r in runs]
            if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
                packed[key] = statistics.median(values)
            else:
                packed[key] = row[key]
        out["rows"].append(packed)
    return out


def print_report(result: dict[str, Any]) -> None:
    """Variant comparison table plus the headline delta."""
    print()
    print(f"query: {result['query']!r}  raw hits: {result['raw']}")
    head = (
        f"{'variant':16} {'uniq':>5} {'dedup':>6} {'tokens':>7} "
        f"{'score':>6} {'good':>5} {'text':>6} {'url':>6} {'left':>5} {'q/find':>7}"
    )
    print(head)
    print("-" * len(head))
    for row in result["rows"]:
        print(
            f"{row['variant']:16} {row['unique']:>5} {row['dedupe_caught']:>6} "
            f"{row['tokens']:>7} {row['mean_score']:>6.3f} {row['good_hits']:>5} "
            f"{str(row['dup_score']):>6} {str(row['url_dup_score']):>6} "
            f"{row['url_dupes_left']:>5} {str(row['q_per_find']):>7}"
        )
    print("-" * len(head))

    by_name = {r["variant"]: r for r in result["rows"]}
    if "url_only" in by_name and "url_then_text" in by_name:
        a, b = by_name["url_only"], by_name["url_then_text"]
        print()
        print("headline A/B  (url_only -> url_then_text):")
        print(f"  dedupe caught       {a['dedupe_caught']} -> {b['dedupe_caught']}")
        print(f"  unique hits kept    {a['unique']} -> {b['unique']}")
        print(f"  tokens              {a['tokens']} -> {b['tokens']}")
        print(f"  url dupes left      {a['url_dupes_left']} -> {b['url_dupes_left']}")
        print(f"  good hits           {a['good_hits']} -> {b['good_hits']}")
    print()


#: metrics where a smaller value is better, for regression checks
LOWER_IS_BETTER = {"tokens", "tokens_per_good", "url_dupes_left", "q_per_find", "unique"}


def check_regression(
    result: dict[str, Any], baseline: dict[str, Any], tolerance: float
) -> list[str]:
    """Compare per-variant metrics; return readable regressions."""
    problems: list[str] = []
    before = {r["variant"]: r for r in baseline.get("rows", [])}
    for row in result["rows"]:
        ref = before.get(row["variant"])
        if not ref:
            continue
        for key, value in row.items():
            base = ref.get(key)
            if key == "variant" or not base or not isinstance(value, (int, float)):
                continue
            if not isinstance(base, (int, float)) or isinstance(value, bool):
                continue
            lower = key in LOWER_IS_BETTER
            change = (value - base) / base
            if change > tolerance if lower else change < -tolerance:
                problems.append(f"{row['variant']}.{key}: {base} -> {value} ({change:+.1%})")
    return problems


def _sanity() -> list[str]:
    """Refuse to report a comparison the fixtures cannot support.

    Two ways this harness could silently lie: variants that all agree (nothing
    to compare), or a fixture set where every planted duplicate happens to be
    catchable by one variant alone (so the composition looks pointless). Both
    are checked here rather than discovered in the output.
    """
    problems: list[str] = []
    raw = [h for f in sq.FIXTURES for h in f.hits]
    counts = {name: len(dedupe(raw)) for name, (dedupe, _d) in VARIANTS.items()}
    if len(set(counts.values())) == 1:
        problems.append(f"all variants agree ({counts}); fixtures cannot discriminate")

    # The composition must strictly beat each single strategy, or the A/B has no
    # headline. This is exactly the case that was missing before a pure
    # same-text/different-host mirror was added.
    combined = counts.get("url_then_text")
    singles = [counts[k] for k in ("url_only", "text_only") if k in counts]
    if combined is not None and singles and not all(combined < s for s in singles):
        problems.append(
            "combined dedupe does not beat both singles "
            f"(url_only={counts.get('url_only')}, text_only={counts.get('text_only')}, "
            f"combined={combined}); fixtures lack a duplicate only one strategy catches"
        )

    # The composition must also be order-independent, or the result is an
    # artefact of the fixture ordering rather than of the strategy.
    if "url_then_text" in counts and "text_then_url" in counts:
        if counts["url_then_text"] != counts["text_then_url"]:
            problems.append(
                "url_then_text and text_then_url disagree "
                f"({counts['url_then_text']} vs {counts['text_then_url']}): result depends "
                "on ordering, so the fixtures are order-sensitive"
            )

    if not any(f.planted_text_dupes for f in sq.FIXTURES):
        problems.append("no fixture plants a text duplicate")
    if not any(f.planted_url_dupes for f in sq.FIXTURES):
        problems.append("no fixture plants a same-URL duplicate")

    # A text duplicate that also shares a URL cannot demonstrate text dedupe.
    norm = [normalize_hit(h) for h in raw]
    urls = Counter(h.url for h in norm)
    pure_text = [
        (f, i) for f in sq.FIXTURES for i in f.planted_text_dupes if urls[f.hits[i].url] == 1
    ]
    if not pure_text:
        problems.append(
            "every planted text duplicate also shares a URL; url dedupe would "
            "catch them all, so text dedupe is untested"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    """Run the A/B comparison; optionally gate against a baseline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=5, help="passes; median reported")
    parser.add_argument("--good-threshold", type=float, default=0.5)
    parser.add_argument("--no-prefilter", action="store_true", help="dedupe raw hits")
    parser.add_argument("--save-baseline", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--max-regression", type=float, default=0.10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    problems = _sanity()
    if problems:
        print("variant sanity check failed:", file=sys.stderr)
        for line in problems:
            print(f"  - {line}", file=sys.stderr)
        return 2

    runs = [
        run_once(use_prefilter=not args.no_prefilter, good_threshold=args.good_threshold)
        for _ in range(max(1, args.repeat))
    ]
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
            print("no baseline; run with --save-baseline first")
            return 1
        found = check_regression(result, json.loads(BASELINE.read_text()), args.max_regression)
        if found:
            print("REGRESSIONS:")
            for line in found:
                print(f"  - {line}")
            status = 1
        else:
            print("no regressions past tolerance")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
