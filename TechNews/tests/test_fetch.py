import httpx
import pytest

from technews.scrape.fetch import USER_AGENT, FetchError, Fetcher, RobotsDisallowed, make_client


class Clock:
    def __init__(self):
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def build(handler, **kw):
    clock = Clock()
    client = make_client(httpx.MockTransport(handler))
    return Fetcher(client, clock=clock, sleep=clock.sleep, **kw), clock


def ok_robots(request, body="User-agent: *\nAllow: /\n"):
    return httpx.Response(200, text=body)


def test_get_returns_body_and_sends_user_agent():
    seen = {}

    def handler(request):
        if request.url.path == "/robots.txt":
            return ok_robots(request)
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, text="hello")

    fetcher, _ = build(handler)
    assert fetcher.get("https://a.example/x").text == "hello"
    assert seen["ua"] == USER_AGENT


def test_robots_disallow_blocks_without_fetching_target():
    hits = []

    def handler(request):
        hits.append(request.url.path)
        if request.url.path == "/robots.txt":
            return ok_robots(request, "User-agent: *\nDisallow: /private\n")
        return httpx.Response(200, text="secret")

    fetcher, _ = build(handler)
    with pytest.raises(RobotsDisallowed):
        fetcher.get("https://a.example/private/x")
    assert "/private/x" not in hits


def test_robots_404_means_allowed():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text="ok")

    fetcher, _ = build(handler)
    assert fetcher.get("https://a.example/x").text == "ok"


@pytest.mark.parametrize("status", [500, 503])
def test_robots_5xx_means_disallowed(status):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(status)
        return httpx.Response(200, text="ok")

    fetcher, _ = build(handler)
    with pytest.raises(RobotsDisallowed):
        fetcher.get("https://a.example/x")


def test_robots_unreachable_means_disallowed():
    def handler(request):
        if request.url.path == "/robots.txt":
            raise httpx.ConnectError("down")
        return httpx.Response(200, text="ok")

    fetcher, _ = build(handler)
    with pytest.raises(RobotsDisallowed):
        fetcher.get("https://a.example/x")


def test_robots_fetched_once_per_host():
    calls = {"robots": 0}

    def handler(request):
        if request.url.path == "/robots.txt":
            calls["robots"] += 1
            return ok_robots(request)
        return httpx.Response(200, text="ok")

    fetcher, _ = build(handler)
    fetcher.get("https://a.example/1")
    fetcher.get("https://a.example/2")
    assert calls["robots"] == 1


def test_rate_limit_waits_between_requests_to_same_host_only():
    def handler(request):
        if request.url.path == "/robots.txt":
            return ok_robots(request)
        return httpx.Response(200, text="ok")

    fetcher, clock = build(handler, min_interval=1.0)
    fetcher.get("https://a.example/1")
    fetcher.get("https://a.example/2")
    # robots.txt (t=0) + first target (waits 1.0) + second target (waits 1.0) = 2.0
    assert sum(clock.slept) == pytest.approx(2.0)
    clock.slept.clear()
    fetcher.get("https://b.example/1")
    assert sum(clock.slept) == 0


def test_retries_transient_status_then_succeeds():
    state = {"n": 0}

    def handler(request):
        if request.url.path == "/robots.txt":
            return ok_robots(request)
        state["n"] += 1
        return httpx.Response(503) if state["n"] < 3 else httpx.Response(200, text="ok")

    fetcher, _ = build(handler, retries=2)
    assert fetcher.get("https://a.example/x").text == "ok"
    assert state["n"] == 3


def test_gives_up_after_retries_with_fetch_error():
    def handler(request):
        if request.url.path == "/robots.txt":
            return ok_robots(request)
        return httpx.Response(503)

    fetcher, _ = build(handler, retries=1)
    with pytest.raises(FetchError, match="503"):
        fetcher.get("https://a.example/x")


def test_404_is_not_retried():
    state = {"n": 0}

    def handler(request):
        if request.url.path == "/robots.txt":
            return ok_robots(request)
        state["n"] += 1
        return httpx.Response(404)

    fetcher, _ = build(handler, retries=2)
    with pytest.raises(FetchError, match="404"):
        fetcher.get("https://a.example/x")
    assert state["n"] == 1


def test_transport_error_wrapped_in_fetch_error():
    def handler(request):
        if request.url.path == "/robots.txt":
            return ok_robots(request)
        raise httpx.ConnectError("boom")

    fetcher, _ = build(handler, retries=0)
    with pytest.raises(FetchError, match="boom"):
        fetcher.get("https://a.example/x")


def test_non_http_scheme_rejected():
    fetcher, _ = build(lambda r: httpx.Response(200))
    with pytest.raises(FetchError, match="scheme"):
        fetcher.get("file:///etc/passwd")
