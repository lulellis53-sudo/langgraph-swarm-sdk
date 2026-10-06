"""Compatibility alias: the implementation lives in the main Swarm repo (``langchain_tools``)."""

from __future__ import annotations

import importlib
import sys

sys.modules[__name__] = importlib.import_module("langchain_tools")
