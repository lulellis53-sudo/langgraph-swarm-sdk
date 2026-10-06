"""Import every swarm_sdk module in a fresh interpreter; fail on swarm_sdk-related errors."""

from __future__ import annotations

import importlib
import pkgutil
import sys

import swarm_sdk

failures: list[str] = []


def on_import_error(name: str) -> None:
    """Called by pkgutil.walk_packages when a package fails to import."""
    exc_type, exc_value, _ = sys.exc_info()
    # Only report if it's a swarm_sdk-related error or non-ImportError exception
    if exc_type is not None and (not issubclass(exc_type, ImportError) or "swarm_sdk" in str(exc_value)):
        failures.append(f"{name}: failed to import package")


for info in pkgutil.walk_packages(swarm_sdk.__path__, "swarm_sdk.", onerror=on_import_error):
    try:
        importlib.import_module(info.name)
    except ImportError as exc:  # optional third-party deps are tolerated
        if "swarm_sdk" in str(exc):
            failures.append(f"{info.name}: {exc}")
    except Exception as exc:  # report any import-time crash, not only ImportError
        failures.append(f"{info.name}: {type(exc).__name__}: {exc}")
for line in failures:
    print(line, file=sys.stderr)
print(f"{len(failures)} failing module(s)")
sys.exit(1 if failures else 0)
