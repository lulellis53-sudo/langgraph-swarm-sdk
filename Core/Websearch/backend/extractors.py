"""HTML → text extractors. Missing optional libs return ``""`` so the next one runs."""

from __future__ import annotations

lazy import importlib
lazy import re

lazy from WebSearch.Core.frontend.websearchers import ExtractorName

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
    if name == "lxml":
        return _lxml(html)
    if name == "readability":
        return _readability(html)
    if name == "justext":
        return _justext(html)
    if name == "inscriptis":
        return _inscriptis(html)
    if name == "markdownify":
        return _markdownify(html)
    return _bs4(html)


def _selectolax(html: str) -> str:
    """Extract body text with selectolax/lexbor; ``""`` when unavailable."""
    try:  # selectolax 1.x dropped the Modest backend (selectolax.parser); lexbor is the parser
        parser_mod = importlib.import_module("selectolax.lexbor")
    except ImportError:
        return ""
    tree = parser_mod.LexborHTMLParser(html)
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
    """Extract main-article text with trafilatura; ``""`` when unavailable."""
    try:
        trafilatura = importlib.import_module("trafilatura")
    except ImportError:
        return ""
    extracted = trafilatura.extract(html, include_comments=False)
    return extracted or ""


def _lxml(html: str) -> str:
    """Extract body text with lxml.html (fast C parser); ``""`` when unavailable.

    Drops ``script``/``style``/``noscript`` and returns the ``body`` text
    (all descendants) separated by newlines — a fast generic extractor that
    keeps every visible node, unlike the article-focused trafilatura/readability.
    """
    try:
        lxml_html = importlib.import_module("lxml.html")
    except ImportError:
        return ""
    try:
        doc = lxml_html.fromstring(html)
    except Exception:  # noqa: BLE001 - malformed HTML must fall through to the next extractor
        return ""
    for bad in doc.xpath("//script | //style | //noscript"):
        bad.drop_tree()
    body = doc.body if doc.body is not None else doc
    return "\n".join(t.strip() for t in body.itertext() if t.strip())


def _readability(html: str) -> str:
    """Main-content extraction via readability-lxml; ``""`` when unavailable."""
    try:
        from readability import Document
    except ImportError:
        return ""
    summary = Document(html).summary()
    return _TAG.sub(" ", _SCRIPT.sub(" ", summary)).strip() or ""


def _justext(html: str) -> str:
    """Boilerplate removal with jusText (English stoplist); ``""`` when unavailable."""
    try:
        import justext
    except ImportError:
        return ""
    paragraphs = justext.justext(
        html.encode("utf-8", errors="replace"), justext.get_stoplist("English")
    )
    kept = [p.text for p in paragraphs if not p.is_boilerplate]
    return "\n".join(kept).strip()


def _bs4(html: str) -> str:
    """Extract text with BeautifulSoup; ``""`` when bs4 is unavailable.

    Prefers the ``lxml`` parser backend (C speed) and falls back to the stdlib
    ``html.parser`` when lxml is not installed.
    """
    try:
        bs4_mod = importlib.import_module("bs4")
    except ImportError:
        return ""
    try:
        soup = bs4_mod.BeautifulSoup(html, "lxml")
    except Exception:  # noqa: BLE001 - lxml parser missing/malformed HTML → stdlib parser
        soup = bs4_mod.BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text("\n")


def _inscriptis(html: str) -> str:
    """Extract clean layout-preserving text with inscriptis; '' when unavailable."""
    try:
        import inscriptis

        return inscriptis.get_text(html) or ""
    except ImportError:
        return ""


def _markdownify(html: str) -> str:
    """Extract clean markdown with markdownify; '' when unavailable."""
    try:
        import markdownify

        return (
            markdownify.markdownify(
                html,
                strip=["script", "style", "nav", "footer", "noscript"],
                heading_style="ATX",
            )
            or ""
        )
    except ImportError:
        return ""


def strip_tags(html: str) -> str:
    """Remove HTML tags with a fast regex fallback."""
    return _TAG.sub(" ", html)


__all__ = ["extract_text", "strip_tags"]
