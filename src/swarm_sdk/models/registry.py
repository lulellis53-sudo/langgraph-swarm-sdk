"""Load Main/config/model_registry.yaml and rank routes to select the best model per think level."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from swarm_sdk.models.selection import ModelRoute, ModelSelectConfig, ThinkLevel

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY_PATH = _REPO_ROOT / "Main" / "config" / "model_registry.yaml"
_PACKAGED_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "agents" / "config" / "model_registry.yaml"
_FALLBACK_REGISTRY_PATH = Path("Main/config/model_registry.yaml")


class RegistryEntry(BaseModel):
    name: str
    provider: str
    api_key_env: str | None = None
    base_url_env: str | None = None
    effort: str | None = None
    think_levels: tuple[ThinkLevel, ...] = ("off", "low", "medium", "high", "xhigh")
    priority: int = 100
    evidence: str = ""


class Registry(BaseModel):
    version: int = 1
    providers: list[RegistryEntry] = Field(default_factory=list)

    def routes(self) -> list[ModelRoute]:
        return [
            ModelRoute(
                name=entry.name,
                provider=entry.provider,
                think_levels=entry.think_levels,
                priority=entry.priority,
            )
            for entry in self.providers
        ]

    def ranked(self, think_level: ThinkLevel) -> list[RegistryEntry]:
        """All entries supporting `think_level`, best (lowest priority) first."""
        return sorted(
            (e for e in self.providers if think_level in e.think_levels),
            key=lambda e: e.priority,
        )

    def select_best(self, think_level: ThinkLevel) -> RegistryEntry:
        """The single best entry for a think level."""
        ranked = self.ranked(think_level)
        if not ranked:
            raise ValueError(f"no registered model supports think_level={think_level!r}")
        return ranked[0]

    def fallback_order(self, think_level: ThinkLevel, depth: int = 3) -> list[RegistryEntry]:
        """Best model plus its fallbacks, in try-order."""
        return self.ranked(think_level)[:depth]

    def to_model_select_config(self, default_level: ThinkLevel = "medium") -> ModelSelectConfig:
        return ModelSelectConfig(default_level=default_level, routes=self.routes())


def load_registry(path: str | Path | None = None) -> Registry:
    candidates = (
        [Path(path)]
        if path
        else [DEFAULT_REGISTRY_PATH, _PACKAGED_REGISTRY_PATH, _FALLBACK_REGISTRY_PATH]
    )
    for candidate in candidates:
        if candidate.is_file():
            data = yaml.safe_load(candidate.read_text())
            return Registry.model_validate(data)
    raise FileNotFoundError(f"model registry not found: {candidates[0]}")


__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "Registry",
    "RegistryEntry",
    "load_registry",
]
