import pytest
from WebSearch.frontend import SearchHit
from WebSearch.frontend.prefilter import prefilter_hits, unwrap_redirect
from WebSearch.frontend.providers import PrefilterPolicy

POLICY = PrefilterPolicy(blocked_domains=("spam.example",), min_snippet_chars=5)


def _hit(
    url: str = "https://good.example/a", title: str = "T", snippet: str = "long enough"
) -> SearchHit:
    return SearchHit(title=title, url=url, snippet=snippet, searcher_id="brave")


@pytest.mark.parametrize(
    ("hit", "reason"),
    [
        (_hit(url="http://[::1"), "bad_url"),
        (_hit(url="javascript:alert(1)"), "bad_url"),
        (_hit(url=""), "bad_url"),
        (_hit(url="ftp://good.example/file"), "scheme"),
        (_hit(url="https://spam.example/x"), "blocked_domain"),
        (_hit(url="https://www.spam.example/x"), "blocked_domain"),
        (_hit(url="https://spam.example./x"), "blocked_domain"),
        (_hit(title="  ", snippet="long enough"), "empty"),
        (_hit(title="", snippet=""), "empty"),
        (_hit(snippet="abc"), "short_snippet"),
    ],
)
def test_each_rejection_reason(hit: SearchHit, reason: str) -> None:
    kept, rejected = prefilter_hits([hit], POLICY)
    assert kept == []
    assert [r.reason for r in rejected] == [reason]
    assert rejected[0].hit is hit


def test_lookalike_domain_is_not_blocked() -> None:
    kept, _ = prefilter_hits([_hit(url="https://notspam.example/x")], POLICY)
    assert len(kept) == 1


def test_snippet_only_hit_passes_when_title_not_required() -> None:
    policy = PrefilterPolicy(require_title=False)
    kept, _ = prefilter_hits([_hit(title="", snippet="has text")], policy)
    assert len(kept) == 1


def test_one_bad_hit_does_not_affect_the_rest_and_order_is_kept() -> None:
    first, bad, last = (
        _hit(url="https://a.example"),
        _hit(url="http://[::1"),
        _hit(url="https://b.example"),
    )
    kept, rejected = prefilter_hits([first, bad, last], POLICY)
    assert kept == [first, last]
    assert [r.hit for r in rejected] == [bad]


def test_unwrap_google_redirect() -> None:
    url = "https://www.google.com/url?q=https%3A%2F%2Ftarget.example%2Fpage&sa=U"
    assert unwrap_redirect(url) == "https://target.example/page"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/url?q=https://target.example",
        "https://www.google.com/url?q=javascript:alert(1)",
        "https://www.google.com/search?q=https://target.example",
        "http://[::1",
        "https://good.example/a",
        "https://google.evil.com/url?q=https://target.example",
        "https://google.com.attacker.net/url?q=https://target.example",
    ],
)
def test_unwrap_leaves_other_urls_alone(url: str) -> None:
    assert unwrap_redirect(url) == url


def test_unwrap_country_google_host() -> None:
    url = "https://www.google.co.uk/url?q=https://target.example/p"
    assert unwrap_redirect(url) == "https://target.example/p"


def test_policy_domains_are_matched_case_insensitively() -> None:
    policy = PrefilterPolicy(blocked_domains=("Spam.Example",))
    kept, _ = prefilter_hits([_hit(url="https://spam.example/x")], policy)
    assert kept == []


def test_prefilter_replaces_redirect_url_with_target() -> None:
    hit = _hit(url="https://www.google.com/url?q=https://target.example/p")
    kept, _ = prefilter_hits([hit], POLICY)
    assert [h.url for h in kept] == ["https://target.example/p"]
