"""Backend: HTML extractors (selectolax, trafilatura, bs4) and text normalization."""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from typing import Literal

from WebSearch.frontend.providers import ExtractorName, ProvidersConfig, load_providers

_WS = re.compile(r"\s+")

ExtractorUsed = ExtractorName | Literal["fallback"]


@dataclass(frozen=True, slots=True)
class ExtractedDoc:
    text: str
    extractor: ExtractorUsed
    url: str = ""


def normalize_text(text: str) -> str:
    """Collapse whitespace and strip. Shared post-step for every extractor."""
    return _WS.sub(" ", text).strip()


def type_is_extracted(value: object) -> bool:
    return isinstance(value, ExtractedDoc)


def extract_and_normalize(
    html: str,
    *,
    url: str = "",
    config: ProvidersConfig | None = None,
) -> ExtractedDoc:
    """Try extractors in yaml order; always run ``normalize_text`` on the winner."""
    order = (config or load_providers()).extractor_order
    last_text = ""
    used: ExtractorUsed = "fallback"
    for name in order:
        text = _extract_with(name, html)
        if text:
            last_text = text
            used = name
            break
    if not last_text:
        last_text = _strip_tags(html)
        used = "fallback"
    return ExtractedDoc(text=normalize_text(last_text), extractor=used, url=url)


def _extract_with(name: ExtractorName, html: str) -> str:
    if name == "selectolax":
        return _selectolax(html)
    if name == "trafilatura":
        return _trafilatura(html)
    return _bs4(html)


def _selectolax(html: str) -> str:
    try:
        parser_mod = importlib.import_module("selectolax.parser")
    except ImportError:
        return ""
    html_parser = parser_mod.HTMLParser
    tree = html_parser(html)
    tree.strip_tags(["script", "style", "noscript"])
    body = tree.body
    raw = body.text(separator="\n") if body is not None else tree.text()
    return raw or ""


def _trafilatura(html: str) -> str:
    try:
        trafilatura = importlib.import_module("trafilatura")
    except ImportError:
        return ""
    extracted = trafilatura.extract(html, include_comments=False)
    return extracted or ""


def _bs4(html: str) -> str:
    try:
        bs4_mod = importlib.import_module("bs4")
    except ImportError:
        return ""
    soup = bs4_mod.BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text("\n")


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


__all__ = [
    "ExtractedDoc",
    "extract_and_normalize",
    "normalize_text",
    "type_is_extracted",
]
