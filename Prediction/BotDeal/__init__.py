"""BotDeal — BR deal-hunting lane inside the Prediction engine.

PromoDeals MCP, harvest, ingest, and ``br_hardware`` SQLite pipeline. For a
dedicated checkout, use the ``feat/botdeal`` worktree (see ``README.md``).
"""

from __future__ import annotations

from Prediction.BotDeal._entry import mcp_main, run_harvest
from Prediction.br_hardware import (
    PRODUCTS,
    SOURCES,
    Lead,
    build_queries,
    connect,
    import_observation,
    rebuild_alerts,
    rebuild_floors,
    run_digest,
    write_forecast,
)
from Prediction.br_hardware import (
    main as br_hardware_main,
)

__all__ = [
    "PRODUCTS",
    "SOURCES",
    "Lead",
    "br_hardware_main",
    "build_queries",
    "connect",
    "import_observation",
    "mcp_main",
    "rebuild_alerts",
    "rebuild_floors",
    "run_digest",
    "run_harvest",
    "write_forecast",
]
