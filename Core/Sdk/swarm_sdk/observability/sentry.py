"""Sentry bootstrap driven by ``Main/config/sentry.yaml``.

The YAML holds env-var **names** only (never values); the DSN itself lives in
the environment or the macOS Keychain. Everything is a no-op without the
``sentry-sdk`` package or with ``SENTRY_DSN`` unset, mirroring
``swarm_sdk.observability.metrics`` / ``tracing``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SentrySdkConfig(BaseModel):
    """The ``sdk:`` block of ``sentry.yaml`` (env-var names, never values)."""

    dsn_env: str = "SENTRY_DSN"
    environment_env: str = "SENTRY_ENVIRONMENT"
    traces_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    send_default_pii: bool = False


class SentryFileConfig(BaseModel):
    """Parsed ``sentry.yaml``; unknown blocks (``mcp``, ``github_repositories``) are ignored."""

    sdk: SentrySdkConfig = Field(default_factory=SentrySdkConfig)


def default_sentry_config_path() -> Path | None:
    """Resolve sentry.yaml by env override, then Main/config and cwd candidates."""
    env = os.environ.get("SWARM_SENTRY_CONFIG")
    if env:
        return Path(env)
    cwd = Path.cwd()
    for candidate in (
        cwd / "Main" / "config" / "sentry.yaml",
        (cwd / ".." / "Main" / "config" / "sentry.yaml").resolve(),
        cwd / "config" / "sentry.yaml",
        (cwd / ".." / "config" / "sentry.yaml").resolve(),
    ):
        if candidate.is_file():
            return candidate
    return None


def load_sentry_config(path: Path | None = None) -> SentryFileConfig | None:
    """Parse ``sentry.yaml``; return None when the file is absent or not a mapping.

    Args:
        path: Explicit config path; defaults to :func:`default_sentry_config_path`.

    Returns:
        The parsed file configuration, or None when there is nothing to load.
    """
    cfg_path = path or default_sentry_config_path()
    if cfg_path is None or not cfg_path.is_file():
        return None
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        logger.warning("sentry config must be a mapping, ignoring: %s", cfg_path)
        return None
    return SentryFileConfig.model_validate(data)


def init_sentry(path: Path | None = None) -> bool:
    """Initialize Sentry from the config file plus environment.

    Resolves the DSN from the env var named by ``sdk.dsn_env``. Skips (returns
    False, no side effects) when the config file is missing, the DSN env is
    unset, or ``sentry-sdk`` is not installed. The DSN value is never logged.

    Args:
        path: Explicit config path; defaults to :func:`default_sentry_config_path`.

    Returns:
        True only when ``sentry_sdk.init`` was actually called.
    """
    file_cfg = load_sentry_config(path)
    if file_cfg is None:
        return False
    dsn = os.environ.get(file_cfg.sdk.dsn_env, "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        logger.debug("sentry-sdk is not installed; Sentry stays disabled")
        return False
    environment = os.environ.get(file_cfg.sdk.environment_env) or None
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=file_cfg.sdk.traces_sample_rate,
        send_default_pii=file_cfg.sdk.send_default_pii,
    )
    logger.info(
        "Sentry initialized (environment=%s, traces_sample_rate=%s)",
        environment or "default",
        file_cfg.sdk.traces_sample_rate,
    )
    return True


__all__ = [
    "SentryFileConfig",
    "SentrySdkConfig",
    "default_sentry_config_path",
    "init_sentry",
    "load_sentry_config",
]
