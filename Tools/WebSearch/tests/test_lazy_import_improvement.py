"""PEP 810 ``lazy import`` in WebSearch is measurably cheaper than the same source imported eagerly.

Both variants run the identical source in fresh interpreters; the only difference is the
``sys.set_lazy_imports_filter`` veto used by the benchmark module. Module counts and the set of
third-party roots loaded are deterministic and carry most of the proof; the one timing check is
a median over ABBA-paired runs with a wide margin so a loaded machine cannot flip it.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from WebSearch.benchmarks.bench_lazy_imports import measure, probe

_LIGHT_ENTRIES = (
    "WebSearch.Core.agents.agent_tools",
    "WebSearch.Core.app.cli",
    "WebSearch.Core.midend.crawl",
)
_HEAVY_ROOTS = {"pandas", "swarm_sdk", "fastapi", "langchain_core"}


@pytest.fixture(scope="module")
def pairs() -> dict[str, tuple[dict[str, object], dict[str, object]]]:
    """Fresh-process (eager, lazy) probe per entry point; deterministic, so run once."""
    entries = (*_LIGHT_ENTRIES, "WebSearch.Core.app.api")
    return {e: (probe(e, eager=True), probe(e, eager=False)) for e in entries}


@pytest.mark.parametrize("entry", _LIGHT_ENTRIES)
def test_lazy_loads_far_fewer_modules(
    entry: str, pairs: dict[str, tuple[dict[str, object], dict[str, object]]]
) -> None:
    eager, lazy = pairs[entry]
    assert lazy["modules"] < eager["modules"] * 0.7  # type: ignore[operator]


@pytest.mark.parametrize("entry", _LIGHT_ENTRIES)
def test_lazy_loads_none_of_the_heavy_third_party_roots(
    entry: str, pairs: dict[str, tuple[dict[str, object], dict[str, object]]]
) -> None:
    _, lazy = pairs[entry]
    assert not _HEAVY_ROOTS & set(lazy["tracked"])  # type: ignore[arg-type]


@pytest.mark.parametrize("entry", _LIGHT_ENTRIES)
def test_eager_baseline_really_loads_third_party_code(
    entry: str, pairs: dict[str, tuple[dict[str, object], dict[str, object]]]
) -> None:
    """If the baseline were light too, the comparison would prove nothing."""
    eager, lazy = pairs[entry]
    assert len(eager["tracked"]) > len(lazy["tracked"])  # type: ignore[arg-type]


def test_api_entry_point_is_never_worse_when_lazy(
    pairs: dict[str, tuple[dict[str, object], dict[str, object]]],
) -> None:
    """``WebSearch.Core.app.api`` builds a FastAPI app at import, so little can be deferred."""
    eager, lazy = pairs["WebSearch.Core.app.api"]
    assert lazy["modules"] <= eager["modules"]  # type: ignore[operator]


def test_lazy_name_loads_its_module_on_first_use_and_results_match_eager() -> None:
    code = (
        "import json, sys\n"
        "if {eager}: sys.set_lazy_imports_filter(lambda *a: False)\n"
        "import WebSearch.Core.agents.agent_tools as tools\n"
        "before = 'tiktoken' in sys.modules\n"
        "count = tools.count_tokens('lazy imports keep behaviour identical')\n"
        "after = 'tiktoken' in sys.modules\n"
        "print(json.dumps({{'before': before, 'after': after, 'count': count}}))"
    )
    out = {
        eager: json.loads(
            subprocess.run(
                [sys.executable, "-c", code.format(eager=eager)],
                capture_output=True,
                text=True,
                check=True,
                timeout=300,
            )
            .stdout.strip()
            .splitlines()[-1]
        )
        for eager in (True, False)
    }
    assert out[False]["before"] is False  # tiktoken is deferred to the first count_tokens call
    assert out[False]["after"] is True
    assert out[False]["count"] == out[True]["count"] > 0


def test_cli_import_is_much_faster_lazy_median_of_abba_runs() -> None:
    row = measure("WebSearch.Core.app.cli", rounds=2)
    assert row.improvement_pct > 20.0, row
    # Deferred work is paid on first use, so the end-to-end gain must hold too.
    assert row.first_use_improvement_pct > 20.0, row
