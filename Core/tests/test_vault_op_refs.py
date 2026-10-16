"""Vault: 1Password references from .env/swarm.op.env resolve through `op read`."""

from __future__ import annotations

from pathlib import Path

from swarm_sdk import vault

REF_FILE = """\
# comment
export JINA_API_KEY=op://Personal/abc123/password
APIFY_API_KEY="op://Personal/def456/password"
#COMMENTED_KEY=op://Personal/zzz/password
PLAIN_KEY=not-a-reference
"""


def _write(tmp_path: Path) -> Path:
    path = tmp_path / "swarm.op.env"
    path.write_text(REF_FILE, encoding="utf-8")
    return path


def test_op_reference_is_parsed_with_export_and_quotes(tmp_path: Path) -> None:
    path = _write(tmp_path)
    assert vault.op_reference("JINA_API_KEY", path) == "op://Personal/abc123/password"
    assert vault.op_reference("APIFY_API_KEY", path) == "op://Personal/def456/password"


def test_op_reference_ignores_comments_plain_values_and_missing_file(tmp_path: Path) -> None:
    path = _write(tmp_path)
    assert vault.op_reference("COMMENTED_KEY", path) is None
    assert vault.op_reference("PLAIN_KEY", path) is None
    assert vault.op_reference("JINA_API_KEY", tmp_path / "missing.env") is None


def test_get_with_source_reads_through_op_read(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(args):
        calls.append(list(args))
        return "secret-value" if args[:2] == ["op", "read"] else None

    found = vault.get_with_source(
        "JINA_API_KEY",
        runner=runner,
        dotenv=tmp_path / "none.env",
        environ={},
        op_env=_write(tmp_path),
    )
    assert found == ("secret-value", "1password")
    assert ["op", "read", "op://Personal/abc123/password"] in calls
    assert not any(call[:2] == ["op", "item"] for call in calls)


def test_get_with_source_falls_back_to_title_lookup_without_a_reference(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(args):
        calls.append(list(args))
        return "from-title" if args[:3] == ["op", "item", "get"] else None

    found = vault.get_with_source(
        "BRAVE_API_KEY",
        runner=runner,
        dotenv=tmp_path / "none.env",
        environ={},
        op_env=_write(tmp_path),
    )
    assert found == ("from-title", "1password")


DOC = "# keys\nexport BRAVE_API_KEY='from-doc'\nEXA_API_KEY=other\n"


def test_get_with_source_reads_the_1password_env_document(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(args):
        calls.append(list(args))
        return DOC if args[:3] == ["op", "document", "get"] else None

    found = vault.get_with_source(
        "BRAVE_API_KEY",
        runner=runner,
        dotenv=tmp_path / "none.env",
        environ={},
        op_env=_write(tmp_path),
    )
    assert found == ("from-doc", "1password-document")
    assert ["op", "document", "get", ".env", "--vault", "2"] in calls


def test_document_without_the_name_falls_through_to_title_lookup(tmp_path: Path) -> None:
    def runner(args):
        if args[:3] == ["op", "document", "get"]:
            return DOC
        return "from-title" if args[:3] == ["op", "item", "get"] else None

    found = vault.get_with_source(
        "GROQ_API_KEY",
        runner=runner,
        dotenv=tmp_path / "none.env",
        environ={},
        op_env=_write(tmp_path),
    )
    assert found == ("from-title", "1password")
