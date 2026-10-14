"""Tests for FastAPI endpoints and SSE streaming."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from langswarm.api import app


@pytest.fixture
def client() -> TestClient:
    """Fixture providing a TestClient instance for the FastAPI application."""
    return TestClient(app)


def test_health_check_endpoint(client: TestClient) -> None:
    """Test /health endpoint returns healthy status and metadata."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_status_endpoint(client: TestClient) -> None:
    """Test /status endpoint returns swarm readiness details."""
    response = client.get("/status")
    assert response.status_code == 200
    data = response.json()
    assert "agents" in data
    assert isinstance(data["agents"], list)
