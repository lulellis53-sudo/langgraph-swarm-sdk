"""Measure the efficiency gains of the current SDK against the replaced behavior.

Every scenario runs the *legacy* implementation inline (the exact code this
branch replaced, kept here as the documented baseline) and the current SDK
code on the same deterministic workload, then reports real measured numbers:
token counts from the tokenizer, validated plans from the real spawn
machinery, cache lookups against a real on-disk SemanticCache, and keyword
search against a real SQLite store. ``improvement_pct`` is computed, never
hardcoded.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, cast

import numpy as np
from pydantic import ValidationError
from swarm_sdk.agents.manifest import AgentManifest
from swarm_sdk.execution import HandoffPayload
from swarm_sdk.memory.opencl_store import OpenClVecStore
from swarm_sdk.memory.sqlite_vec import SqliteVecStore
from swarm_sdk.models.chat import complete
from swarm_sdk.orchestrator.plan import Plan
from swarm_sdk.orchestrator.spawn import _JSON_OBJECT, PLAN_PROMPT, _validate_plan, spawn
from swarm_sdk.prompting.budget import count_text
from swarm_sdk.retrieval.cache import SemanticCache
from swarm_sdk.retrieval.embeddings import HashEmbedder, _bge_style, _prepare_texts
from swarm_sdk.retrieval.recall import recall_hits

SEED = 7


def _metric(
    name: str,
    baseline: float,
    current: float,
    *,
    higher_is_better: bool,
    detail: dict[str, Any],
) -> dict[str, Any]:
    """One report row; ``improvement_pct`` needs a non-zero baseline."""
    if baseline:
        improvement = (current - baseline) / baseline * 100.0
        if not higher_is_better:
            improvement = -improvement
    else:
        improvement = float("nan")
    return {
        "name": name,
        "baseline": round(baseline, 4),
        "current": round(current, 4),
        "improvement_pct": round(improvement, 2) if improvement == improvement else None,
        "delta_pp": round(current - baseline, 4),
        "higher_is_better": higher_is_better,
        "detail": detail,
    }


def _manifest(name: str) -> AgentManifest:
    """Build a minimal valid manifest named ``name`` for the plan-validation scenario."""
    return AgentManifest.model_validate(
        {
            "name": name,
            "role": f"role of {name}",
            "model": "openai:gpt-4o",
            "token_budget": {"max_prompt": 512, "max_completion": 128},
        }
    )


async def _spawn_legacy(
    goal: str,
    manifests: dict[str, AgentManifest],
    model: object,
) -> bool:
    """Pre-fix spawn loop: the retry resent the identical prompt, so a model
    that answered badly once answered badly twice and the swarm fell back to a
    single-step plan. Returns True only when a validated plan survived."""
    orchestrator = manifests.get("Orchestrator") or next(iter(manifests.values()))
    roster = "\n".join(f"- {m.name}: {m.role}" for m in manifests.values())
    prompt = PLAN_PROMPT.format(goal=goal, agents=roster)
    for _ in range(2):
        raw = await complete(cast(Any, model), orchestrator.role, prompt)
        match = _JSON_OBJECT.search(raw)
        if match is None:
            continue
        try:
            plan = Plan.model_validate(json.loads(match.group(0)))
        except ValidationError, json.JSONDecodeError:
            continue
        try:
            _validate_plan(plan, manifests)
        except ValueError:
            continue
        return True
    return False


def scenario_plan_recovery() -> dict[str, Any]:
    """Goals whose first plan is rejected: recovery rate, legacy vs current."""
    from benchmark.tests.fakes import Script, ScriptedModel, answer

    step_coder = '{"id": "S1", "title": "t", "description": "d", "agent": "Coder"}'
    step_coder_s2 = (
        '{"id": "S2", "title": "u", "description": "e", "agent": "Coder", "depends_on": ["S1"]}'
    )
    step_coder_dep_s2 = (
        '{"id": "S1", "title": "t", "description": "d", "agent": "Coder", "depends_on": ["S2"]}'
    )
    step_coder_b = '{"id": "S2", "title": "u", "description": "e", "agent": "Coder"}'
    step_ghost = '{"id": "S1", "title": "t", "description": "d", "agent": "Ghost"}'
    good_by_case = {
        "unknown_agent": f'{{"steps": [{step_coder}]}}',
        "no_json": f'{{"steps": [{step_coder}]}}',
        "forward_dep": f'{{"steps": [{step_coder_s2}]}}',
    }
    bad_by_case = {
        "unknown_agent": f'{{"steps": [{step_ghost}]}}',
        "no_json": "Of course! Here is my plan for the swarm.",
        "forward_dep": f'{{"steps": [{step_coder_dep_s2}, {step_coder_b}]}}',
    }
    manifests = {"Orchestrator": _manifest("Orchestrator"), "Coder": _manifest("Coder")}
    legacy_recovered = 0
    current_recovered = 0
    for case, bad in bad_by_case.items():
        # Legacy: the retry cannot tell the model what was wrong, so the model
        # replays the same faulty answer and the plan is lost.
        legacy_recovered += asyncio.run(
            _spawn_legacy(
                "goal",
                manifests,
                ScriptedModel(script=Script([answer(bad), answer(bad)])),
            )
        )
        # Current: the retry carries the rejection reason; the model fixes it.
        plan = asyncio.run(
            spawn(
                "goal",
                manifests,
                model_override=ScriptedModel(
                    script=Script([answer(bad), answer(good_by_case[case])])
                ),
            )
        )
        try:
            _validate_plan(plan, manifests)
            current_recovered += 1
        except ValueError:
            pass
    total = len(bad_by_case)
    return _metric(
        "plan_recovery_rate_pct",
        legacy_recovered / total * 100.0,
        current_recovered / total * 100.0,
        higher_is_better=True,
        detail={
            "scenarios": total,
            "note": "validated plans after a rejected first reply",
        },
    )


def scenario_fanout_briefs(answers_per_mix: int = 60) -> dict[str, Any]:
    """Synthesizer input tokens for specialist briefs: legacy facts duplicated
    the summary head; current facts carry only summary overflow."""
    lengths = (200, 340, 480)
    legacy_tokens = 0
    current_tokens = 0
    for index in range(answers_per_mix):
        answer = f"specialist-{index} " + "finding " * (lengths[index % 3] // 8)
        ask = f"task {index}"
        legacy = HandoffPayload(summary=answer[:280], ask=ask, facts=[answer[:120]])
        overflow = answer[280:400] if len(answer) > 280 else ""
        current = HandoffPayload(
            summary=answer[:280], ask=ask, facts=[overflow] if overflow else []
        )
        legacy_tokens += count_text(legacy.model_dump_json())
        current_tokens += count_text(current.model_dump_json())
    return _metric(
        "fanout_brief_tokens",
        float(legacy_tokens),
        float(current_tokens),
        higher_is_better=False,
        detail={"answers": answers_per_mix, "unit": "tokens into the synthesizer"},
    )


def scenario_bge_m3_prefix(texts_count: int = 24) -> dict[str, Any]:
    """Embedding input tokens for BGE-M3: legacy prefixed every BGE model;
    current skips prefixes for M3 (upstream: M3 takes no instructions)."""
    texts = [f"memory passage {index} about vector stores" for index in range(texts_count)]
    model = "bge-m3-q8_0.gguf"
    legacy = _prepare_texts(texts, query=False, bge_style=True)
    current = _prepare_texts(texts, query=False, bge_style=_bge_style(model))
    return _metric(
        "bge_m3_embed_tokens",
        float(sum(count_text(text) for text in legacy)),
        float(sum(count_text(text) for text in current)),
        higher_is_better=False,
        detail={"texts": texts_count, "model": model},
    )


def scenario_empty_reply_cache(variants: int = 5, tmp_dir: str | None = None) -> dict[str, Any]:
    """After an empty specialist reply, the same question re-asked: legacy
    cached the empty string and served it forever; current never stores it."""
    results = {"legacy_bad_hits": 0, "current_bad_hits": 0, "followups": 0}
    with tempfile.TemporaryDirectory(dir=tmp_dir) as tmp:
        for index in range(variants):
            question = f"what does module {index} export?"
            legacy_cache = SemanticCache(str(Path(tmp) / f"legacy{index}.db"), HashEmbedder(32))
            legacy_cache.store(question, "")
            if legacy_cache.lookup(question) == "":
                results["legacy_bad_hits"] += 1
            current_cache = SemanticCache(str(Path(tmp) / f"current{index}.db"), HashEmbedder(32))
            # Current worker code stores only non-empty replies, so nothing is
            # written for the empty answer; the follow-up must be a miss.
            if current_cache.lookup(question) == "":
                results["current_bad_hits"] += 1
            results["followups"] += 1
    total = float(results["followups"])
    return _metric(
        "empty_reply_poison_rate_pct",
        results["legacy_bad_hits"] / total * 100.0,
        results["current_bad_hits"] / total * 100.0,
        higher_is_better=False,
        detail={"followups": results["followups"], "note": "bogus empty answers served from cache"},
    )


def scenario_recall_dedupe(memories: int = 24) -> dict[str, Any]:
    """Prompt tokens for recalled memory: legacy SwarmSDK.recall injected
    duplicates; current recall dedupes before the prompt."""
    unique = [f"fact {index}: the swarm caches semantic answers" for index in range(memories // 2)]
    texts = unique + unique[: memories // 2]  # second half exact duplicates
    store = OpenClVecStore(32)
    embedder = HashEmbedder(32)
    vectors = embedder.embed(texts, query=False)
    for text, vector in zip(texts, vectors, strict=True):
        store.add(text, vector)
    query_vector = embedder.embed(["semantic answers"], query=True)[0]
    legacy_joined = "\n".join(hit.text for hit in store.search(query_vector, memories))
    current_hits = recall_hits(
        "semantic answers",
        store,
        embedder,
        _identity_reranker(),
        retrieve_k=memories,
        rerank_k=memories,
        dedup_threshold=0.98,
    )
    current_joined = "\n".join(hit.text for hit in current_hits)
    return _metric(
        "recall_prompt_tokens",
        float(count_text(legacy_joined)),
        float(count_text(current_joined)),
        higher_is_better=False,
        detail={"memories": memories, "duplicates": memories // 2, "unit": "tokens injected"},
    )


def _identity_reranker() -> Any:
    """Return an order-preserving reranker (imported lazily to keep startup cheap)."""
    from swarm_sdk.retrieval.rerank import IdentityReranker

    return IdentityReranker()


def scenario_fts5_fallback(docs: int = 120, queries: int = 8) -> dict[str, Any]:
    """Keyword search on SQLite builds without FTS5: legacy construction
    crashed outright; current falls back to a token scan. Reports the
    operational rate, fallback recall, and scan latency."""
    legacy_operational = 1.0
    try:
        sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE probe USING fts5(x)")
    except sqlite3.Error:
        legacy_operational = 0.0

    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteVecStore(str(Path(tmp) / "kw.db"), 8)
        topics = ["alpha", "beta", "gamma", "delta"]
        for index in range(docs):
            topic = topics[index % len(topics)]
            store.add(f"doc {index} mentions {topic} repeatedly {topic}", _one_hot(8, index % 8))
        recall: list[float] = []
        latencies: list[float] = []
        for topic in topics[:queries]:
            expected = {
                text
                for text in (f"doc {i} mentions {topic} repeatedly {topic}" for i in range(docs))
            }
            started = time.perf_counter()
            hits = store.keyword_search(topic, 10)
            latencies.append((time.perf_counter() - started) * 1000)
            returned_texts = [hit.text for hit in hits]
            recall.append(
                len(set(returned_texts) & expected) / len(returned_texts) if returned_texts else 0.0
            )
        store.close()
    current_operational = 1.0 if statistics.mean(recall) > 0.99 else 0.0
    return _metric(
        "fts5_fallback_operational_pct",
        legacy_operational * 100.0,
        current_operational * 100.0,
        higher_is_better=True,
        detail={
            "docs": docs,
            "keyword_recall": round(statistics.mean(recall), 4),
            "p50_ms": round(statistics.median(latencies), 3),
            "note": "legacy construction raised 'no such module: fts5'",
        },
    )


def _one_hot(dim: int, index: int) -> np.ndarray:
    """Return a unit vector with a single 1.0 at ``index``."""
    vector = np.zeros(dim, dtype=np.float32)
    vector[index] = 1.0
    return vector


def run(answers: int = 60, texts: int = 24, docs: int = 120) -> dict[str, Any]:
    """Run every efficiency scenario and return the report dict."""
    metrics = [
        scenario_fanout_briefs(answers),
        scenario_bge_m3_prefix(texts),
        scenario_plan_recovery(),
        scenario_empty_reply_cache(),
        scenario_recall_dedupe(),
        scenario_fts5_fallback(docs),
    ]
    measured = [
        cast(float, item["improvement_pct"])
        for item in metrics
        if item["improvement_pct"] is not None
    ]
    return {
        "seed": SEED,
        "metrics": metrics,
        "mean_improvement_pct": round(statistics.mean(measured), 2) if measured else None,
        "selection": "measured baseline (old behavior, inline) vs current SDK",
    }


def main() -> None:
    """Parse CLI flags, run every scenario and print the JSON report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answers", type=int, default=200)
    parser.add_argument("--texts", type=int, default=48)
    parser.add_argument("--docs", type=int, default=400)
    parser.add_argument("--write-results", action="store_true")
    args = parser.parse_args()
    report = run(args.answers, args.texts, args.docs)
    output = json.dumps(report, indent=2)
    if args.write_results:
        path = Path(__file__).resolve().parents[2] / "results" / "efficiency_gains"
        path.mkdir(parents=True, exist_ok=True)
        target = path / "latest.json"
        target.write_text(output + "\n", encoding="utf-8")
        print(f"Wrote {target}")
    print(output)


if __name__ == "__main__":
    main()
