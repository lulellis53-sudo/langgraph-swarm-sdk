"""SearXNG Docker wrapper for local WebSearch development.

Provides paths to the packaged ``compose.yaml``/``settings.yml`` and a small
helper to run ``docker compose`` commands against them.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def docker_dir() -> Path:
    """Return the directory containing the SearXNG compose files."""
    return Path(__file__).resolve().parent


def compose_file() -> Path:
    """Return the path to ``compose.yaml``."""
    return docker_dir() / "compose.yaml"


def settings_file() -> Path:
    """Return the path to ``settings.yml``."""
    return docker_dir() / "settings.yml"


def _env() -> dict[str, str]:
    """Inherit the parent environment; ensure COMPOSE_FILE points to ours."""
    env = dict(os.environ)
    env["COMPOSE_FILE"] = str(compose_file())
    env.setdefault("SEARXNG_PORT", "8080")
    env.setdefault("SEARXNG_BASE_URL", "http://localhost:8080/")
    return env


def run_compose(args: list[str], *, cwd: Path | None = None) -> int:
    """Run ``docker compose`` with the packaged compose file.

    Args:
        args: Subcommand and flags to pass to ``docker compose``.
        cwd: Working directory for the command; defaults to :func:`docker_dir`.

    Returns:
        int: The command's exit code.
    """
    cmd = ["docker", "compose", *args]
    result = subprocess.run(cmd, env=_env(), cwd=cwd or docker_dir(), check=False)
    return result.returncode


def status() -> int:
    """Print whether the SearXNG container is running."""
    return run_compose(["ps"])


def up(detach: bool = True) -> int:
    """Start the SearXNG container."""
    args = ["up"]
    if detach:
        args.append("-d")
    return run_compose(args)


def down(volumes: bool = False) -> int:
    """Stop and remove the SearXNG container."""
    args = ["down"]
    if volumes:
        args.append("-v")
    return run_compose(args)


__all__ = [
    "compose_file",
    "docker_dir",
    "down",
    "run_compose",
    "settings_file",
    "status",
    "up",
]
