from WebSearch.frontend import SearchHit
from WebSearch.frontend.hits import near_dedupe, normalize_hit

BASE = (
    "Python 3.14 release notes: free-threaded build, deferred annotations, "
    "t-strings, and a new zstd compression module for the standard library"
)


def _hit(
    title: str = "Title",
    snippet: str = "snippet",
    url: str = "https://example.com/a",
    searcher_id: str = "brave",
) -> SearchHit:
    return SearchHit(title=title, url=url, snippet=snippet, searcher_id=searcher_id)


def test_normalize_cleans_title_and_snippet() -> None:
    hit = normalize_hit(_hit(title="  Café &amp; Bar​  ", snippet="a  b\n\na b"))
    assert (hit.title, hit.snippet) == ("Café & Bar", "a b")


def test_site_suffix_is_stripped_when_it_names_the_host() -> None:
    hit = normalize_hit(
        _hit(title="Intro to asyncio | Example", url="https://www.example.com/a")
    )
    assert hit.title == "Intro to asyncio"


def test_site_suffix_with_spaces_and_dash_variants() -> None:
    hit = normalize_hit(
        _hit(title="Best answer – Stack Overflow", url="https://stackoverflow.com/q/1")
    )
    assert hit.title == "Best answer"


def test_site_suffix_matches_a_subdomain_label() -> None:
    hit = normalize_hit(
        _hit(
            title="asyncio - Python",
            url="https://docs.python.org/3/library/asyncio.html",
        )
    )
    assert hit.title == "asyncio"


def test_other_separator_text_is_kept() -> None:
    hit = normalize_hit(_hit(title="Pros | Cons of rust", url="https://example.com/a"))
    assert hit.title == "Pros | Cons of rust"


def test_title_that_is_only_a_suffix_is_kept() -> None:
    hit = normalize_hit(_hit(title="| Example", url="https://example.com/a"))
    assert hit.title == "| Example"


def test_normalize_handles_empty_and_non_ascii() -> None:
    hit = normalize_hit(_hit(title="", snippet="日本語のテキスト"))
    assert (hit.title, hit.snippet) == ("", "日本語のテキスト")


def test_near_dedupe_merges_identical_text_and_records_other_searchers() -> None:
    first = _hit(BASE, "", "https://a.example/1", "brave")
    second = _hit(BASE, "", "https://b.example/2", "tavily")
    third = _hit(BASE, "", "https://c.example/3", "tavily")
    out = near_dedupe([first, second, third])
    assert [h.url for h in out] == ["https://a.example/1"]
    assert out[0].also_from == ("tavily",)


def test_near_dedupe_same_searcher_is_not_listed_in_also_from() -> None:
    out = near_dedupe(
        [_hit(BASE, "", "https://a.example/1"), _hit(BASE, "", "https://b.example/2")]
    )
    assert len(out) == 1
    assert out[0].also_from == ()


def test_near_dedupe_merges_a_lightly_edited_copy() -> None:
    edited = _hit(BASE + " today", "", "https://b.example/2", "tavily")
    out = near_dedupe([_hit(BASE, "", "https://a.example/1"), edited])
    assert [h.url for h in out] == ["https://a.example/1"]


def test_near_dedupe_keeps_a_different_hit() -> None:
    other = _hit(
        "How to bake sourdough bread at home with a cast iron dutch oven and a long cold proof",
        "",
        "https://b.example/2",
    )
    out = near_dedupe([_hit(BASE, "", "https://a.example/1"), other])
    assert len(out) == 2


def test_near_dedupe_never_merges_short_texts() -> None:
    out = near_dedupe(
        [
            _hit("Python", "", "https://a.example/1"),
            _hit("Python", "", "https://b.example/2"),
        ]
    )
    assert len(out) == 2


def test_near_dedupe_zero_distance_keeps_an_edited_copy() -> None:
    edited = _hit(BASE + " today", "", "https://b.example/2", "tavily")
    assert (
        len(
            near_dedupe([_hit(BASE, "", "https://a.example/1"), edited], max_distance=0)
        )
        == 2
    )


def test_near_dedupe_handles_empty_input() -> None:
    assert near_dedupe([]) == []
