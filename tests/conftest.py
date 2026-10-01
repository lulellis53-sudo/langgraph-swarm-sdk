"""Make the checkout importable as ``WebSearch`` whatever its directory is called."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if "WebSearch" not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        "WebSearch", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["WebSearch"] = module
    spec.loader.exec_module(module)
