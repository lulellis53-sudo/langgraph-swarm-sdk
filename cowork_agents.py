"""Three-agent cowork pipeline: Playwright fetch -> normalize/dedupe -> SQLite.

Pattern C (wave-barrier coworking) over three deterministic agents:

    Wave 0: WebFetch   - one parallel step per URL, headless Chromium render
    Wave 1: Normalizer - extract, normalize, blake2b-dedupe the batch
    Wave 2: Persister  - INSERT OR IGNORE the unique docs into SQLite

Heavy payloads (HTML bytes, extracted docs) travel through a scratchpad dict
bound in the worker factory; ``StepOutput.content`` stays a short summary, so
no transcript bloat (LangGraphSwarm.md sections 2.3 and 3.1).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from WebSearch.backend.docs import ExtractedDoc, dedupe_docs
from WebSearch.backend.extractors import extract_text
from WebSearch.backend.normalize import normalize_text
from WebSearch.backend.store import connect, count_documents, put_documents
from WebSearch.frontend.websearchers import ProvidersConfig, load_providers

if TYPE_CHECKING:
    from swarm_sdk.orchestrator import PlanStep
    from swarm_sdk.orchestrator.plan import StepOutput

FetchFn = Callable[[str], bytes]


class _ActionWorker:
    """Deterministic worker: runs a bound action instead of calling an LLM."""

    def __init__(self, agent: str, action: Callable[[], str]) -> None:
        self._agent = agent
        self._action = action

    async def run(
        self,
        step_id: str,
        description: str,
        dep_outputs: dict[str, str],
        *,
        files: list[str] | None = None,
        task: str = "",
    ) -> StepOutput:
        from swarm_sdk.orchestrator.plan import StepOutput

        del description, dep_outputs, files, task
        started = time.perf_counter()
        content = await asyncio.to_thread(self._action)
        return StepOutput(
            step_id=step_id,
            agent=self._agent,
            content=content,
            wall_s=time.perf_counter() - started,
        )


def run_cowork_pipeline(
    urls: Sequence[str],
    *,
    fetch: FetchFn | None = None,
    db_path: str | Path = "websearch_docs.db",
    max_concurrency: int = 3,
    config: ProvidersConfig | None = None,
) -> dict[str, Any]:
    """Fetch, normalize/dedupe, and store *urls* with the three-agent swarm.

    Args:
        urls: Candidate URLs; duplicates by URL are dropped before fetching.
        fetch: Override GET (tests). Default: headless Chromium via Playwright.
        db_path: SQLite database file for the Persister agent.
        max_concurrency: Parallel fetch cap for wave 0.
        config: ProvidersConfig; default ``load_providers()``.

    Returns:
        dict: ``stored`` rows added, ``docs`` unique docs kept after dedupe,
        ``fetched`` number of fetch steps, ``wall_s`` wall time.
    """
    from WebSearch.midend import fetch_playwright

    from swarm_sdk.orchestrator import Plan, run_plan

    cfg = config or load_providers()
    do_fetch: FetchFn = (
        fetch
        if fetch is not None
        else (lambda url: fetch_playwright(url, timeout_s=cfg.crawl.timeout_s))
    )

    scratch: dict[str, Any] = {"docs": []}
    unique_urls: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    unique_urls = unique_urls[: cfg.crawl.max_urls]

    steps: list[tuple[str, str, str, Callable[[], str], tuple[str, ...], list[str]]] = []
    fetch_ids: list[str] = []
    for index, url in enumerate(unique_urls):
        sid = f"F{index}"

        def make_fetch_action(target: str = url, tag: str = sid) -> Callable[[], str]:
            def action() -> str:
                html = do_fetch(target)
                scratch[f"html:{tag}"] = html.decode("utf-8", errors="replace")
                return f"fetched {target} ({len(html)} bytes)"

            return action

        steps.append((sid, "WebFetch", url, make_fetch_action(), (), [f"fetch:{index}"]))
        fetch_ids.append(sid)

    def normalize_action() -> str:
        docs = [
            ExtractedDoc(
                text=normalize_text(extract_text("selectolax", scratch[f"html:{sid}"])),
                extractor="selectolax",
                url=url,
                raw_chars=len(scratch[f"html:{sid}"]),
            )
            for sid, url in zip(fetch_ids, unique_urls, strict=True)
        ]
        unique = dedupe_docs(docs)
        scratch["docs"] = unique
        return f"normalized {len(docs)} pages, deduped to {len(unique)}"

    steps.append(
        (
            "N",
            "Normalizer",
            "normalize and dedupe the batch",
            normalize_action,
            tuple(fetch_ids),
            ["normalize"],
        )
    )

    def persist_action() -> str:
        conn = connect(db_path)
        stored = put_documents(conn, scratch["docs"])
        total = count_documents(conn)
        conn.close()
        scratch["stored"] = stored
        return f"stored {stored} new documents (total {total})"

    steps.append(
        ("S", "Persister", "put unique documents in SQLite", persist_action, ("N",), ["store"])
    )

    def factory(step: PlanStep) -> _ActionWorker:
        _sid, agent, _desc, action, _deps, _files = step_by_id[step.id]
        return _ActionWorker(agent, action)

    step_by_id = {
        sid: (sid, agent, desc, action, deps, files)
        for sid, agent, desc, action, deps, files in steps
    }
    plan_steps = [
        PlanStepLike(sid, agent, desc, deps, files)
        for sid, agent, desc, _action, deps, files in steps
    ]
    plan = Plan(steps=plan_steps)
    started = time.perf_counter()
    result = asyncio.run(run_plan(plan, factory, max_concurrency=max_concurrency))
    wall = time.perf_counter() - started
    return {
        "fetched": len(fetch_ids),
        "docs": len(scratch["docs"]),
        "stored": scratch.get("stored", 0),
        "total_in_db": count_documents(connect(db_path)),
        "wall_s": round(wall, 4),
        "outputs": {sid: out.content for sid, out in result.outputs.items()},
    }


def PlanStepLike(
    sid: str, agent: str, description: str, depends: tuple[str, ...], files: list[str]
) -> PlanStep:
    """Build a ``PlanStep`` without importing the SDK at module import time."""
    from swarm_sdk.orchestrator import PlanStep

    return PlanStep(
        id=sid,
        title=description,
        description=description,
        agent=agent,
        files=files,
        depends_on=list(depends),
        inputs=list(depends),
    )


__all__ = ["run_cowork_pipeline"]
