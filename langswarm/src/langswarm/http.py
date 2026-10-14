"""Outbound HTTP with httpx2.

httpx2 is the Pydantic-stewarded continuation of httpx under a new package
name and import path; the API surface carries over. A shared client keeps
connection pooling across tool calls.
"""


def http_client(**kwargs):
    """Lazily build a sync httpx2 client with a sensible timeout."""
    import httpx2

    return httpx2.Client(timeout=httpx2.Timeout(30.0), follow_redirects=True, **kwargs)


def fetch_tool(*, name: str = "fetch_url"):
    """Return a tool that agents use to fetch a page over HTTP(S)."""
    client = http_client()

    def fetch(url: str) -> str:
        """Fetch a URL over HTTP(S) and return the response body as text."""
        response = client.get(url)
        response.raise_for_status()
        return response.text

    fetch.__name__ = name
    return fetch
