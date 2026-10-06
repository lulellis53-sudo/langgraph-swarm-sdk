"""Tests for low-swarm CLI entrypoint with rich/plain console rendering."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from swarm_sdk import cli


class TestLowSwarmCLI:
    """Test suite for low-swarm CLI subcommands: run, vault, ingest, doctor."""

    def test_cli_missing_or_invalid_subcommand(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Invoking CLI with no arguments or invalid subcommand returns non-zero."""
        assert cli.main([]) != 0
        assert cli.main(["unknown-command"]) != 0

    def test_cli_doctor_diagnostic(self, capsys: pytest.CaptureFixture[str]) -> None:
        """low-swarm doctor inspects host invariants and displays diagnostic information."""
        exit_code = cli.main(["doctor"])
        assert exit_code == 0

        captured = capsys.readouterr()
        out = captured.out
        # Invariants checks
        assert "Host Diagnostic" in out or "i7-9750H" in out
        assert "AVX-512" in out
        assert "Prohibited" in out or "PROHIBITED" in out
        # Tool availability checks
        assert "rg" in out
        assert "bat" in out

    def test_cli_run_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        """low-swarm run executes synthesis task and renders results with exit code 0."""
        exit_code = cli.main(["run", "Implement simple greeter function"])
        assert exit_code == 0

        captured = capsys.readouterr()
        out = captured.out
        assert "Status" in out or "SUCCESS" in out or "success" in out
        assert "Jev" in out or "Model Tier" in out
        assert "Lifeguard" in out or "Approved" in out or "APPROVED" in out

    def test_cli_run_with_files_profile_verbose(self, capsys: pytest.CaptureFixture[str]) -> None:
        """low-swarm run supports --files, --profile, and --verbose flags."""
        exit_code = cli.main(
            [
                "run",
                "Build numeric helper functions",
                "--files",
                "helper.py",
                "math.py",
                "--profile",
                "--verbose",
            ]
        )
        assert exit_code == 0

        captured = capsys.readouterr()
        out = captured.out
        assert "helper.py" in out or "math.py" in out or "Profile" in out or "ms" in out

    def test_cli_run_blocked_safety(self, capsys: pytest.CaptureFixture[str]) -> None:
        """low-swarm run halts and returns exit code 1 when safety gate blocks task."""
        exit_code = cli.main(["run", "rm -rf / --no-preserve-root && echo erased"])
        assert exit_code == 1

        captured = capsys.readouterr()
        out = captured.out + captured.err
        assert "blocked" in out.lower() or "safety gate" in out.lower()

    def test_cli_run_blocked_lifeguard(self, capsys: pytest.CaptureFixture[str]) -> None:
        """low-swarm run halts and returns exit code 1 when lifeguard rejects code."""
        with patch("swarm_sdk.cli.LowSwarmEngine") as mock_engine_cls:
            mock_engine = MagicMock()
            mock_engine.run.return_value = {
                "status": "blocked",
                "error": "Max resynthesis iterations reached",
                "jev_decision": {"safe": True, "model_tier": "flash_lite"},
                "lifeguard_report": {
                    "is_approved": False,
                    "violations": [
                        {
                            "file": "bad.py",
                            "line": 1,
                            "col": 0,
                            "message": "Prohibited os.system call",
                        }
                    ],
                },
                "synthesized_code": {},
                "diff_patches": [],
            }
            mock_engine_cls.return_value = mock_engine

            exit_code = cli.main(["run", "Execute unsafe command"])
            assert exit_code == 1

            captured = capsys.readouterr()
            out = captured.out + captured.err
            assert "blocked" in out.lower() or "violation" in out.lower()

    def test_cli_vault_set_and_get(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """low-swarm vault set and get interact with secrets."""
        stored_secrets: dict[str, str] = {}

        def mock_set_secret(name: str, key: str, **kwargs) -> bool:
            stored_secrets[name] = key
            return True

        def mock_get_secret(name: str, **kwargs) -> str | None:
            return stored_secrets.get(name)

        monkeypatch.setattr("swarm_sdk.cli.set_secret", mock_set_secret)
        monkeypatch.setattr("swarm_sdk.cli.get_secret", mock_get_secret)

        # Set OPENAI_API_KEY
        exit_set = cli.main(
            ["vault", "set", "--service", "OPENAI_API_KEY", "--key", "sk-secret-xyz"]
        )
        assert exit_set == 0
        assert stored_secrets["OPENAI_API_KEY"] == "sk-secret-xyz"

        # Get OPENAI_API_KEY
        exit_get = cli.main(["vault", "get", "--service", "OPENAI_API_KEY"])
        assert exit_get == 0
        captured = capsys.readouterr()
        assert "sk-secret-xyz" in captured.out

        # Get missing key
        exit_get_missing = cli.main(["vault", "get", "--service", "NON_EXISTENT"])
        assert exit_get_missing == 1

    def test_cli_vault_set_shorthand_service(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """low-swarm vault set maps service shorthands like 'openai' and 'jev' to standard names."""
        calls: list[tuple[str, str]] = []

        def mock_set_secret(name: str, key: str, **kwargs) -> bool:
            calls.append((name, key))
            return True

        monkeypatch.setattr("swarm_sdk.cli.set_secret", mock_set_secret)

        exit_code = cli.main(["vault", "set", "--service", "openai", "--key", "sk-proj-val"])
        assert exit_code == 0
        assert calls[-1] == ("OPENAI_API_KEY", "sk-proj-val")

        exit_code = cli.main(["vault", "set", "--service", "jev", "--key", "jev-token-val"])
        assert exit_code == 0
        assert calls[-1] == ("JEV_API_KEY", "jev-token-val")

    def test_cli_vault_status_does_not_leak_secrets(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """low-swarm vault status displays presence of keys without printing values."""
        super_secret = "super-secret-unmasked-token-value-999"

        def mock_get_with_source(name: str, **kwargs):
            if name == "OPENAI_API_KEY":
                return (super_secret, "keychain")
            if name == "JEV_API_KEY":
                return (super_secret, "env")
            return None

        monkeypatch.setattr("swarm_sdk.cli.get_with_source", mock_get_with_source)

        exit_code = cli.main(["vault", "status"])
        assert exit_code == 0

        captured = capsys.readouterr()
        out = captured.out
        assert "OPENAI_API_KEY" in out
        assert "JEV_API_KEY" in out
        # CRITICAL SECURITY INVARIANT: Secret value MUST NEVER appear in output
        assert super_secret not in out
        assert "keychain" in out.lower()
        assert "env" in out.lower()

    def test_cli_ingest_markdown_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """low-swarm ingest indexes markdown files and saves vector database."""
        src_dir = tmp_path / "docs"
        src_dir.mkdir()
        (src_dir / "guide.md").write_text(
            "# System Architecture\n\nHigh-performance LangGraph orchestrator on low memory.\n\n"
            "## Invariants\n\nMust avoid AVX-512 and respect 13.6 GB ceiling.\n",
            encoding="utf-8",
        )

        out_dir = tmp_path / "faiss_idx"

        exit_code = cli.main(["ingest", "--source", str(src_dir), "--output", str(out_dir)])
        assert exit_code == 0

        assert out_dir.exists()
        assert (out_dir / "chunks.json").exists()
        assert (out_dir / "meta.json").exists()

        captured = capsys.readouterr()
        assert "Ingested" in captured.out or "chunks" in captured.out

    def test_plain_console_rendering(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Verify plain console fallback renders without rich installed."""
        console = cli.PlainConsole()
        console.print("[bold green]Success[/bold green]: all clear")
        console.rule("Section Title")

        captured = capsys.readouterr()
        assert "Success: all clear" in captured.out
        assert "Section Title" in captured.out

    def test_cli_ingest_nonexistent_source(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """low-swarm ingest returns exit code 1 if source path does not exist."""
        non_existent = tmp_path / "does_not_exist"
        exit_code = cli.main(
            ["ingest", "--source", str(non_existent), "--output", str(tmp_path / "out")]
        )
        assert exit_code == 1

        captured = capsys.readouterr()
        assert "does not exist" in captured.out

    def test_cli_vault_missing_subcommand(self, capsys: pytest.CaptureFixture[str]) -> None:
        """low-swarm vault without subcommand returns exit code 2."""
        exit_code = cli.main(["vault"])
        assert exit_code == 2

    def test_cli_pyproject_scripts_entry(self) -> None:
        """Verify pyproject.toml defines low-swarm script entrypoint."""
        pyproject_path = Path("/Users/usuario/Swarm/pyproject.toml")
        content = pyproject_path.read_text(encoding="utf-8")
        assert 'low-swarm = "swarm_sdk.cli:main"' in content
