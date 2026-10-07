"""HTML → text extractors. Missing optional libs return ``""`` so the next one runs."""

from __future__ import annotations

import importlib
import re

from WebSearch.frontend.websearchers import ExtractorName

_TAG = re.compile(r"<[^>]+>", re.IGNORECASE)


_SCRIPT = re.compile(
    r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>",
    re.IGNORECASE | re.DOTALL,
)


def extract_text(name: ExtractorName, html: str) -> str:
    """Run the named extractor and return plain text (or ``""`` if unavailable)."""
    if name == "selectolax":
        return _selectolax(html)
    if name == "selectolax_regex":
        return _selectolax_regex(html)
    if name == "regex":
        return _regex(html)
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


def _selectolax_regex(html: str) -> str:
    """Selectolax text, then regex whitespace/script leftovers."""
    raw = _selectolax(html)
    if not raw:
        return ""
    cleaned = _SCRIPT.sub(" ", raw)
    return _TAG.sub(" ", cleaned)


def _regex(html: str) -> str:
    """Tag-strip with regex only (no parser extras)."""
    without_chrome = _SCRIPT.sub(" ", html)
    return strip_tags(without_chrome)


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


def strip_tags(html: str) -> str:
    """Remove HTML tags with a fast regex fallback."""
    return _TAG.sub(" ", html)


__all__ = ["extract_text", "strip_tags"]
