"""Offline tests for the dedupe/normalizer/extractor upgrades.

Covers registrable-domain site keys (tldextract), the opt-in language gate
(lingua), and the readability/jusText extractors. No network.
"""

from __future__ import annotations

import pytest
from WebSearch.backend.extractors import extract_text
from WebSearch.backend.prefilter import (
    PrefilterPolicy,
    RejectReason,
    is_wrong_language,
    prefilter_hits,
)
from WebSearch.frontend.hits import _strip_site_suffix
from WebSearch.frontend.types import SearchHit

_ARTICLE_HTML = """
<html><head><title>Tech Blog — Python 3.15 lazy imports</title></head>
<body>
<nav>
Home | Products | Pricing | Login | Signup Newsletter | Careers |
Download | Enterprise | Support | Status | Blog | Press | Partners |
Affiliates | Contact | Sitemap | RSS | Subscribe | Unsubscribe |
Cookie Preferences | Accessibility | Trust Center | Security | Legal
</nav>
<aside>Advertisement: Buy our premium developer tools today! Special
offer ends soon. Limited time discount for annual plans. Refer a friend
and earn credits. Join our webinar series on modern software delivery.</aside>
<article class="post-content" id="main-content">
<h1>Python 3.15 lazy imports</h1>
<p>Python 3.15 introduces PEP 810 explicit lazy imports, a syntax that lets a
module declare which imports should be treated as lazy by listing the module
names as strings. On Python 3.15 and later those imports become lazy
automatically, as if they were imported with the lazy keyword, which defers
module loading until first attribute access and improves CLI startup
performance for tools that pull heavy optional dependencies.</p>
<p>Early benchmarks on large command line applications show meaningful startup
reductions because rarely used subcommands no longer pay the import cost at
process start. The reference implementation and the full specification are
documented in the Python enhancement proposal, and third party packaging tools
are expected to adopt the syntax gradually as interpreters upgrade.</p>
<p>Migrating existing codebases involves marking conditional imports and
optional backends first, then measuring startup with a profiler to confirm the
wins. Teams that maintain plugin architectures benefit the most, since plugin
discovery no longer forces eager imports of every plugin module during boot.</p>
</article>
<footer>Copyright 2026 Example Corp. All rights reserved. Privacy Policy.
Terms of Service. Cookie Settings. Do Not Sell My Information. Sitemap.</footer>
</body></html>
"""


def test_site_suffix_strip_uses_registrable_domain() -> None:
    """A 'Python.org' title suffix matches docs.python.org via tldextract keys."""
    hit = SearchHit(
        title="Python 3.15 Docs | Python.org",
        url="https://docs.python.org/3.15/whatsnew/",
        snippet="release notes",
        searcher_id="ddg",
    )
    stripped = _strip_site_suffix(hit.title, hit.url)
    assert stripped == "Python 3.15 Docs"


def test_site_suffix_keeps_unrelated_brand() -> None:
    """A suffix naming a different site is not stripped."""
    title = "Lazy Imports | PyCharm Blog"
    url = "https://blog.jetbrains.com/pycharm/lazy-imports"
    assert _strip_site_suffix(title, url) == title


def test_language_gate_rejects_foreign_snippet() -> None:
    """With language=en, a Spanish snippet is rejected as wrong_language."""
    pytest.importorskip("langdetect")
    policy = PrefilterPolicy(language="en", min_snippet_chars=0)
    hits = [
        SearchHit(
            title="Noticias de tecnología",
            url="https://ejemplo.es/noticias",
            snippet="Las importaciones perezosas llegan a Python 3.15 en esta versión.",
            searcher_id="ddg",
        ),
        SearchHit(
            title="Python 3.15 lazy imports land",
            url="https://example.com/news",
            snippet="Explicit lazy imports ship in Python 3.15, speeding CLI startup.",
            searcher_id="ddg",
        ),
    ]
    kept, rejected = prefilter_hits(hits, policy)
    assert [h.url for h in kept] == ["https://example.com/news"]
    assert all(r.reason == RejectReason.wrong_language for r in rejected)


def test_language_gate_off_by_default_and_fail_open() -> None:
    """No configured language never rejects; missing lingua never rejects."""
    policy = PrefilterPolicy()
    hit = SearchHit("Título", "https://ejemplo.es/x", "Texto en español.", "ddg")
    kept, rejected = prefilter_hits([hit], policy)
    assert len(kept) == 1
    assert rejected == []


def test_is_wrong_language_empty_text_is_false() -> None:
    """Empty text is never flagged (short snippets survive the gate)."""
    assert is_wrong_language("", "en") is False


def test_readability_extractor_keeps_article_drops_nav() -> None:
    """readability-lxml returns the article body without nav/footer chrome."""
    pytest.importorskip("readability")
    text = extract_text("readability", _ARTICLE_HTML)
    assert "PEP 810" in text
    assert "Pricing" not in text
    assert "Copyright" not in text


def test_justext_extractor_drops_boilerplate() -> None:
    """JusText keeps the article paragraph and drops nav/footer boilerplate."""
    pytest.importorskip("justext")
    text = extract_text("justext", _ARTICLE_HTML)
    assert "PEP 810" in text
    assert "Signup Newsletter" not in text


def test_lxml_extractor_keeps_body_drops_script() -> None:
    """The lxml extractor keeps body text and drops script/style nodes."""
    pytest.importorskip("lxml")
    html = (
        "<html><head><style>body{}</style></head>"
        "<body><script>alert(1)</script>"
        "<p>Visible lxml paragraph with PEP 810 content.</p></body></html>"
    )
    text = extract_text("lxml", html)
    assert "PEP 810" in text
    assert "alert" not in text
    assert "body{}" not in text


def test_extractor_order_includes_lxml_after_trafilatura() -> None:
    """The lxml extractor is registered in providers.yaml order, after trafilatura."""
    from WebSearch.frontend.registry import load_providers

    order = load_providers().extractor_order
    assert "lxml" in order
    assert order.index("lxml") == order.index("trafilatura") + 1


def test_unknown_extractor_names_stay_in_literal() -> None:
    """Registry accepts the new extractor names in providers.yaml order."""
    from WebSearch.frontend.registry import load_providers

    order = load_providers().extractor_order
    assert "readability" in order
    assert "justext" in order
    assert order.index("readability") > order.index("trafilatura")
