"""``/healthz`` must not depend on provider health."""

from typing import Any, cast

from fastapi.testclient import TestClient

from swarm_sdk.serving.http import create_app


class _ProvidersDownSDK:
    """SDK double that fails the test if ``/healthz`` probes providers."""

    def provider_health(self) -> dict[str, str]:
        raise AssertionError("/healthz must not probe providers")


def test_healthz_is_independent_of_providers() -> None:
    client = TestClient(create_app(cast(Any, _ProvidersDownSDK())))
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
