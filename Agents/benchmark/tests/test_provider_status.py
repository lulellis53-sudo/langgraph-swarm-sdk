"""Provider readiness reports never include credential values."""

from __future__ import annotations

from swarm_sdk.models import status
from swarm_sdk.models.chat import Route


def test_provider_status_groups_routes_and_reports_names_only(monkeypatch) -> None:
    routes = {
        "openrouter:vendor/model-a": Route("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL"),
        "openrouter:vendor/model-b": Route("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL"),
        "anthropic:model": Route("ANTHROPIC_API_KEY", ""),
    }
    monkeypatch.setattr(status, "_route_index", lambda: routes)
    monkeypatch.setattr(status, "route_is_ready", lambda model: model.startswith("openrouter:"))
    monkeypatch.setattr(status.importlib.util, "find_spec", lambda _module: object())

    rows = status.provider_status()

    assert [row["provider"] for row in rows] == ["anthropic", "openrouter"]
    openrouter = rows[1]
    assert openrouter["models"] == ["openrouter:vendor/model-a", "openrouter:vendor/model-b"]
    assert openrouter["credential_env"] == ["OPENROUTER_API_KEY"]
    assert openrouter["configured"] is True
    assert openrouter["installed"] is True
    assert "secret" not in repr(rows)


def test_providers_command_prints_readiness_without_values(monkeypatch, capsys) -> None:
    from swarm_sdk import cli

    monkeypatch.setattr(
        "swarm_sdk.models.status.provider_status",
        lambda: [
            {
                "provider": "openrouter",
                "models": ["openrouter:vendor/model"],
                "credential_env": ["OPENROUTER_API_KEY"],
                "configured": True,
                "installed": True,
            }
        ],
    )

    assert cli.main(["providers"]) == 0
    output = capsys.readouterr().out
    assert "OPENROUTER_API_KEY" in output
    assert "openrouter" in output
    assert "secret" not in output
