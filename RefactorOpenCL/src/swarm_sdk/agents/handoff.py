"""Validate a worker reply against ``Agents/{Name}/handoff.schema.json``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

__all__ = ["handoff_errors"]


def _object_text(content: str) -> str | None:
    """Return a JSON object body, or None when the reply is prose.

    Args:
        content: Worker reply, optionally wrapped in a Markdown fence.

    Returns:
        The object text, or None when the reply does not start an object.
    """
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        body = lines[1:]
        if body and body[-1].startswith("```"):
            body = body[:-1]
        text = "\n".join(body).strip()
    if not text.startswith("{"):
        return None
    return text


def handoff_errors(agents_root: str, agent: str, content: str) -> list[str]:
    """Check a reply against that agent's handoff schema.

    Prose is accepted. A reply that starts a JSON object must parse and match
    the schema. Agents without ``handoff.schema.json`` are not checked.

    Args:
        agents_root: Directory that contains ``{agent}/``.
        agent: Manifest name.
        content: Worker reply.

    Returns:
        Human-readable errors. Empty means the reply may be handed on.

    Raises:
        SchemaError: When the on-disk schema is not a valid JSON Schema.
    """
    path = Path(agents_root) / agent / "handoff.schema.json"
    if not path.is_file():
        return []
    body = _object_text(content)
    if body is None:
        return []
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        return [f"handoff JSON did not parse: {exc.msg}"]
    if not isinstance(value, dict):
        return ["handoff JSON must be an object"]
    schema: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    return [error.message for error in validator.iter_errors(value)]
