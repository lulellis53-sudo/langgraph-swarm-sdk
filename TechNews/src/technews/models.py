"""Value objects shared by every stage."""

from dataclasses import dataclass
from typing import Literal

type Category = Literal["bigtech", "git", "hardware", "code", "ai"]
type SourceKind = Literal["feed", "hn", "search"]

CATEGORIES: tuple[str, ...] = ("bigtech", "git", "hardware", "code", "ai")
SOURCE_KINDS: tuple[str, ...] = ("feed", "hn", "search")


@dataclass(frozen=True, slots=True)
class Source:
    """One configured news source."""

    name: str
    category: Category
    kind: SourceKind
    url: str | None = None
    query: str | None = None
    enabled: bool = True
    limit: int = 20


@dataclass(frozen=True, slots=True)
class Article:
    """One collected headline; ``published`` is ISO 8601 UTC or None."""

    url: str
    source: str
    category: Category
    title: str
    published: str | None
    excerpt: str
    tags: tuple[str, ...] = ()
