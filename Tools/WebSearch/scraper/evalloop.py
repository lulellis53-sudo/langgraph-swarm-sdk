"""Offline eval loop for the WebScraper hit pipeline.

Runs one query through ``prepare_hits`` → ``compact_hits`` → a deterministic
normalization pass and emits the metrics the improve-loop watches:

- hits: in → prepared → kept (with drop reasons)
- token usage: used vs budget, savings %
- dedupe: planted-duplicate recall
- normalization: chars saved and a 0–1 score
- data quality: mean lexical relevance of the kept hits

No network, no model downloads — a synthetic corpus with planted duplicates
and boilerplate drives every number, so runs are reproducible and diffable.

Run: ``PYTHONPATH=. python -m WebSearch.scraper.evalloop [--query "..."]``
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass, field
from typing import Any

from WebSearch.scraper.hits import compact_hits, hit_score, prepare_hits

__all__ = ["EvalReport", "run_eval", "make_corpus"]

_DEFAULT_QUERY = "rtx 5090 preco oferta brasil"


@dataclass(slots=True)
class EvalReport:
    """Metrics for one query run through the pipeline."""

    query: str
    hits_in: int
    hits_prepared: int
    hits_kept: int
    tokens_used: int
    budget_tokens: int
    tokens_saved_pct: float
    duplicates_dropped: int
    planted_dupes: int
    dedupe_recall: float
    norm_chars_before: int
    norm_chars_after: int
    norm_score: float
    quality_score: float
    drop_reasons: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Plain-dict form for JSON output."""
        return asdict(self)


def make_corpus(
    count: int = 60, *, seed: int = 7, duplicate_rate: float = 0.35
) -> list[dict[str, Any]]:
    """Build a reproducible corpus with boilerplate snippets and planted duplicates."""
    rng = random.Random(seed)
    topics = [
        "rtx 5090 preco oferta brasil",
        "rtx 5090 comprar parcelado",
        "geforce rtx 5090 promocao hoje",
        "placa rtx 5090 frete gratis",
    ]
    boilerplate = (
        " oferta valida hoje, frete gratis para todo o brasil, "
        "parcelamos em ate 12x, garantia oficial, estoque limitado."
    )
    hits: list[dict[str, Any]] = []
    for index in range(count):
        topic = rng.choice(topics)
        if rng.random() < duplicate_rate and hits:
            source = rng.choice(hits)
            hits.append(
                {
                    "url": f"https://shop{index}.example/item?utm_source=feed",
                    "title": source["title"],
                    "snippet": source["snippet"],
                    "score": source["score"] * 0.5,
                }
            )
            continue
        snippet = f"{topic} por R$ {rng.randrange(500, 20000)},00.{boilerplate} ref {index}"
        hits.append(
            {
                "url": f"https://shop{index}.example/item?utm_source=feed",
                "title": f"{topic} — loja {index}",
                "snippet": snippet,
                "score": round(rng.random(), 3),
            }
        )
    return hits


def _normalize_snippet(text: str) -> str:
    """Deterministic normalization: collapse whitespace, strip trailing commas."""
    import re

    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned.rstrip(",. ")


def run_eval(
    query: str = _DEFAULT_QUERY,
    *,
    corpus: list[dict[str, Any]] | None = None,
    budget_tokens: int = 1200,
    limit: int = 10,
) -> EvalReport:
    """Run *query* through the pipeline and return the metric report.

    Args:
        query (str): The search query driving snippet pruning + scoring.
        corpus (list | None): Raw hits; default is the synthetic corpus.
        budget_tokens (int): Token budget for the packer.
        limit (int): Max hits kept after packing.

    Returns:
        EvalReport: All pipeline metrics for this run.
    """
    raw = corpus if corpus is not None else make_corpus()
    # Actual planted duplicates: a (title, snippet) pair repeated from an earlier hit.
    seen_pairs: set[tuple[str, str]] = set()
    planted = 0
    for item in raw:
        pair = (str(item.get("title", "")), str(item.get("snippet", "")))
        if pair in seen_pairs:
            planted += 1
        else:
            seen_pairs.add(pair)

    raw_chars = sum(len(str(item.get("snippet", ""))) for item in raw)
    prepared = prepare_hits(raw, query)
    result = compact_hits(raw, query, budget_tokens=budget_tokens, limit=limit)

    # Normalization = the pipeline's real snippet cleaning + pruning (raw → prepared).
    prepared_chars = sum(len(str(hit.get("snippet", ""))) for hit in prepared)
    norm_score = (1 - prepared_chars / raw_chars) if raw_chars else 0.0

    kept_scores = [
        hit_score(str(h.get("title", "")), str(h.get("snippet", "")), query)
        for h in result.kept
    ]
    quality = sum(kept_scores) / len(kept_scores) if kept_scores else 0.0

    drop_reasons: dict[str, int] = {}
    for hit in result.dropped:
        reason = str(hit.get("_drop_reason", "budget"))
        drop_reasons[reason] = drop_reasons.get(reason, 0) + 1

    return EvalReport(
        query=query,
        hits_in=len(raw),
        hits_prepared=len(prepared),
        hits_kept=len(result.kept),
        tokens_used=result.tokens_used,
        budget_tokens=budget_tokens,
        tokens_saved_pct=round(100 * (1 - result.tokens_used / budget_tokens), 1),
        duplicates_dropped=result.duplicates_dropped,
        planted_dupes=planted,
        dedupe_recall=round(result.duplicates_dropped / planted, 3) if planted else 1.0,
        norm_chars_before=raw_chars,
        norm_chars_after=prepared_chars,
        norm_score=round(norm_score, 3),
        quality_score=round(quality, 3),
        drop_reasons=drop_reasons,
    )


def main() -> None:
    """Parse args, run the eval, print a table + JSON."""
    parser = argparse.ArgumentParser(description="Offline WebScraper eval loop")
    parser.add_argument("--query", default=_DEFAULT_QUERY)
    parser.add_argument("--budget", type=int, default=1200)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true", help="Emit the report as JSON")
    args = parser.parse_args()

    report = run_eval(args.query, budget_tokens=args.budget, limit=args.limit)
    if args.json:
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
        return

    print(f"query            {report.query}")
    print(
        f"hits             {report.hits_in} in → {report.hits_prepared} prepared "
        f"→ {report.hits_kept} kept"
    )
    print(
        f"tokens           {report.tokens_used}/{report.budget_tokens} used, "
        f"{report.tokens_saved_pct}% saved"
    )
    print(
        f"dedupe           {report.duplicates_dropped}/{report.planted_dupes} planted "
        f"(recall {report.dedupe_recall:.0%})"
    )
    print(
        f"normalization    {report.norm_chars_before}→{report.norm_chars_after} chars "
        f"(score {report.norm_score:.2f})"
    )
    print(f"quality          mean lexical {report.quality_score:.2f}")
    if report.drop_reasons:
        print(f"drops            {report.drop_reasons}")


if __name__ == "__main__":
    main()
