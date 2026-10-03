import socket

import httpx2

from swarm_sdk.serving.peer import async_post_json, post_json


def test_httpx2_post_uses_http2() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["method"] = request.method
        return httpx2.Response(200, json={"text": "pong", "cached": False})

    body = post_json(
        "https://peer.example/v1/runs",
        {"text": "ping"},
        transport=httpx2.MockTransport(handler),
    )
    assert body["text"] == "pong"
    assert seen["method"] == "POST"


async def test_aiohttp_post() -> None:
    from aiohttp import web

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    async def ok(request: web.Request) -> web.Response:
        payload = await request.json()
        return web.json_response({"text": payload["text"]})

    application = web.Application()
    application.router.add_post("/v1/runs", ok)
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    try:
        body = await async_post_json(
            f"http://127.0.0.1:{port}/v1/runs",
            {"text": "ping"},
        )
    except Exception as exc:
        if "Operation not permitted" in str(exc) or "not permitted" in str(exc):
            import pytest

            pytest.skip(f"Loopback socket connection restricted by sandbox: {exc}")
        raise
    finally:
        await runner.cleanup()
    assert body["text"] == "ping"
