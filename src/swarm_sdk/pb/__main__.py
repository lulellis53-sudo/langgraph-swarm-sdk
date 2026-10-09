"""Regenerate gRPC stubs from ``swarm.proto`` into this package.

Uses the official custom package-path form of ``-I`` so generated
``*_pb2_grpc.py`` imports resolve inside ``swarm_sdk.pb`` without a
manual sed rewrite. See:
https://grpc.io/docs/languages/python/basics/#generating-grpc-interfaces-with-custom-package-path
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PB_DIR = Path(__file__).resolve().parent
_SRC_ROOT = _PB_DIR.parent.parent  # …/src
_PROTO = _PB_DIR / "swarm.proto"
_PACKAGE_PREFIX = "swarm_sdk/pb"


def regenerate() -> None:
    """Run ``grpc_tools.protoc`` on ``swarm.proto`` to refresh the package stubs.

    Raises:
        FileNotFoundError: If ``swarm.proto`` is missing from this package.
        subprocess.CalledProcessError: If protoc exits non-zero.
    """
    if not _PROTO.is_file():
        raise FileNotFoundError(f"missing {_PROTO}")

    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"-I{_PACKAGE_PREFIX}={_PB_DIR}",
        f"--python_out={_SRC_ROOT}",
        f"--pyi_out={_SRC_ROOT}",
        f"--grpc_python_out={_SRC_ROOT}",
        str(_PROTO),
    ]
    subprocess.run(cmd, check=True)
    print(f"regenerated stubs from {_PROTO.name} → {_PB_DIR} ({_PACKAGE_PREFIX})")


def main() -> int:
    """Regenerate the gRPC stubs and return a process exit code.

    Returns:
        Always ``0`` on success (protoc failures raise instead).
    """
    regenerate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
