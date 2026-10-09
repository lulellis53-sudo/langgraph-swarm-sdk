"""``websearch --prompt``: one query, every provider, optional dork, route and forecast."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, replace
from datetime import date, timedelta
from pathlib import Path
from typing import IO, Any

from WebSearch.agent_tools import render_brief, search_hits
from WebSearch.backend import extract_and_normalize
from WebSearch.backend.route import (
    TARGETS,
    RouteError,
    route,
    semantic_handler,
    sql_handler,
)
from WebSearch.backend.store import connect
from WebSearch.browser_agent import BrowseError
from WebSearch.forecast import ForecastUnavailable, forecast_hits, record_run
from WebSearch.frontend.dorks import DorkError, dork
from WebSearch.frontend.report import search_report
from WebSearch.frontend.websearchers import ProvidersConfig, SearchFn, load_providers
from WebSearch.midend import FetchFn, crawl_then_scrape

DEFAULT_DB = "websearch_docs.db"
_DORK_STRIP = re.compile(r'["()|]')


def build_parser() -> argparse.ArgumentParser:
    """Argument parser for the ``websearch`` command."""
    parser = argparse.ArgumentParser(prog="websearch", description=__doc__)
    parser.add_argument("--prompt", help="the one query sent to every provider")
    parser.add_argument("--doctor", action="store_true", help="check crawlers, providers, model")
    parser.add_argument("--providers", metavar="FILE", help="providers .yaml or .json to use")
    dorks = parser.add_argument_group("google dork (any flag turns the prompt into a dork)")
    dorks.add_argument("--preset", help="named dork from dork_presets in the providers file")
    dorks.add_argument("--site")
    dorks.add_argument("--exclude-site", action="append", default=[], metavar="HOST")
    dorks.add_argument("--filetype")
    dorks.add_argument("--intitle")
    dorks.add_argument("--inurl")
    dorks.add_argument("--intext")
    dorks.add_argument("--exact", action="append", default=[], metavar="PHRASE")
    dorks.add_argument("--exclude", action="append", default=[], metavar="TERM")
    dorks.add_argument("--after", metavar="YYYY-MM-DD")
    dorks.add_argument("--before", metavar="YYYY-MM-DD")
    dorks.add_argument("--days", type=int, metavar="N", help="shorthand for --after (today - N)")
    agent = parser.add_argument_group("LLM browser agent")
    agent.add_argument(
        "--browse", action="store_true", help="a chat model searches and reads pages"
    )
    agent.add_argument(
        "--autonomous",
        action="store_true",
        help="one Keychain-ready model drives Playwright; a different model dedupes pages",
    )
    agent.add_argument("--model", help="provider:name; default llm.model of the providers file")
    parser.add_argument("--searcher", help="restrict to one provider id (default: all)")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=30.0, help="search budget in seconds")
    parser.add_argument(
        "--route",
        default="",
        metavar="sql,semantic",
        help="crawl the hits, dedupe/normalize, then send docs to these paths",
    )
    parser.add_argument("--db", help=f"SQLite path (default {DEFAULT_DB} when needed)")
    parser.add_argument("--forecast", action="store_true", help="forecast hits for this query")
    parser.add_argument("--horizon", type=int, default=7)
    parser.add_argument(
        "--report",
        action="store_true",
        help="per-provider diagnostics: status, prefilter rejects, dedupe, tokens, latency",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser


def _preset_options(
    args: argparse.Namespace, presets: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """Dork keyword arguments: the preset first, explicit flags on top, relative days resolved."""
    options: dict[str, Any] = {}
    if args.preset:
        if args.preset not in presets:
            raise DorkError(f"unknown preset {args.preset!r}; choose from {sorted(presets)}")
        options.update(presets[args.preset])
    flags: dict[str, Any] = {
        "site": args.site,
        "filetype": args.filetype,
        "intitle": args.intitle,
        "inurl": args.inurl,
        "intext": args.intext,
        "after": args.after,
        "before": args.before,
        "exact": list(args.exact) or None,
        "exclude": list(args.exclude) or None,
        "exclude_sites": list(args.exclude_site) or None,
    }
    options.update({k: v for k, v in flags.items() if v})
    today = date.today()
    for key, field in (("after_days", "after"), ("before_days", "before")):
        days = options.pop(key, None)
        if args.days is not None and key == "after_days":
            days = args.days
        if days is not None and field not in options:
            options[field] = (today - timedelta(days=int(days))).isoformat()
    if args.days is not None and "after" not in options:
        options["after"] = (today - timedelta(days=args.days)).isoformat()
    return options


def build_query(
    args: argparse.Namespace, presets: Mapping[str, Mapping[str, Any]] | None = None
) -> str:
    """The raw prompt, or a dork built from its words when any dork option is set."""
    options = _preset_options(args, presets or {})
    if not options:
        return str(args.prompt)
    words = _DORK_STRIP.sub(" ", str(args.prompt)).split()
    return dork(*words, **options)


def _autonomous_report(
    args: argparse.Namespace,
    query: str,
    cfg: ProvidersConfig,
    backends: Mapping[str, SearchFn] | None,
    fetch: FetchFn | None,
    model: Any,
    resolver: Callable[[str], list[str]] | None,
    dedupe_model: Any,
    ready: Callable[[str], bool] | None,
) -> dict[str, Any]:
    """``--autonomous``: browse with one model, then drop near-duplicates with another."""
    from WebSearch.browser_agent import run_autonomous

    if args.model:
        rest = tuple(name for name in cfg.autonomous_playwright if name != args.model)
        cfg = replace(cfg, autonomous_playwright=(args.model, *rest))
    result = run_autonomous(
        query,
        config=cfg,
        playwright_model=model,
        dedupe_model=dedupe_model,
        fetch=fetch,
        backends=backends,
        resolver=resolver,
        ready=ready,
    )
    return {
        "query": query,
        "hits": [],
        "autonomous": {
            "playwright_model": result.playwright_model,
            "dedupe_model": result.dedupe_model,
            "summarize_model": result.summarize_model,
            "answer": result.answer,
            "pages": result.pages,
            "kept": result.kept,
            "dropped": result.dropped,
            "decision_maker": result.decision_maker,
            "memory_provider": result.memory_provider,
        },
        "browse": asdict(result.browse),
    }


def _browse_report(
    args: argparse.Namespace,
    query: str,
    cfg: ProvidersConfig,
    backends: Mapping[str, SearchFn] | None,
    fetch: FetchFn | None,
    model: Any,
    resolver: Callable[[str], list[str]] | None,
) -> dict[str, Any]:
    """``--browse``: hand the question to the LLM browser agent instead of a plain search."""
    from WebSearch.browser_agent import browse

    if args.model:
        cfg = replace(cfg, llm=replace(cfg.llm, model=args.model))
    kwargs: dict[str, Any] = {"model": model, "config": cfg, "backends": backends, "fetch": fetch}
    if resolver is not None:
        kwargs["resolver"] = resolver
    result = browse(query, **kwargs)
    return {"query": query, "hits": [], "browse": asdict(result)}


def _targets(raw: str) -> list[str]:
    """Split a comma route string into non-empty target names."""
    return [part.strip() for part in raw.split(",") if part.strip()]


def run(
    args: argparse.Namespace,
    *,
    backends: Mapping[str, SearchFn] | None = None,
    fetch: FetchFn | None = None,
    engine_factory: Callable[[], Any] | None = None,
    model: Any = None,
    resolver: Callable[[str], list[str]] | None = None,
    dedupe_model: Any = None,
    ready: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Execute one ``websearch`` invocation and return the report.

    Raises:
        DorkError: Invalid dork input.
        RouteError: Unknown route.
        KeyError: Unknown ``--searcher``.
    """
    targets = _targets(args.route)
    unknown = [t for t in targets if t not in TARGETS]
    if unknown:
        raise RouteError(f"unknown route {unknown[0]!r}; choose from {TARGETS}")
    cfg = load_providers(Path(args.providers).expanduser() if args.providers else None)
    query = build_query(args, cfg.dork_presets)
    if args.autonomous:
        return _autonomous_report(
            args, query, cfg, backends, fetch, model, resolver, dedupe_model, ready
        )
    if args.browse:
        return _browse_report(args, query, cfg, backends, fetch, model, resolver)
    extra: dict[str, Any] = {}
    if args.report:
        diag = search_report(
            query,
            config=cfg,
            backends=backends,
            searcher_id=args.searcher,
            timeout_s=args.timeout,
            limit=args.limit,
        )
        hits = diag.hits
        extra["providers"] = [asdict(p) for p in diag.providers]
        extra["merge"] = {
            "kept": diag.kept,
            "exact_dupes": diag.exact_dupes,
            "near_dupes": diag.near_dupes,
            "final": diag.final,
        }
    else:
        hits = search_hits(
            query,
            limit=args.limit,
            config=cfg,
            backends=backends,
            searcher_id=args.searcher,
            timeout_s=args.timeout,
        )
    report: dict[str, Any] = {"query": query, "hits": [asdict(hit) for hit in hits], **extra}

    db_path = args.db or (
        DEFAULT_DB if ("sql" in targets or "semantic" in targets or args.forecast) else None
    )
    if db_path:
        conn = connect(db_path)
        try:
            record_run(conn, query, hits)
            if args.forecast:
                try:
                    days = forecast_hits(
                        conn, query, horizon=args.horizon, engine_factory=engine_factory
                    )
                    report["forecast"] = [{"ds": ds, "hits": y} for ds, y in days]
                except ForecastUnavailable as exc:
                    report["forecast_error"] = str(exc)
        finally:
            conn.close()

    if targets:
        pages = crawl_then_scrape(hits, fetch=fetch, config=cfg)
        docs = [
            extract_and_normalize(p.html, url=p.url, config=cfg, main_first=True)
            for p in pages
            if p.html
        ]
        handlers = {"semantic": semantic_handler(str(args.prompt), db_path=db_path or ":memory:")}
        if db_path:
            handlers["sql"] = sql_handler(db_path)
        clean, results = route(docs, targets, handlers)
        report["docs"] = len(clean)
        report["routes"] = [asdict(r) for r in results]
    return report


def _render(report: dict[str, Any], hits_text: str) -> str:
    """Render a CLI report as human-readable text."""
    if "autonomous" in report:
        auto = report["autonomous"]
        browse = report["browse"]
        lines = [
            f"question: {report['query']}",
            auto["answer"] or f"(no answer: {browse['stopped']})",
            f"playwright: {auto['playwright_model']}",
            f"dedupe: {auto['dedupe_model'] or 'blake2b'}",
            f"summarize: {auto['summarize_model'] or 'browser answer'}",
        ]
        if auto.get("decision_maker"):
            lines.append(f"decision: {auto['decision_maker']}")
        if auto.get("memory_provider"):
            lines.append(f"memory: {auto['memory_provider']}")
        lines += [f"kept: {url}" for url in auto["kept"]]
        lines += [f"dropped: {url}" for url in auto["dropped"]]
        lines += [f"opened: {url}" for url in browse["pages"]]
        lines += [f"blocked: {url}" for url in browse["blocked"]]
        return "\n".join(lines)
    if "browse" in report:
        b = report["browse"]
        lines = [f"question: {report['query']}", b["answer"] or f"(no answer: {b['stopped']})"]
        lines += [f"opened: {url}" for url in b["pages"]]
        lines += [f"blocked: {url}" for url in b["blocked"]]
        lines.append(f"searches: {len(b['searches'])}, model tokens: {b['model_tokens']}")
        return "\n".join(lines)
    lines = [f"query: {report['query']}", hits_text]
    for item in report.get("forecast", []):
        lines.append(f"forecast {item['ds']}: {item['hits']:.1f} hits")
    if "forecast_error" in report:
        lines.append(f"forecast unavailable: {report['forecast_error']}")
    for prov in report.get("providers", []):
        lines.append(
            f"provider {prov['id']}: {prov['status']} raw={prov['raw']} kept={prov['kept']} "
            f"rejected={prov['rejected']} api_tokens={prov['api_tokens']} {prov['ms']}ms"
        )
    for result in report.get("routes", []):
        status = "ok" if result["ok"] else f"failed ({result['error']})"
        lines.append(f"route {result['target']}: {status} {result['detail']}")
    return "\n".join(lines)


def main(
    argv: Sequence[str] | None = None,
    *,
    backends: Mapping[str, SearchFn] | None = None,
    fetch: FetchFn | None = None,
    engine_factory: Callable[[], Any] | None = None,
    model: Any = None,
    resolver: Callable[[str], list[str]] | None = None,
    dedupe_model: Any = None,
    ready: Callable[[str], bool] | None = None,
    out: IO[str] | None = None,
) -> int:
    """Entry point; returns the process exit code (0 ok, 2 bad input, 1 no result)."""
    stream = out or sys.stdout
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.doctor:
        from WebSearch.doctor import doctor, render

        cfg = load_providers(Path(args.providers).expanduser() if args.providers else None)
        report = doctor(cfg)
        print(json.dumps(report, indent=2) if args.json else render(report), file=stream)
        return 0
    if not args.prompt:
        parser.error("--prompt is required (or use --doctor)")
    try:
        report = run(
            args,
            backends=backends,
            fetch=fetch,
            engine_factory=engine_factory,
            model=model,
            resolver=resolver,
            dedupe_model=dedupe_model,
            ready=ready,
        )
    except (DorkError, RouteError, KeyError, ValueError, OSError, BrowseError) as exc:
        print(f"websearch: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2), file=stream)
    else:
        from WebSearch.frontend.websearchers import SearchHit

        hits = [SearchHit(**h) for h in report["hits"]]
        print(_render(report, render_brief(hits) if hits else ""), file=stream)
    if "autonomous" in report:
        auto = report["autonomous"]
        return 0 if auto["answer"] or auto["kept"] else 1
    if "browse" in report:
        return 0 if report["browse"]["answer"] else 1
    return 0 if report["hits"] else 1


__all__ = ["build_parser", "build_query", "main", "run"]
