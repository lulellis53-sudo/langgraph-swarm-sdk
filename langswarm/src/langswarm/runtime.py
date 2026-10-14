"""Event-loop policy: uvloop on POSIX platforms."""


def install_uvloop() -> bool:
    """Make uvloop the default asyncio event-loop policy; no-op on Windows."""
    import os

    if os.name != "posix":
        return False
    import asyncio

    import uvloop

    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    return True
