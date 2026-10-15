from pathlib import Path

import pytest

from technews.sources import SourceConfigError, load_sources


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "sources.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_loads_all_kinds(tmp_path):
    path = write(
        tmp_path,
        """
sources:
  - {name: A, category: ai, kind: feed, url: "https://a.example/feed"}
  - {name: HN, category: code, kind: hn, limit: 5}
  - {name: Apple, category: bigtech, kind: search, query: "site:apple.com/newsroom"}
  - {name: Disabled, category: ai, kind: feed, url: "https://o.example/f", enabled: false}
""",
    )
    got = load_sources(path)
    assert [s.name for s in got] == ["A", "HN", "Apple", "Disabled"]
    assert got[1].limit == 5
    assert got[3].enabled is False
    assert got[0].url == "https://a.example/feed"


def test_empty_file_is_error(tmp_path):
    with pytest.raises(SourceConfigError, match="no sources"):
        load_sources(write(tmp_path, ""))


def test_empty_list_is_error(tmp_path):
    with pytest.raises(SourceConfigError, match="no sources"):
        load_sources(write(tmp_path, "sources: []"))


def test_unknown_category_names_the_entry(tmp_path):
    path = write(tmp_path, "sources:\n  - {name: X, category: sports, kind: hn}\n")
    with pytest.raises(SourceConfigError, match="X.*category"):
        load_sources(path)


def test_feed_requires_url(tmp_path):
    path = write(tmp_path, "sources:\n  - {name: X, category: ai, kind: feed}\n")
    with pytest.raises(SourceConfigError, match="X.*url"):
        load_sources(path)


def test_search_requires_query(tmp_path):
    path = write(tmp_path, "sources:\n  - {name: X, category: ai, kind: search}\n")
    with pytest.raises(SourceConfigError, match="X.*query"):
        load_sources(path)


def test_duplicate_names_rejected(tmp_path):
    path = write(
        tmp_path,
        "sources:\n  - {name: X, category: ai, kind: hn}\n  - {name: X, category: ai, kind: hn}\n",
    )
    with pytest.raises(SourceConfigError, match="duplicate.*X"):
        load_sources(path)


def test_non_http_feed_url_rejected(tmp_path):
    path = write(
        tmp_path,
        "sources:\n  - {name: X, category: ai, kind: feed, url: 'file:///etc/passwd'}\n",
    )
    with pytest.raises(SourceConfigError, match="X.*http"):
        load_sources(path)


def test_shipped_registry_is_valid_and_covers_every_category():
    shipped = Path(__file__).parent.parent / "sources.yaml"
    got = load_sources(shipped)
    assert {s.category for s in got} == {"bigtech", "git", "hardware", "code", "ai"}
    assert sum(1 for s in got if s.category == "bigtech") >= 30


def test_yaml_boolean_name_gives_quote_hint(tmp_path):
    path = write(tmp_path, "sources:\n  - {name: Off, category: ai, kind: hn}\n")
    with pytest.raises(SourceConfigError, match="quote"):
        load_sources(path)
