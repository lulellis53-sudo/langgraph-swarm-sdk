"""Seatbelt confinement of the math verifier (roadmap item 9)."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from swarm_sdk.math.verify import verify_math_solution

darwin_only = pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("sandbox-exec") is None,
    reason="needs macOS sandbox-exec",
)


def test_profile_denies_network_spawn_and_scopes_writes() -> None:
    from swarm_sdk.core.darwin_sandbox import build_profile

    workdir = Path("/tmp/work dir")
    profile = build_profile(workdir, home=Path("/Users/someone"))

    assert "(deny network*)" in profile
    assert "(deny process-fork)" in profile
    assert f'(subpath "{workdir.resolve()}")' in profile
    assert '(deny file-read* (subpath "/Users/someone"))' in profile


def test_profile_escapes_quotes_in_paths() -> None:
    from swarm_sdk.core.darwin_sandbox import build_profile

    profile = build_profile(Path('/tmp/a"b'), home=Path("/Users/someone"))

    assert 'a\\"b' in profile
    assert 'a"b' not in profile.replace('a\\"b', "")


def test_wrap_command_is_a_noop_without_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    from swarm_sdk.core import darwin_sandbox

    monkeypatch.setattr(darwin_sandbox, "sandbox_available", lambda: False)

    assert darwin_sandbox.wrap_command(["python", "-V"], Path("/tmp")) == ["python", "-V"]


def test_wrap_command_prefixes_sandbox_exec(monkeypatch: pytest.MonkeyPatch) -> None:
    from swarm_sdk.core import darwin_sandbox

    monkeypatch.setattr(darwin_sandbox, "sandbox_available", lambda: True)

    argv = darwin_sandbox.wrap_command(["python", "-V"], Path("/tmp"))

    assert argv[:2] == [darwin_sandbox.SANDBOX_EXEC, "-p"]
    assert argv[3:] == ["python", "-V"]


def test_ordinary_calculation_still_verifies() -> None:
    result = verify_math_solution("sum", 45, "res = sum(range(10))")

    assert result.verified is True


@darwin_only
def test_script_cannot_read_a_file_under_home() -> None:
    with tempfile.TemporaryDirectory(dir=Path.home(), prefix=".swarm-sbx-") as secret_dir:
        secret = Path(secret_dir) / "secret.txt"
        secret.write_text("42")
        script = f"res = int(open({str(secret)!r}).read())"

        result = verify_math_solution("read", 42, script)

    assert result.verified is False
    assert "PermissionError" in result.detail


@darwin_only
def test_script_cannot_open_a_network_connection() -> None:
    script = (
        "import socket\n"
        "s = socket.socket()\n"
        "s.settimeout(2)\n"
        "s.connect(('127.0.0.1', 9))\n"
        "res = 1\n"
    )

    result = verify_math_solution("net", 1, script)

    assert result.verified is False
    assert "PermissionError" in result.detail


@darwin_only
def test_script_cannot_spawn_a_process() -> None:
    script = "import subprocess\nsubprocess.run(['/bin/echo', 'x'], check=True)\nres = 1\n"

    result = verify_math_solution("spawn", 1, script)

    assert result.verified is False
    assert "PermissionError" in result.detail


@darwin_only
def test_script_cannot_write_outside_its_workdir() -> None:
    with tempfile.TemporaryDirectory(dir=Path.home(), prefix=".swarm-sbx-") as outside:
        target = Path(outside) / "written.txt"
        script = f"open({str(target)!r}, 'w').write('x')\nres = 1\n"

        result = verify_math_solution("write", 1, script)

        assert result.verified is False
        assert not target.exists()


@darwin_only
def test_script_can_still_write_in_its_workdir() -> None:
    script = "open('scratch.txt', 'w').write('7')\nres = int(open('scratch.txt').read())\n"

    assert verify_math_solution("scratch", 7, script).verified is True


@darwin_only
def test_sandbox_can_be_disabled_explicitly() -> None:
    script = (
        "import subprocess\n"
        "res = len(subprocess.run(['/bin/echo', 'x'], capture_output=True).stdout)\n"
    )

    assert verify_math_solution("spawn", 2, script, sandbox=False).verified is True
