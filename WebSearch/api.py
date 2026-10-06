"""FastAPI front for WebSearch: the same search, doctor and browse surfaces as the CLI.

Run locally (binds loopback only by default)::

    PYTHONPATH=<repo root> uv run python -m WebSearch.api          # 127.0.0.1:8765
    PYTHONPATH=<repo root> uv run uvicorn WebSearch.api:app --port 8765

The API never accepts a database path, route or forecast option: those write files or spend
history on the server, so they stay CLI-only. ``/browse`` runs the LLM + Playwright agent and
costs model tokens; it is capped by the ``llm:`` budgets of the providers file. Add your own
authentication before binding to anything but loopback.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from WebSearch.browse_agent import BrowseError
from WebSearch.cli import build_parser, run
from WebSearch.doctor import doctor
from WebSearch.frontend.dorks import DorkError
from WebSearch.frontend.websearchers import SearchFn, load_providers
from WebSearch.midend import FetchFn


class SearchRequest(BaseModel):
    """Body of ``POST /search``; the dork fields mirror the CLI flags."""

    prompt: str = Field(min_length=1, max_length=500)
    preset: str | None = None
    site: str | None = None
    exclude_site: list[str] = Field(default_factory=list, max_length=10)
    filetype: str | None = None
    intitle: str | None = None
    inurl: str | None = None
    intext: str | None = None
    exact: list[str] = Field(default_factory=list, max_length=10)
    exclude: list[str] = Field(default_factory=list, max_length=10)
    after: str | None = None
    before: str | None = None
    days: int | None = Field(default=None, ge=0, le=3650)
    searcher: str | None = None
    limit: int = Field(default=10, ge=1, le=50)
    timeout: float = Field(default=30.0, gt=0, le=120)
    report: bool = False


class BrowseRequest(BaseModel):
    """Body of ``POST /browse``."""

    question: str = Field(min_length=1, max_length=1000)
    model: str | None = Field(default=None, max_length=100)


def _namespace(**fields: Any) -> Any:
    """CLI defaults for every option, then the request's non-empty fields on top."""
    args = build_parser().parse_args(["--prompt", fields.pop("prompt")])
    for key, value in fields.items():
        if value is not None:
            setattr(args, key, value)
    return args


def create_app(
    *,
    backends: Mapping[str, SearchFn] | None = None,
    fetch: FetchFn | None = None,
    model_factory: Callable[[], Any] | None = None,
) -> FastAPI:
    """Build the app. The keyword arguments let tests swap providers, fetcher and model."""
    app = FastAPI(title="WebSearch", version="1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/doctor")
    def doctor_report() -> dict[str, Any]:
        return doctor(load_providers())

    @app.get("/presets")
    def presets() -> dict[str, Any]:
        return load_providers().dork_presets

    @app.post("/search")
    def search(body: SearchRequest) -> dict[str, Any]:
        args = _namespace(**body.model_dump())
        try:
            return run(args, backends=backends, fetch=fetch)
        except (DorkError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/browse")
    def browse_endpoint(body: BrowseRequest) -> dict[str, Any]:
        from WebSearch.browse_agent import browse

        cfg = load_providers()
        try:
            if body.model:
                from dataclasses import replace

                cfg = replace(cfg, llm=replace(cfg.llm, model=body.model))
            model = model_factory() if model_factory else None
            result = browse(body.question, model=model, config=cfg, backends=backends, fetch=fetch)
        except (ValueError, OSError, BrowseError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return asdict(result)

    return app


app = create_app()


def main() -> int:
    """Serve on loopback; ``WEBSEARCH_API_PORT`` changes the port."""
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("WEBSEARCH_API_PORT", "8765")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
