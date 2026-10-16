"""Tests for the provider capability registry (Config/Providers.json)."""

from __future__ import annotations

import json

import pytest
from WebSearch.frontend.capabilities import (
    capabilities_path,
    load_capabilities,
    provider_capabilities,
)
from WebSearch.frontend.registry import load_providers


def test_registry_file_parses_and_versions() -> None:
    """The packaged JSON loads and carries schema version 1."""
    data = load_capabilities()
    assert data["version"] == 1
    assert isinstance(data["providers"], dict)
    assert data["providers"]


def test_every_active_searcher_has_a_capability_block() -> None:
    """All non-disabled searchers in providers.yaml appear in the registry."""
    data = load_capabilities()["providers"]
    for spec in load_providers().searchers:
        if not spec.enabled:
            continue
        assert spec.id in data, f"missing capability block for {spec.id}"


def test_capability_blocks_carry_docs_and_limits_shape() -> None:
    """Each wired provider has https docs and a limits object with non-negative ints."""
    for provider_id, block in load_capabilities()["providers"].items():
        if block.get("kind") == "placeholder":
            continue
        assert block["docs"].startswith("https://"), provider_id
        limits = block.get("limits")
        if limits is None:
            continue
        for key, value in limits.items():
            if value is None:
                continue
            assert isinstance(value, int) and value >= 0, f"{provider_id}.{key}={value!r}"


def test_known_documented_caps_match_official_docs() -> None:
    """Spot-check limits that come straight from official documentation."""
    assert provider_capabilities("tavily")["limits"]["max_query_chars"] == 400
    assert provider_capabilities("tavily")["limits"]["max_results"] == 20
    assert provider_capabilities("exa")["limits"]["max_results"] == 100
    assert provider_capabilities("brave")["limits"]["max_results"] == 20
    ddg_mcp = provider_capabilities("ddg_mcp")
    assert ddg_mcp["limits"]["search_rate_per_min"] == 30
    assert ddg_mcp["limits"]["fetch_rate_per_min"] == 20


def test_placeholders_name_request_parameters() -> None:
    """Placeholders document the wire parameter names for JS/py clients."""
    tavily = provider_capabilities("tavily")
    assert tavily["placeholders"]["query"] == "query"
    assert tavily["placeholders"]["results"] == "max_results"
    searxng = provider_capabilities("searxng")
    assert (
        searxng["placeholders"]["format"]
        == "format=json (must be enabled in settings.yml search.formats)"
    )


def test_unknown_provider_raises_keyerror() -> None:
    """Asking for an unknown id fails loudly."""
    with pytest.raises(KeyError, match="unknown provider"):
        provider_capabilities("does_not_exist")


def test_file_is_utf8_json_for_js_consumers() -> None:
    """The file stays plain UTF-8 JSON (loadable from Node without a parser change)."""
    raw = capabilities_path().read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert parsed["providers"]
