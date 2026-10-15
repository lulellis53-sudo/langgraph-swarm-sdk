"""WebSearch worktree bound to the prediction engine's tool-call protocol."""

from __future__ import annotations

from typing import Protocol

from swarm_sdk.prediction._worktree import ensure_repo_on_path
from swarm_sdk.prediction.errors import WebSearchToolError

__all__ = ["SearchTool", "make_websearch_tool"]


class SearchTool(Protocol):
    """A tool call returning ``(url, normalized_text)`` documents for a query."""

    def __call__(self, query: str, *, limit: int = 5) -> list[tuple[str, str]]: ...


def make_websearch_tool(
    *,
    limit: int = 5,
    fetch_timeout_s: float = 15.0,
) -> SearchTool:
    """Build a tool call backed by the ``WebSearch`` worktree.

    The worktree is imported lazily so the engine stays importable without it.
    Each search runs the WebSearch provider registry; top hits are fetched and
    run through the WebSearch extraction + normalization pipeline.

    Args:
        limit: Default maximum hits to fetch per query.
        fetch_timeout_s: Per-page fetch timeout.

    Returns:
        A :class:`SearchTool` callable.

    Raises:
        WebSearchToolError: The worktree is missing, or the search or a fetch fails.
    """
    try:
        ensure_repo_on_path()
        from WebSearch.backend.docs import extract_and_normalize
        from WebSearch.frontend.websearchers import registry_search
    except ImportError as err:
        raise WebSearchToolError(f"WebSearch worktree not importable: {err}") from err

    import httpx

    def search(query: str, *, limit: int = limit) -> list[tuple[str, str]]:
        """Search the registry and return normalized ``(url, text)`` documents."""
        try:
            hits = registry_search(query)
        except Exception as err:  # noqa: BLE001 - provider errors are tool failures
            raise WebSearchToolError(f"search failed: {type(err).__name__}") from err
        documents: list[tuple[str, str]] = []
        with httpx.Client(timeout=fetch_timeout_s, follow_redirects=True) as client:
            for hit in hits[:limit]:
                try:
                    response = client.get(hit.url)
                    response.raise_for_status()
                    doc = extract_and_normalize(response.text, hit.url)
                except Exception:  # noqa: BLE001 - one bad page must not kill the run
                    continue
                if doc.text:
                    documents.append((doc.url, doc.text))
        return documents

    return search
