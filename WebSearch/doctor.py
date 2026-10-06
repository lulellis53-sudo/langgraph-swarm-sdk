"""Environment check for WebSearch: which crawlers, extractors, providers and model are usable.

Modelled on ``opencli doctor``: one read-only report that says what will work before a run
fails halfway. Nothing here makes a network call or prints a secret; keys are reported as
set/unset only.
"""

from __future__ import annotations

import importlib
import importlib.metadata
from typing import Any

from WebSearch.frontend.report import _credentials
from WebSearch.frontend.websearchers import (
    ProvidersConfig,
    builtin_searchers,
    load_providers,
    providers_config_path,
)

#: crawler/extractor name → (import name, distribution name)
_MODULES: dict[str, tuple[str, str]] = {
    "httpx": ("httpx", "httpx"),
    "httpx2": ("httpx2", "httpx2"),
    "requests": ("requests", "requests"),
    "aiohttp": ("aiohttp", "aiohttp"),
    "curl_cffi": ("curl_cffi", "curl-cffi"),
    "scrapy": ("scrapy", "scrapy"),
    "playwright": ("playwright", "playwright"),
    "crawlee": ("crawlee", "crawlee"),
    "selectolax": ("selectolax", "selectolax"),
    "trafilatura": ("trafilatura", "trafilatura"),
    "bs4": ("bs4", "beautifulsoup4"),
    "ddgs": ("ddgs", "ddgs"),
    "fastapi": ("fastapi", "fastapi"),
}
_ALWAYS = {"regex", "selectolax_regex"}


def _module(name: str) -> dict[str, Any]:
    target, dist = _MODULES.get(name, (name, name))
    try:
        importlib.import_module(target)
    except ImportError:
        return {"name": name, "installed": False}
    try:
        version = importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        version = ""
    return {"name": name, "installed": True, "version": version}


def _chromium_ready() -> bool | None:
    """True when Playwright's Chromium binary exists; ``None`` when Playwright is missing."""
    try:
        sync_api = importlib.import_module("playwright.sync_api")
    except ImportError:
        return None
    try:
        with sync_api.sync_playwright() as pw:
            from pathlib import Path

            return Path(pw.chromium.executable_path).exists()
    except Exception:  # Playwright raises its own Error types for driver problems
        return False


def _autonomous(cfg: ProvidersConfig) -> dict[str, Any]:
    """Roster readiness. Reports names only; secret values stay in the vault."""
    from WebSearch.autonomous import model_key_ready, select_ready

    cache: dict[str, bool] = {}

    def ready(name: str) -> bool:
        if name not in cache:
            cache[name] = model_key_ready(name)
        return cache[name]

    def roster(names: tuple[str, ...]) -> list[dict[str, Any]]:
        return [{"name": name, "ready": ready(name)} for name in names]

    playwright = roster(cfg.autonomous_playwright)
    selected_playwright = select_ready(cfg.autonomous_playwright, ready=ready)
    selected_dedupe = select_ready(
        cfg.autonomous_dedupe,
        ready=ready,
        skip=frozenset({selected_playwright}) if selected_playwright else frozenset(),
    )
    return {
        "playwright": playwright,
        "dedupe": roster(cfg.autonomous_dedupe),
        "memory": roster(cfg.autonomous_memory),
        "decision": roster(cfg.autonomous_decision),
        "selected_playwright": selected_playwright,
        "selected_dedupe": selected_dedupe,
        "selected_memory": select_ready(cfg.autonomous_memory, ready=ready),
        "selected_decision": select_ready(cfg.autonomous_decision, ready=ready),
    }


def doctor(config: ProvidersConfig | None = None) -> dict[str, Any]:
    """Collect a readiness report; never raises for a missing optional dependency."""
    cfg = config or load_providers()
    backends = builtin_searchers()
    crawlers = [_module(name) for name in cfg.crawl.crawler_order]
    extractors = [
        {"name": name, "installed": True} if name in _ALWAYS else _module(name)
        for name in cfg.extractor_order
    ]
    searchers = []
    for spec in cfg.searchers:
        needs, have = _credentials(spec)
        searchers.append(
            {
                "id": spec.id,
                "has_backend": spec.id in backends,
                "needs_credentials": needs,
                "credentials_set": have,
                "dork": spec.dork,
            }
        )
    return {
        "config": str(providers_config_path()),
        "crawlers": crawlers,
        "extractors": extractors,
        "searchers": searchers,
        "api": [_module("fastapi"), _module("ddgs")],
        "chromium_ready": _chromium_ready()
        if any(c["name"] == "playwright" for c in crawlers)
        else None,
        "llm": {
            "model": cfg.llm.model,
            "max_pages": cfg.llm.max_pages,
            "max_steps": cfg.llm.max_steps,
        },
        "dork_presets": sorted(cfg.dork_presets),
        "autonomous": _autonomous(cfg),
    }


def render(report: dict[str, Any]) -> str:
    """Plain-text table of :func:`doctor` output."""

    def mark(ok: object) -> str:
        return "ok" if ok else "MISSING"

    lines = [f"config: {report['config']}", "crawlers:"]
    for item in report["crawlers"]:
        lines.append(f"  {item['name']:<10} {mark(item['installed'])} {item.get('version', '')}")
    chromium = report["chromium_ready"]
    if chromium is not None:
        lines.append(f"  chromium   {mark(chromium)}")
    lines.append("extractors:")
    for item in report["extractors"]:
        lines.append(f"  {item['name']:<17} {mark(item['installed'])} {item.get('version', '')}")
    lines.append("searchers:")
    for item in report["searchers"]:
        state = (
            "no backend"
            if not item["has_backend"]
            else ("key set" if item["credentials_set"] else "key MISSING")
            if item["needs_credentials"]
            else "no key needed"
        )
        lines.append(f"  {item['id']:<14} {state:<14} dork={item['dork']}")
    llm = report["llm"]
    lines.append(f"llm: {llm['model'] or 'not configured'} (pages<={llm['max_pages']})")
    lines.append(f"presets: {', '.join(report['dork_presets']) or '-'}")
    auto = report.get("autonomous")
    if isinstance(auto, dict):
        for role in ("playwright", "dedupe", "memory", "decision"):
            bits = [
                f"{item['name']} {'ready' if item['ready'] else 'not-ready'}"
                for item in auto.get(role, [])
            ]
            chosen = auto.get(f"selected_{role}") or "none"
            lines.append(f"autonomous {role}: {', '.join(bits) or '-'} -> {chosen}")
    return "\n".join(lines)


__all__ = ["doctor", "render"]
