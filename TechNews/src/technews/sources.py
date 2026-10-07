"""Load and validate the source registry (``sources.yaml``)."""

from pathlib import Path

import yaml

from technews.models import CATEGORIES, SOURCE_KINDS, Source


class SourceConfigError(Exception):
    """The source registry is missing, malformed or inconsistent."""


def load_sources(path: Path) -> list[Source]:
    """Return every source in ``path`` (enabled or not), validated.

    Raises:
        SourceConfigError: with the entry name and reason on any invalid entry.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as err:
        raise SourceConfigError(f"cannot read {path}: {err}") from err
    entries = data.get("sources") if isinstance(data, dict) else None
    if not entries:
        raise SourceConfigError(f"no sources in {path}")
    out: list[Source] = []
    seen: set[str] = set()
    for raw in entries:
        source = _parse_entry(raw)
        if source.name in seen:
            raise SourceConfigError(f"duplicate source name: {source.name}")
        seen.add(source.name)
        out.append(source)
    return out


def _parse_entry(raw: object) -> Source:
    if not isinstance(raw, dict) or raw.get("name") is None:
        raise SourceConfigError(f"source entry needs a name: {raw!r}")
    if not isinstance(raw["name"], str) or not raw["name"].strip():
        raise SourceConfigError(
            f"source name {raw['name']!r} is not text (YAML read it as a bool/number): "
            'quote it, e.g. name: "Off"'
        )
    name = raw["name"]
    category, kind = raw.get("category"), raw.get("kind")
    if category not in CATEGORIES:
        raise SourceConfigError(f"{name}: bad category {category!r}, expected one of {CATEGORIES}")
    if kind not in SOURCE_KINDS:
        raise SourceConfigError(f"{name}: bad kind {kind!r}, expected one of {SOURCE_KINDS}")
    url, query = raw.get("url"), raw.get("query")
    if kind == "feed":
        if not url:
            raise SourceConfigError(f"{name}: kind feed requires url")
        if not str(url).startswith(("http://", "https://")):
            raise SourceConfigError(f"{name}: url must be http(s): {url}")
    if kind == "search" and not query:
        raise SourceConfigError(f"{name}: kind search requires query")
    return Source(
        name=name,
        category=category,
        kind=kind,
        url=url,
        query=query,
        enabled=bool(raw.get("enabled", True)),
        limit=int(raw.get("limit", 20)),
    )
