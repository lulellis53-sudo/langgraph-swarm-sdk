import subprocess
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest
from WebSearch.frontend import SearchHit, parallel_search, registry_search
from WebSearch.frontend.models import SinkReport
from WebSearch.frontend.providers import PrefilterPolicy, ProvidersConfig, SearcherSpec

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


def _hit(
    url: str,
    title: str = "Some title",
    snippet: str = "a reasonably long snippet",
    tokens: int = 0,
) -> SearchHit:
    return SearchHit(
        title=title, url=url, snippet=snippet, searcher_id="x", api_tokens=tokens
    )


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
    junk, clean = _hit("https://spam.example/x"), _hit("https://good.example/y")
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
            backends={"a": _backend([_hit("https://a.example")])},
            sink=sink,
        )
        == []
    )
    assert sink.calls == []


def test_titles_are_normalized_and_near_duplicates_removed_before_the_cap() -> None:
    dup_a = _hit(
        "https://a.example/1",
        title="Python 3.14 release notes free-threaded build and t-strings overview",
        snippet="",
    )
    dup_b = _hit(
        "https://b.example/2",
        title="Python 3.14 release notes free-threaded build and t-strings overview",
        snippet="",
    )
    other = _hit(
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
        _hit("https://a.example/1", title=twin, snippet=""),
        _hit("https://b.example/2", title=twin, snippet=""),
    ]
    out = parallel_search(
        "q", config=_config("a"), backends={"a": _backend(hits)}, near_distance=None
    )
    assert len(out) == 2


def test_sink_receives_the_final_capped_list() -> None:
    sink = _RecordingSink()
    hits = [
        _hit(
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
        backends={"a": _backend([_hit("https://a.example/")])},
        sink=_FailingSink(OSError("disk full")),
    )
    assert [h.url for h in out] == ["https://a.example/"]


def test_sink_programming_error_propagates() -> None:
    with pytest.raises(ValueError, match="bug"):
        parallel_search(
            "q",
            config=_config("a"),
            backends={"a": _backend([_hit("https://a.example/")])},
            sink=_FailingSink(ValueError("bug")),
        )


def test_api_tokens_total_survives_prefilter_and_sits_on_the_first_hit() -> None:
    rejected_head = _hit("https://spam.example/x", tokens=30)
    kept = _hit("https://good.example/y", tokens=0)
    cfg = _config("a", "b", policy=PrefilterPolicy(blocked_domains=("spam.example",)))
    backends = {
        "a": _backend([rejected_head, kept]),
        "b": _backend(
            [
                replace(
                    _hit(
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
        "a": _backend([_hit("https://spam.example/x")]),
        "b": _backend([_hit("https://good.example/y")]),
    }
    out = registry_search("q", config=cfg, backends=backends)
    assert [h.url for h in out] == ["https://good.example/y"]


def test_registry_search_drops_rejected_hits_from_a_mixed_batch() -> None:
    cfg = _config("a", policy=PrefilterPolicy(blocked_domains=("spam.example",)))
    backends = {
        "a": _backend([_hit("https://spam.example/x"), _hit("https://good.example/y")])
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
