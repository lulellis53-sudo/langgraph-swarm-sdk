"""WebSearch frontend tests: sink types, config, prefilter, hit cleanup, pipeline."""

import subprocess
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest
from WebSearch.backend.prefilter import prefilter_hits, unwrap_redirect
from WebSearch.frontend import SearchHit, parallel_search, registry_search
from WebSearch.frontend.hits import near_dedupe, normalize_hit
from WebSearch.frontend.websearchers import (
    NullSink,
    PrefilterPolicy,
    ProvidersConfig,
    SearcherSpec,
    SinkReport,
    load_providers,
)

# ---- Result sink types -----------------------------------------------------------------------


def test_search_hit_also_from_defaults_to_empty() -> None:
    assert SearchHit("t", "https://a.example", "s", "brave").also_from == ()


def test_null_sink_stores_nothing() -> None:
    hit = SearchHit("t", "https://a.example", "s", "brave")
    assert NullSink().store([hit]) == SinkReport(stored=0)


# ---- providers.yaml: prefilter config --------------------------------------------------------


def _load(tmp_path: Path, text: str):
    path = tmp_path / "providers.yaml"
    path.write_text(text, encoding="utf-8")
    return load_providers(path)


def test_prefilter_defaults_without_block(tmp_path: Path) -> None:
    assert _load(tmp_path, "version: 1\n").prefilter == PrefilterPolicy()


def test_prefilter_block_is_parsed_and_normalized(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        "prefilter:\n"
        "  schemes: [HTTPS]\n"
        "  blocked_domains: ['.Spam.Example', '']\n"
        "  min_snippet_chars: '12'\n"
        "  require_title: false\n",
    )
    assert cfg.prefilter == PrefilterPolicy(
        schemes=("https",),
        blocked_domains=("spam.example",),
        min_snippet_chars=12,
        require_title=False,
    )


def test_prefilter_empty_schemes_fall_back_to_default(tmp_path: Path) -> None:
    assert _load(tmp_path, "prefilter:\n  schemes: []\n").prefilter.schemes == (
        "http",
        "https",
    )


def test_prefilter_bad_number_names_the_field(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"prefilter\.min_snippet_chars"):
        _load(tmp_path, "prefilter:\n  min_snippet_chars: abc\n")


def test_prefilter_non_bool_require_title_names_the_field(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"prefilter\.require_title"):
        _load(tmp_path, "prefilter:\n  require_title: 'false'\n")


def test_packaged_providers_yaml_has_permissive_prefilter() -> None:
    assert load_providers().prefilter == PrefilterPolicy()


def test_providers_yaml_loads_from_package_root_not_nested() -> None:
    """Installed layout is ``<pkg>/providers.yaml``, not ``<pkg>/WebSearch/providers.yaml``."""
    from importlib.resources import files

    pkg_root = Path(str(files("WebSearch")))
    path = pkg_root / "providers.yaml"
    assert path.is_file()
    assert pkg_root.name == "WebSearch"
    assert not (pkg_root / "WebSearch" / "providers.yaml").is_file()
    assert load_providers(path).prefilter == PrefilterPolicy()


# ---- Prefilter -------------------------------------------------------------------------------

POLICY = PrefilterPolicy(blocked_domains=("spam.example",), min_snippet_chars=5)


def _prefilter_hit(
    url: str = "https://good.example/a", title: str = "T", snippet: str = "long enough"
) -> SearchHit:
    return SearchHit(title=title, url=url, snippet=snippet, searcher_id="brave")


@pytest.mark.parametrize(
    ("hit", "reason"),
    [
        (_prefilter_hit(url="http://[::1"), "bad_url"),
        (_prefilter_hit(url="javascript:alert(1)"), "bad_url"),
        (_prefilter_hit(url=""), "bad_url"),
        (_prefilter_hit(url="ftp://good.example/file"), "scheme"),
        (_prefilter_hit(url="https://spam.example/x"), "blocked_domain"),
        (_prefilter_hit(url="https://www.spam.example/x"), "blocked_domain"),
        (_prefilter_hit(url="https://spam.example./x"), "blocked_domain"),
        (_prefilter_hit(title="  ", snippet="long enough"), "empty"),
        (_prefilter_hit(title="", snippet=""), "empty"),
        (_prefilter_hit(snippet="abc"), "short_snippet"),
    ],
)
def test_each_rejection_reason(hit: SearchHit, reason: str) -> None:
    kept, rejected = prefilter_hits([hit], POLICY)
    assert kept == []
    assert [r.reason for r in rejected] == [reason]
    assert rejected[0].hit is hit


def test_lookalike_domain_is_not_blocked() -> None:
    kept, _ = prefilter_hits([_prefilter_hit(url="https://notspam.example/x")], POLICY)
    assert len(kept) == 1


def test_snippet_only_hit_passes_when_title_not_required() -> None:
    policy = PrefilterPolicy(require_title=False)
    kept, _ = prefilter_hits([_prefilter_hit(title="", snippet="has text")], policy)
    assert len(kept) == 1


def test_one_bad_hit_does_not_affect_the_rest_and_order_is_kept() -> None:
    first, bad, last = (
        _prefilter_hit(url="https://a.example"),
        _prefilter_hit(url="http://[::1"),
        _prefilter_hit(url="https://b.example"),
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
        "https://google.abc.de/url?q=https://target.example",
        "https://google.foo.io/url?q=https://target.example",
    ],
)
def test_unwrap_leaves_other_urls_alone(url: str) -> None:
    assert unwrap_redirect(url) == url


def test_unwrap_country_google_host() -> None:
    url = "https://www.google.co.uk/url?q=https://target.example/p"
    assert unwrap_redirect(url) == "https://target.example/p"


def test_policy_domains_are_matched_case_insensitively() -> None:
    policy = PrefilterPolicy(blocked_domains=("Spam.Example",))
    kept, _ = prefilter_hits([_prefilter_hit(url="https://spam.example/x")], policy)
    assert kept == []


def test_prefilter_replaces_redirect_url_with_target() -> None:
    hit = _prefilter_hit(url="https://www.google.com/url?q=https://target.example/p")
    kept, _ = prefilter_hits([hit], POLICY)
    assert [h.url for h in kept] == ["https://target.example/p"]


# ---- Hit normalization and near-dedupe -------------------------------------------------------

BASE = (
    "Python 3.14 release notes: free-threaded build, deferred annotations, "
    "t-strings, and a new zstd compression module for the standard library"
)


def _text_hit(
    title: str = "Title",
    snippet: str = "snippet",
    url: str = "https://example.com/a",
    searcher_id: str = "brave",
) -> SearchHit:
    return SearchHit(title=title, url=url, snippet=snippet, searcher_id=searcher_id)


def test_normalize_cleans_title_and_snippet() -> None:
    hit = normalize_hit(_text_hit(title="  Café &amp; Bar​  ", snippet="a  b\n\na b"))
    assert (hit.title, hit.snippet) == ("Café & Bar", "a b")


def test_site_suffix_is_stripped_when_it_names_the_host() -> None:
    hit = normalize_hit(
        _text_hit(title="Intro to asyncio | Example", url="https://www.example.com/a")
    )
    assert hit.title == "Intro to asyncio"


def test_site_suffix_with_spaces_and_dash_variants() -> None:
    hit = normalize_hit(
        _text_hit(title="Best answer – Stack Overflow", url="https://stackoverflow.com/q/1")
    )
    assert hit.title == "Best answer"


def test_site_suffix_matches_a_subdomain_label() -> None:
    hit = normalize_hit(
        _text_hit(
            title="asyncio - Python",
            url="https://docs.python.org/3/library/asyncio.html",
        )
    )
    assert hit.title == "asyncio"


def test_other_separator_text_is_kept() -> None:
    hit = normalize_hit(_text_hit(title="Pros | Cons of rust", url="https://example.com/a"))
    assert hit.title == "Pros | Cons of rust"


def test_title_that_is_only_a_suffix_is_kept() -> None:
    hit = normalize_hit(_text_hit(title="| Example", url="https://example.com/a"))
    assert hit.title == "| Example"


def test_normalize_handles_empty_and_non_ascii() -> None:
    hit = normalize_hit(_text_hit(title="", snippet="日本語のテキスト"))
    assert (hit.title, hit.snippet) == ("", "日本語のテキスト")


def test_near_dedupe_merges_identical_text_and_records_other_searchers() -> None:
    first = _text_hit(BASE, "", "https://a.example/1", "brave")
    second = _text_hit(BASE, "", "https://b.example/2", "tavily")
    third = _text_hit(BASE, "", "https://c.example/3", "tavily")
    out = near_dedupe([first, second, third])
    assert [h.url for h in out] == ["https://a.example/1"]
    assert out[0].also_from == ("tavily",)


def test_near_dedupe_same_searcher_is_not_listed_in_also_from() -> None:
    out = near_dedupe(
        [
            _text_hit(BASE, "", "https://a.example/1"),
            _text_hit(BASE, "", "https://b.example/2"),
        ]
    )
    assert len(out) == 1
    assert out[0].also_from == ()


def test_near_dedupe_merges_a_lightly_edited_copy() -> None:
    edited = _text_hit(BASE + " today", "", "https://b.example/2", "tavily")
    out = near_dedupe([_text_hit(BASE, "", "https://a.example/1"), edited])
    assert [h.url for h in out] == ["https://a.example/1"]


def test_near_dedupe_keeps_a_different_hit() -> None:
    other = _text_hit(
        "How to bake sourdough bread at home with a cast iron dutch oven and a long cold proof",
        "",
        "https://b.example/2",
    )
    out = near_dedupe([_text_hit(BASE, "", "https://a.example/1"), other])
    assert len(out) == 2


def test_near_dedupe_never_merges_short_texts() -> None:
    out = near_dedupe(
        [
            _text_hit("Python", "", "https://a.example/1"),
            _text_hit("Python", "", "https://b.example/2"),
        ]
    )
    assert len(out) == 2


def test_near_dedupe_zero_distance_keeps_an_edited_copy() -> None:
    edited = _text_hit(BASE + " today", "", "https://b.example/2", "tavily")
    assert (
        len(near_dedupe([_text_hit(BASE, "", "https://a.example/1"), edited], max_distance=0)) == 2
    )


def test_near_dedupe_handles_empty_input() -> None:
    assert near_dedupe([]) == []


# ---- parallel_search / registry_search pipeline ----------------------------------------------

ROOT = Path(__file__).resolve().parents[1]


def _config(*ids: str, policy: PrefilterPolicy | None = None) -> ProvidersConfig:
    return ProvidersConfig(
        version=1,
        searchers=tuple(SearcherSpec(id=i, kind="websearcher") for i in ids),
        extractor_order=("regex",),
        prefilter=policy or PrefilterPolicy(),
    )


def _backend(hits: Sequence[SearchHit]):
    return lambda query, spec: [replace(h, searcher_id=spec.id) for h in hits]


def _search_hit(
    url: str,
    title: str = "Some title",
    snippet: str = "a reasonably long snippet",
    tokens: int = 0,
) -> SearchHit:
    return SearchHit(title=title, url=url, snippet=snippet, searcher_id="x", api_tokens=tokens)


class _RecordingSink:
    def __init__(self) -> None:
        self.calls: list[list[SearchHit]] = []

    def store(self, hits: Sequence[SearchHit]) -> SinkReport:
        self.calls.append(list(hits))
        return SinkReport(stored=len(hits))


class _FailingSink:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def store(self, hits: Sequence[SearchHit]) -> SinkReport:
        raise self.error


def test_junk_hit_returned_by_two_providers_does_not_outrank_a_clean_hit() -> None:
    junk, clean = _search_hit("https://spam.example/x"), _search_hit("https://good.example/y")
    cfg = _config("a", "b", policy=PrefilterPolicy(blocked_domains=("spam.example",)))
    backends = {"a": _backend([junk, clean]), "b": _backend([junk])}
    assert [h.url for h in parallel_search("q", config=cfg, backends=backends)] == [
        "https://good.example/y"
    ]


def test_all_hits_rejected_returns_empty_and_skips_the_sink() -> None:
    sink = _RecordingSink()
    cfg = _config("a", policy=PrefilterPolicy(schemes=("ftp",)))
    assert (
        parallel_search(
            "q",
            config=cfg,
            backends={"a": _backend([_search_hit("https://a.example")])},
            sink=sink,
        )
        == []
    )
    assert sink.calls == []


def test_titles_are_normalized_and_near_duplicates_removed_before_the_cap() -> None:
    dup_a = _search_hit(
        "https://a.example/1",
        title="Python 3.14 release notes free-threaded build and t-strings overview",
        snippet="",
    )
    dup_b = _search_hit(
        "https://b.example/2",
        title="Python 3.14 release notes free-threaded build and t-strings overview",
        snippet="",
    )
    other = _search_hit(
        "https://c.example/3",
        title="Sourdough bread with a cast iron dutch oven overnight",
        snippet="",
    )
    out = parallel_search(
        "q",
        config=_config("a"),
        backends={"a": _backend([dup_a, dup_b, other])},
        limit=2,
    )
    assert [h.url for h in out] == ["https://a.example/1", "https://c.example/3"]


def test_near_distance_none_disables_near_dedupe() -> None:
    twin = "Python 3.14 release notes free-threaded build and t-strings overview"
    hits = [
        _search_hit("https://a.example/1", title=twin, snippet=""),
        _search_hit("https://b.example/2", title=twin, snippet=""),
    ]
    out = parallel_search(
        "q", config=_config("a"), backends={"a": _backend(hits)}, near_distance=None
    )
    assert len(out) == 2


def test_sink_receives_the_final_capped_list() -> None:
    sink = _RecordingSink()
    hits = [
        _search_hit(
            f"https://h{i}.example/",
            title=f"Distinct result number {i} about topic {i}",
        )
        for i in range(4)
    ]
    out = parallel_search(
        "q", config=_config("a"), backends={"a": _backend(hits)}, limit=2, sink=sink
    )
    assert sink.calls == [out]
    assert len(out) == 2


def test_sink_oserror_still_returns_results() -> None:
    out = parallel_search(
        "q",
        config=_config("a"),
        backends={"a": _backend([_search_hit("https://a.example/")])},
        sink=_FailingSink(OSError("disk full")),
    )
    assert [h.url for h in out] == ["https://a.example/"]


def test_sink_programming_error_propagates() -> None:
    with pytest.raises(ValueError, match="bug"):
        parallel_search(
            "q",
            config=_config("a"),
            backends={"a": _backend([_search_hit("https://a.example/")])},
            sink=_FailingSink(ValueError("bug")),
        )


def test_api_tokens_total_survives_prefilter_and_sits_on_the_first_hit() -> None:
    rejected_head = _search_hit("https://spam.example/x", tokens=30)
    kept = _search_hit("https://good.example/y", tokens=0)
    cfg = _config("a", "b", policy=PrefilterPolicy(blocked_domains=("spam.example",)))
    backends = {
        "a": _backend([rejected_head, kept]),
        "b": _backend(
            [
                replace(
                    _search_hit(
                        "https://other.example/z",
                        title="A completely different page about bread",
                    ),
                    api_tokens=12,
                )
            ]
        ),
    }
    out = parallel_search("q", config=cfg, backends=backends)
    assert sum(h.api_tokens for h in out) == 42
    assert out[0].api_tokens == 42


def test_registry_search_fails_over_when_first_batch_is_all_rejected() -> None:
    cfg = _config("a", "b", policy=PrefilterPolicy(blocked_domains=("spam.example",)))
    backends = {
        "a": _backend([_search_hit("https://spam.example/x")]),
        "b": _backend([_search_hit("https://good.example/y")]),
    }
    out = registry_search("q", config=cfg, backends=backends)
    assert [h.url for h in out] == ["https://good.example/y"]


def test_registry_search_drops_rejected_hits_from_a_mixed_batch() -> None:
    cfg = _config("a", policy=PrefilterPolicy(blocked_domains=("spam.example",)))
    backends = {
        "a": _backend(
            [
                _search_hit("https://spam.example/x"),
                _search_hit("https://good.example/y"),
            ]
        )
    }
    out = registry_search("q", config=cfg, backends=backends)
    assert [h.url for h in out] == ["https://good.example/y"]


@pytest.mark.parametrize("first", ["frontend", "backend"])
def test_either_package_can_be_imported_first(first: str) -> None:
    code = (
        "import sys; sys.path.insert(0, 'tests'); import conftest; "
        f"import WebSearch.{first}; import WebSearch.frontend, WebSearch.backend"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_import_websearch_does_not_eager_load_pipeline() -> None:
    """``import WebSearch`` must not pull agent_tools/backend/frontend/midend until used."""
    code = (
        "import sys, WebSearch\n"
        "mods = set(sys.modules)\n"
        "assert 'WebSearch.agent_tools' not in mods\n"
        "assert 'WebSearch.backend' not in mods\n"
        "assert 'WebSearch.midend' not in mods\n"
        "assert callable(WebSearch.run_pipeline)\n"
        "from WebSearch import search_hits\n"
        "assert callable(search_hits)\n"
        "assert 'WebSearch.agent_tools' in sys.modules\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr

