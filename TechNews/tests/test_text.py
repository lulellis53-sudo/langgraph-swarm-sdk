import pytest

from technews.text import canonical_url, content_hash, make_excerpt


def test_canonical_url_strips_tracking_fragment_slash_and_case():
    messy = "HTTP://Example.COM/a/?utm_source=x&id=7&utm_medium=y#frag"
    assert canonical_url(messy) == "http://example.com/a?id=7"


def test_canonical_url_same_story_two_spellings_match():
    a = canonical_url("HTTP://Example.com/a/?utm_source=x#frag")
    b = canonical_url("http://example.com/a")
    assert a == b


def test_canonical_url_keeps_root_path():
    assert canonical_url("https://example.com/") == "https://example.com/"


def test_canonical_url_sorts_query_keys():
    assert canonical_url("https://e.com/p?b=2&a=1") == "https://e.com/p?a=1&b=2"


def test_excerpt_strips_html_and_entities():
    assert make_excerpt("<p>Fish &amp; <b>chips</b></p>") == "Fish & chips"


def test_excerpt_collapses_whitespace():
    assert make_excerpt("a \n\n  b\t c") == "a b c"


def test_excerpt_empty():
    assert make_excerpt("") == ""


def test_excerpt_exactly_limit_is_untouched():
    text = "x" * 300
    assert make_excerpt(text) == text


def test_excerpt_over_limit_truncated_at_word_with_ellipsis():
    text = ("word " * 100).strip()  # 499 chars
    out = make_excerpt(text)
    assert len(out) <= 300
    assert out.endswith("…")
    assert not out[:-1].endswith(" ")


def test_excerpt_301_chars_no_spaces_hard_cut():
    out = make_excerpt("y" * 301)
    assert len(out) == 300
    assert out.endswith("…")


def test_excerpt_non_ascii_and_emoji_counted_as_characters():
    text = "ação 🚀 " * 100
    out = make_excerpt(text)
    assert len(out) <= 300
    assert "🚀" in out


def test_content_hash_stable_and_sensitive():
    assert content_hash("T", "e") == content_hash("T", "e")
    assert content_hash("T", "e") != content_hash("T", "f")


@pytest.mark.parametrize("raw", ["<script>alert(1)</script>hi", "<style>p{}</style>hi"])
def test_excerpt_drops_script_and_style_content(raw):
    assert make_excerpt(raw) == "hi"
