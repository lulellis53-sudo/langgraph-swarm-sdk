"""Offline tests for technews.prediction.harvest (fake search_fn only)."""

from __future__ import annotations

from dataclasses import dataclass

from technews.prediction.harvest import (
    UNAVAILABLE,
    TopicHarvester,
    TopicSignal,
    default_query,
    top_titles,
)


@dataclass(frozen=True, slots=True)
class FakeHit:
    title: str
    url: str
    snippet: str = ""
    source: str = "fake"


def hits(*titles: str) -> list[FakeHit]:
    return [FakeHit(t, f"https://n.example/{i}") for i, t in enumerate(titles)]


# ---- pure helpers -----------------------------------------------------------------------------


def test_default_query_appends_news() -> None:
    assert default_query("AI regulation") == "AI regulation news"


def test_top_titles_dedupes_case_and_whitespace() -> None:
    titles = ["Big  Deal", "big deal", "  Big   deal  ", "Other"]
    assert top_titles(titles) == ["Big  Deal", "Other"]


def test_top_titles_caps_at_five_and_skips_empty() -> None:
    titles = [f"t{i}" for i in range(8)] + ["", "   "]
    out = top_titles(titles)
    assert out == [f"t{i}" for i in range(5)]


# ---- harvester --------------------------------------------------------------------------------


def test_check_topic_uses_injected_fake_and_default_query() -> None:
    seen: list[str] = []

    def fake(q: str) -> list[FakeHit]:
        seen.append(q)
        return hits("a", "b", "a", "b")

    sig = TopicHarvester(fake).check_topic("climate")
    assert seen == ["climate news"]
    assert isinstance(sig, TopicSignal)
    assert sig == TopicSignal("climate", "climate news", 4, ["a", "b"], "injected")


def test_check_topic_honors_explicit_query() -> None:
    seen: list[str] = []
    TopicHarvester(lambda q: (seen.append(q), hits())[1]).check_topic("climate", query="q")
    assert seen == ["q"]


def test_check_topic_empty_result() -> None:
    sig = TopicHarvester(lambda q: []).check_topic("quiet topic")
    assert sig.hits == 0 and sig.top_titles == [] and sig.source == "injected"


def test_check_topics_preserves_order_and_caps_titles() -> None:
    def fake(q: str) -> list[FakeHit]:
        return hits(*[f"{q}-t{i}" for i in range(7)])

    sigs = TopicHarvester(fake).check_topics(["x", "y"])
    assert [s.topic for s in sigs] == ["x", "y"]
    assert all(s.hits == 7 and len(s.top_titles) == 5 for s in sigs)


def test_check_topic_degrades_without_raising(caplog) -> None:
    def boom(q: str) -> list[FakeHit]:
        raise RuntimeError("backend down")

    harvester = TopicHarvester(boom)
    with caplog.at_level("WARNING"):
        sig = harvester.check_topic("any")
    assert sig == TopicSignal("any", "any news", 0, [], UNAVAILABLE)
    harvester.check_topic("any")  # second call: still degrades, no raise
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1  # logged once
