"""Compatibility alias: the implementation lives in the main Swarm repo (``repeater``)."""

from __future__ import annotations

import importlib
import sys

sys.modules[__name__] = importlib.import_module("repeater")
