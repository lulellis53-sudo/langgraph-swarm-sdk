"""Put ``Core/Sdk`` on ``sys.path`` so ``swarm_sdk`` imports resolve in Core tests."""

from __future__ import annotations

import sys
from pathlib import Path

_SDK_ROOT = Path(__file__).resolve().parents[1] / "Sdk"
_SDK_STR = str(_SDK_ROOT)
if _SDK_STR not in sys.path:
    sys.path.insert(0, _SDK_STR)
