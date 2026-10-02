from __future__ import annotations

from pathlib import Path
import pytest

from swarm_sdk.core.rules import HostInvariants, HostRuleEngine


def test_host_invariants_defaults():
    invariants = HostInvariants()
    assert invariants.cpu_arch == "x86_64"
    assert invariants.cpu_model == "Intel Core i7-9750H"
    assert invariants.simd_supported == ["AVX2", "FMA", "SSE4.2"]
    assert invariants.simd_prohibited == ["AVX-512"]
    assert invariants.ram_total_gb == 16.0
    assert invariants.ram_ceiling_gb == 13.6
    assert invariants.max_subagents == 3
    assert invariants.modern_cli_tools == {
        "grep": "rg",
        "cat": "bat",
        "find": "fd",
        "sed": "sd",
        "awk": "choose",
        "ls": "eza",
    }


def test_host_invariants_avx512_prohibition_enforced():
    # AVX-512 cannot be in supported list
    with pytest.raises(ValueError, match="AVX-512"):
        HostInvariants(simd_supported=["AVX2", "AVX-512"])

    # AVX-512 must be in prohibited list
    with pytest.raises(ValueError, match="AVX-512"):
        HostInvariants(simd_prohibited=[])


def test_discover_rules_with_explicit_dir(tmp_path: Path):
    rules_file = tmp_path / "AGENTS.md"
    rules_file.write_text("# Test Rules\n")

    discovered = HostRuleEngine.discover_rules(tmp_path)
    assert discovered == rules_file


def test_discover_rules_with_explicit_file(tmp_path: Path):
    rules_file = tmp_path / "CUSTOM_AGENTS.md"
    rules_file.write_text("# Custom Rules\n")

    discovered = HostRuleEngine.discover_rules(rules_file)
    assert discovered == rules_file


def test_discover_rules_default_fallback():
    # If no root_dir given, it finds the repo or machine AGENTS.md if present
    discovered = HostRuleEngine.discover_rules()
    if discovered is not None:
        assert discovered.exists()
        assert discovered.name == "AGENTS.md"


def test_discover_rules_nonexistent(tmp_path: Path):
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()
    # Explicitly asking for an empty dir without falling back to system
    discovered = HostRuleEngine.discover_rules(empty_dir)
    assert discovered is None


def test_parse_invariants_default():
    engine = HostRuleEngine()
    invariants = engine.parse_invariants(None)
    assert isinstance(invariants, HostInvariants)
    assert "AVX-512" in invariants.simd_prohibited
    assert "AVX-512" not in invariants.simd_supported


def test_parse_invariants_from_mock_rules_file(tmp_path: Path):
    mock_rules = tmp_path / "AGENTS.md"
    mock_rules.write_text(
        "# AGENTS.md\n"
        "Intel i7-9750H (6c/12t, AVX2/FMA, no AVX-512), 16 GB RAM.\n"
        "Never spawn more than 2 to 3 concurrent active subagents.\n"
    )
    engine = HostRuleEngine(rules_path=mock_rules)
    invariants = engine.parse_invariants(mock_rules)
    assert invariants.max_subagents == 3
    assert "AVX-512" in invariants.simd_prohibited


def test_parse_invariants_rejects_avx512_enablement(tmp_path: Path):
    mock_rules = tmp_path / "AGENTS.md"
    mock_rules.write_text(
        "# AGENTS.md\n"
        "Enabled SIMD: AVX-512 supported.\n"
    )
    engine = HostRuleEngine()
    with pytest.raises(ValueError, match="AVX-512"):
        engine.parse_invariants(mock_rules)


def test_inject_system_prompt_empty_base():
    engine = HostRuleEngine()
    prompt = engine.inject_system_prompt()
    assert "Intel Core i7-9750H" in prompt
    assert "x86_64" in prompt
    assert "AVX-512" in prompt
    assert "PROHIBITED" in prompt.upper() or "STRICTLY PROHIBITED" in prompt.upper()
    assert "13.6" in prompt or "13.6 GB" in prompt
    assert "rg" in prompt and "bat" in prompt and "fd" in prompt
    assert "sd" in prompt and "choose" in prompt and "eza" in prompt


def test_inject_system_prompt_with_base():
    engine = HostRuleEngine()
    base = "You are an autonomous senior engineer."
    prompt = engine.inject_system_prompt(base)
    assert prompt.startswith(base)
    assert "Intel Core i7-9750H" in prompt
    assert "bat" in prompt


@pytest.mark.parametrize(
    ("cmd", "expected_safe"),
    [
        ("rg 'pattern' src/", True),
        ("bat README.md", True),
        ("fd -e py", True),
        ("sd 'foo' 'bar' file.txt", True),
        ("choose 0 data.txt", True),
        ("eza -la", True),
        ("python3 -m pytest tests/", True),
        ("git status", True),
        ("echo 'cat'", True),
        ("git log --grep='test'", True),
    ],
)
def test_validate_command_safety_allowed(cmd: str, expected_safe: bool):
    engine = HostRuleEngine()
    safe, reason = engine.validate_command_safety(cmd)
    assert safe is expected_safe
    assert reason is None


@pytest.mark.parametrize(
    ("cmd", "expected_tool", "replacement"),
    [
        ("cat README.md", "cat", "bat"),
        ("/bin/cat README.md", "cat", "bat"),
        ("grep -rn 'hello' .", "grep", "rg"),
        ("find . -name '*.py'", "find", "fd"),
        ("sed 's/a/b/' file.txt", "sed", "sd"),
        ("awk '{print $1}' data.txt", "awk", "choose"),
        ("ls -la", "ls", "eza"),
        ("echo hello | grep world", "grep", "rg"),
        ("sudo cat /etc/hosts", "cat", "bat"),
    ],
)
def test_validate_command_safety_legacy_tools(cmd: str, expected_tool: str, replacement: str):
    engine = HostRuleEngine()
    safe, reason = engine.validate_command_safety(cmd)
    assert safe is False
    assert reason is not None
    assert expected_tool in reason
    assert replacement in reason


@pytest.mark.parametrize(
    "cmd",
    [
        "gcc -mavx512f test.c",
        "clang -mavx512vl test.c",
        "cargo build -- -C target-feature=+avx512f",
        "CFLAGS='-mavx512' make",
        "ninja -mavx512",
    ],
)
def test_validate_command_safety_prohibited_simd(cmd: str):
    engine = HostRuleEngine()
    safe, reason = engine.validate_command_safety(cmd)
    assert safe is False
    assert reason is not None
    assert "AVX-512" in reason


def test_core_package_reexport():
    from swarm_sdk.core import HostInvariants as CoreHostInvariants
    from swarm_sdk.core import HostRuleEngine as CoreHostRuleEngine

    assert CoreHostInvariants is HostInvariants
    assert CoreHostRuleEngine is HostRuleEngine


def test_class_level_invocations():
    # Calling directly on HostRuleEngine class without instantiating
    safe, reason = HostRuleEngine.validate_command_safety("cat file.txt")
    assert safe is False
    assert "bat" in reason

    safe, reason = HostRuleEngine.validate_command_safety("rg pattern src/")
    assert safe is True
    assert reason is None

    prompt = HostRuleEngine.inject_system_prompt("Base instructions")
    assert prompt.startswith("Base instructions")
    assert "Intel Core i7-9750H" in prompt

    invariants = HostRuleEngine.parse_invariants()
    assert isinstance(invariants, HostInvariants)


def test_nested_subshell_and_wrapper_validation():
    engine = HostRuleEngine()

    # $(cat ...) subshell
    safe, reason = engine.validate_command_safety("echo $(cat secret.txt)")
    assert safe is False
    assert "cat" in reason
    assert "bat" in reason

    # `grep ...` backticks
    safe, reason = engine.validate_command_safety("echo `grep -r foo .`")
    assert safe is False
    assert "grep" in reason
    assert "rg" in reason

    # sh -c "cat file"
    safe, reason = engine.validate_command_safety("sh -c 'cat file.txt'")
    assert safe is False
    assert "cat" in reason
    assert "bat" in reason

    # xargs grep
    safe, reason = engine.validate_command_safety("xargs -n 1 grep target")
    assert safe is False
    assert "grep" in reason
    assert "rg" in reason

