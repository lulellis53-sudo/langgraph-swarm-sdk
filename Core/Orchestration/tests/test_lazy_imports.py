"""PEP 810: importing the graph module must not load the heavy LangChain stack."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _modules_loaded_after(statement: str, names: list[str]) -> dict[str, bool]:
    code = (
        "import json, sys\n"
        f"{statement}\n"
        f"print(json.dumps({{n: n in sys.modules for n in {names!r}}}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
        cwd=PROJECT_ROOT,
    )
    import json

    return json.loads(result.stdout.strip().splitlines()[-1])


def test_importing_graph_does_not_load_langgraph_or_langchain_core() -> None:
    loaded = _modules_loaded_after("import orchestration.graph", ["langgraph", "langchain_core"])
    assert loaded == {"langgraph": False, "langchain_core": False}


def test_building_the_graph_loads_langgraph_on_first_use() -> None:
    loaded = _modules_loaded_after(
        "from orchestration.graph import build_graph\n"
        "from langchain_core.language_models.fake_chat_models import FakeListChatModel\n"
        "build_graph(FakeListChatModel(responses=['p', 'a']), lambda plan: 'n')",
        ["langgraph"],
    )
    assert loaded == {"langgraph": True}
