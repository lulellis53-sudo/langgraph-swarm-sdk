from WebSearch.frontend import SearchHit
from WebSearch.frontend.models import NullSink, SinkReport


def test_search_hit_also_from_defaults_to_empty() -> None:
    assert SearchHit("t", "https://a.example", "s", "brave").also_from == ()


def test_null_sink_stores_nothing() -> None:
    hit = SearchHit("t", "https://a.example", "s", "brave")
    assert NullSink().store([hit]) == SinkReport(stored=0)
