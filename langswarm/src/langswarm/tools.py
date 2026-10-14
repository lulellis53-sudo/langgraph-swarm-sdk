"""Tool registry shared by YAML blueprints and programmatic specs.

Agents reference tools by name (``tools: [rag_search]``); the registry maps
each name to a zero-argument factory. Heavy dependencies are imported inside
the factories and the tool functions themselves, so resolving the registry is
instant and a missing optional service surfaces as a tool error the model can
recover from.
"""

from collections.abc import Callable

# ---------------------------------------------------------------------------
# Offline demo tools (no dependencies, always available)
# ---------------------------------------------------------------------------

def fetch_notes(topic: str) -> str:
    """Look up the local fallback notes for a topic."""
    return (
        f"Notes on '{topic}': "
        "1) swarms split work between specialised agents; "
        "2) handoff tools pass full message history, so context is never lost; "
        "3) a shared supervisor tracks the active agent across turns; "
        "4) observability platforms show the full handoff trace tree."
    )


def draft_outline(title: str, notes: str) -> str:
    """Turn notes into a three-section article outline."""
    return (
        f"Outline for '{title}': "
        f"I. Context — {notes[:60]}...; "
        "II. How it works — agents, handoffs, routing; "
        "III. Conclusion — when to choose a swarm over a single agent."
    )


def critique_draft(draft: str) -> str:
    """Return a short critique of a draft for revision purposes."""
    issues = "a clear thesis" if len(draft) > 200 else "too short"
    return f"Critique: the draft has {issues}. Verify claims and tighten the ending."


def format_answer(text: str) -> str:
    """Polish a final answer: trim and collapse whitespace."""
    return " ".join(text.split())


def calculate(expression: str) -> str:
    """Evaluate a mathematical expression exactly with SymPy."""
    import sympy

    return str(sympy.sympify(expression))


# ---------------------------------------------------------------------------
# Factories for tools with optional or service-backed dependencies
# ---------------------------------------------------------------------------

def _rag_search():
    from langswarm.retrieval import rag_search_tool

    return rag_search_tool()


def _rag_ingest():
    from langswarm.retrieval import rag_ingest_tool

    return rag_ingest_tool()


def _remember():
    from langswarm.mem0 import mem0_remember_tool

    return mem0_remember_tool()


def _recall():
    from langswarm.mem0 import mem0_recall_tool

    return mem0_recall_tool()


def _inspect_dataset():
    from langswarm.config import settings
    from langswarm.data import table_tool

    return table_tool(settings.data_path, name="inspect_dataset")


def _validate_dataset():
    from langswarm.config import settings
    from langswarm.data import validate_dataset_tool

    return validate_dataset_tool(settings.data_path)


def _fetch_url():
    from langswarm.http import fetch_tool

    return fetch_tool()


def _run_benchmark():
    from langswarm.bench import bench_tool

    return bench_too
def _websearch():
    # WebSearch is a separate package (Tools/WebSearch); import it lazily so a
    # missing install surfaces as a tool error, not an import-time failure.
    from WebSearch.Webengine import Websearch

    return Websearch()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

REGISTRY: dict[str, Callable[[], Callable]] = {
    "fetch_notes": lambda: fetch_notes,
    "draft_outline": lambda: draft_outline,
    "critique_draft": lambda: critique_draft,
    "format_answer": lambda: format_answer,
    "calculate": lambda: calculate,
    "rag_search": _rag_search,
    "rag_ingest": _rag_ingest,
    "remember": _remember,
    "recall": _recall,
    "inspect_dataset": _inspect_dataset,
    "validate_dataset": _validate_dataset,
    "fetch_url": _fetch_url,
    "websearch": _websearch,
    "run_benchmark": _run_benchmark,
}

TOOL_REGISTRY = REGISTRY


def get_tool(name: str) -> Callable:
    """Retrieve an instantiated tool by name."""
    if name not in REGISTRY:
        raise KeyError(f"Unknown tool '{name}'. Known tools: {list(REGISTRY.keys())}")
    return REGISTRY[name]()


def resolve_tools(names: list[str]) -> list[Callable]:
    """Instantiate a list of tools by registry name."""
    unknown = [name for name in names if name not in REGISTRY]
    if unknown:
        known = ", ".join(sorted(REGISTRY))
        raise KeyError(f"Unknown tool(s): {', '.join(unknown)}. Known tools: {known}")
    return [REGISTRY[name]() for name in names]

