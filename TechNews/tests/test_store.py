import sqlite3

from technews.models import Article
from technews.store import Store


def art(
    url="https://e.com/a",
    title="T",
    excerpt="E",
    published="2026-10-07T00:00:00+00:00",
    category="ai",
    source="S",
    tags=(),
):
    return Article(
        url=url,
        source=source,
        category=category,
        title=title,
        published=published,
        excerpt=excerpt,
        tags=tags,
    )


def test_add_new_then_duplicate(tmp_path):
    with Store(tmp_path / "t.db") as store:
        assert store.add(art()) is True
        assert store.add(art()) is False
        assert store.count() == 1


def test_same_story_two_url_spellings_is_one_row(tmp_path):
    with Store(tmp_path / "t.db") as store:
        assert store.add(art(url="HTTP://Example.com/a/?utm_source=x#frag", title="X")) is True
        assert store.add(art(url="http://example.com/a", title="Y")) is False
        assert store.count() == 1
        assert store.recent()[0].url == "http://example.com/a"


def test_syndicated_copy_with_same_title_and_excerpt_is_one_row(tmp_path):
    with Store(tmp_path / "t.db") as store:
        assert store.add(art(url="https://a.com/1", title="Same", excerpt="Same")) is True
        assert store.add(art(url="https://b.com/2", title="Same", excerpt="Same")) is False


def test_add_many_returns_inserted_count(tmp_path):
    with Store(tmp_path / "t.db") as store:
        n = store.add_many(
            [
                art(url="https://e.com/1", title="1"),
                art(url="https://e.com/2", title="2"),
                art(url="https://e.com/1", title="1"),
            ]
        )
        assert n == 2


def test_recent_orders_newest_first_nulls_last_and_filters_category(tmp_path):
    with Store(tmp_path / "t.db") as store:
        store.add(art(url="https://e.com/old", title="old", published="2026-10-01T00:00:00+00:00"))
        store.add(art(url="https://e.com/new", title="new", published="2026-10-05T00:00:00+00:00"))
        store.add(art(url="https://e.com/none", title="none", published=None))
        store.add(
            art(
                url="https://e.com/hw",
                title="hw",
                category="hardware",
                published="2026-10-06T00:00:00+00:00",
            )
        )
        assert [a.title for a in store.recent()] == ["hw", "new", "old", "none"]
        assert [a.title for a in store.recent(category="ai")] == ["new", "old", "none"]
        assert len(store.recent(limit=2)) == 2


def test_roundtrip_preserves_tags_and_unicode(tmp_path):
    with Store(tmp_path / "t.db") as store:
        store.add(art(title="Ação 🚀", tags=("gpu", "ia")))
        got = store.recent()[0]
        assert got.title == "Ação 🚀"
        assert got.tags == ("gpu", "ia")


def test_persists_across_reopen(tmp_path):
    path = tmp_path / "t.db"
    with Store(path) as store:
        store.add(art())
    with Store(path) as store:
        assert store.count() == 1


def test_creates_parent_directory(tmp_path):
    with Store(tmp_path / "nested" / "dir" / "t.db") as store:
        assert store.count() == 0


def test_uses_parameterized_queries_for_hostile_title(tmp_path):
    with Store(tmp_path / "t.db") as store:
        store.add(art(title="x'); DROP TABLE articles;--"))
        assert store.count() == 1
    conn = sqlite3.connect(tmp_path / "t.db")
    assert conn.execute("select count(*) from articles").fetchone()[0] == 1
