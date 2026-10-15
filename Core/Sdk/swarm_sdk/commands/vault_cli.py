"""``swarm-vault`` CLI: ``set NAME``, ``import FILE``, ``status [NAME ...]``.

Moved out of :mod:`swarm_sdk.vault` so the library module stays print-free;
all user-facing output lives here. Secret values are never printed.
"""

from __future__ import annotations

import getpass
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from swarm_sdk import vault


def main(argv: Sequence[str] | None = None, *, runner: vault.Runner | None = None) -> int:
    """Run ``swarm-vault set NAME`` or ``swarm-vault status [NAME ...]``."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in {"set", "status", "import"}:
        print("usage: swarm-vault set NAME | import FILE | status [NAME ...]", file=sys.stderr)
        return 2
    cmd, names = args[0], args[1:]
    try:
        if cmd == "import":
            if len(names) != 1:
                print("usage: swarm-vault import FILE", file=sys.stderr)
                return 2
            stored, skipped = vault.import_file(Path(names[0]).expanduser())
            print(f"stored: {', '.join(stored) or '-'}")
            print(f"skipped: {', '.join(skipped) or '-'}")
            return 1 if skipped or not stored else 0
        if cmd == "set":
            if len(names) != 1:
                print("usage: swarm-vault set NAME", file=sys.stderr)
                return 2
            name = vault._check(names[0])
            if vault._keychain_args():
                # `security` stops option parsing at the Keychain positional, so a trailing
                # `-w` prompt would be ignored: prompt here and send the value on stdin.
                value = getpass.getpass(f"Value for {name}: ")
                if not value.strip():
                    print("empty value", file=sys.stderr)
                    return 2
                return 0 if vault.set_secret(name, value) else 1
            # No value on argv: `security` prompts for it on the terminal.
            proc = subprocess.run(
                [
                    "security",
                    "add-generic-password",
                    "-a",
                    getpass.getuser(),
                    "-s",
                    f"{vault.SERVICE_PREFIX}{name}",
                    "-U",
                    "-w",
                ],
                check=False,
            )
            return proc.returncode
        missing = False
        for name in names or vault.KNOWN_NAMES:
            found = vault.get_with_source(name, runner=runner)
            print(f"{name}: {found[1] if found else 'missing'}")
            missing = missing or found is None
        return 1 if missing else 0
    except vault.VaultError as exc:
        print(str(exc), file=sys.stderr)
        return 2


__all__ = ["main"]
