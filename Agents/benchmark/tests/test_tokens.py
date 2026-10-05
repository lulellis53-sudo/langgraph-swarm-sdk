"""Token budgets and usage rollups — property tests plus a few examples."""

from __future__ import annotations

import threading
from typing import cast

import hypothesis.strategies as st
from hypothesis import assume, given, settings

from swarm_sdk.observability.usage import UsageLog, estimate_cost_usd
from swarm_sdk.prompting import budget
from swarm_sdk.prompting.budget import TokenBudget, count_text

_TEXT = st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc")), max_size=64)
_NONEMPTY = _TEXT.filter(lambda s: bool(s.strip()))
_HYP = settings(max_examples=50, deadline=None)


@_HYP
@given(text=_TEXT)
def test_count_text_non_negative(text: str) -> None:
    assert count_text(text) >= 0
    assert count_text("") == 0


@_HYP
@given(
    system=_TEXT,
    memories=st.lists(_TEXT, max_size=8),
    turns=st.lists(_TEXT, max_size=10),
    max_tokens=st.integers(min_value=1, max_value=48),
    tool_cap=st.integers(min_value=1, max_value=24),
)
def test_packed_context_never_exceeds_budget(
    system: str,
    memories: list[str],
    turns: list[str],
    max_tokens: int,
    tool_cap: int,
) -> None:
    budget = TokenBudget(max_tokens=max_tokens, tool_cap=tool_cap)
    packed = budget.pack(system=system, memories=memories, turns=turns)
    assert budget.count(packed.text) <= max_tokens
    if packed.system:
        assert packed.text.startswith(packed.system)


@_HYP
@given(
    system=_NONEMPTY,
    max_tokens=st.integers(min_value=1, max_value=32),
)
def test_pack_preserves_system_when_nothing_else_fits(system: str, max_tokens: int) -> None:
    budget = TokenBudget(max_tokens=max_tokens, tool_cap=8)
    packed = budget.pack(system=system, memories=[], turns=[])
    assert budget.count(packed.text) <= max_tokens
    assert packed.user == ""


@_HYP
@given(
    rows=st.lists(
        st.tuples(
            st.sampled_from(["coder", "cache", "router", "tester"]),
            st.integers(min_value=0, max_value=10_000),
            st.booleans(),
        ),
        max_size=40,
    ),
)
def test_usage_summary_sums_tokens_per_agent(rows: list[tuple[str, int, bool]]) -> None:
    log = UsageLog()
    expected: dict[str, int] = {}
    for agent, tokens, cached in rows:
        log.add(agent, tokens, cached)
        expected[agent] = expected.get(agent, 0) + tokens
    summary: dict[str, int] = {}
    for row in log.summary():
        agent = row["agent"]
        tokens = row["tokens"]
        assert isinstance(agent, str)
        assert isinstance(tokens, int)
        summary[agent] = tokens
    if not rows:
        assert summary == {}
    else:
        assert summary == expected
        assert list(summary) == sorted(summary)


def test_usage_summary_example_groups_tokens() -> None:
    log = UsageLog()
    log.add("coder", 10, False)
    log.add("coder", 5, False)
    log.add("cache", 0, True)
    assert {row["agent"]: row["tokens"] for row in log.summary()} == {"cache": 0, "coder": 15}


@_HYP
@given(max_tokens=st.integers(max_value=0))
def test_token_budget_rejects_non_positive_max(max_tokens: int) -> None:
    assume(max_tokens < 1)
    try:
        TokenBudget(max_tokens=max_tokens)
    except ValueError:
        return
    raise AssertionError("expected ValueError for max_tokens < 1")


class _CountingTok:
    """Tokenizer double that counts ``encode`` calls and scales by length."""

    def __init__(self, per_char: int = 1) -> None:
        self.calls = 0
        self.per_char = per_char

    def encode(self, text: str) -> list[int]:
        self.calls += 1
        return [0] * (len(text) * self.per_char)


def test_count_text_cache_avoids_reencode() -> None:
    budget._COUNT_CACHE.clear()
    tok = _CountingTok()
    assert count_text("hello world", tok) == 11
    assert count_text("hello world", tok) == 11
    assert tok.calls == 1


def test_count_text_cache_is_per_tokenizer() -> None:
    budget._COUNT_CACHE.clear()
    one, two = _CountingTok(1), _CountingTok(2)
    assert count_text("abc", one) == 3
    assert count_text("abc", two) == 6


def test_count_text_cache_is_bounded() -> None:
    budget._COUNT_CACHE.clear()
    tok = _CountingTok()
    for i in range(budget._COUNT_CACHE_MAX + 100):
        count_text(f"t{i} x", tok)
    assert len(budget._COUNT_CACHE) <= budget._COUNT_CACHE_MAX


def test_count_text_cache_threadsafe() -> None:
    budget._COUNT_CACHE.clear()
    tok = _CountingTok()
    errors: list[BaseException] = []

    def work(offset: int) -> None:
        try:
            for i in range(300):
                count_text(f"w{offset}-{i}", tok)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(budget._COUNT_CACHE) <= budget._COUNT_CACHE_MAX


def test_usage_add_new_kwargs_are_optional() -> None:
    log = UsageLog()
    log.add("coder", 10, False)
    assert log.summary() == [
        {"agent": "coder", "tokens": 10, "latency_ms_total": 0.0, "cost_estimate_usd": 0.0}
    ]


def test_usage_summary_sums_latency_and_cost() -> None:
    log = UsageLog()
    log.add("coder", 1000, False, latency_ms=12.5, model="openai:gpt-4o-mini")
    log.add("coder", 1000, False, latency_ms=7.5, model="openai:gpt-4o-mini")
    (row,) = log.summary()
    assert row["tokens"] == 2000
    assert row["latency_ms_total"] == 20.0
    assert cast(float, row["cost_estimate_usd"]) > 0.0


def test_estimate_cost_unknown_model_is_zero() -> None:
    assert estimate_cost_usd("nope:model", 5000) == 0.0
    assert estimate_cost_usd("", 5000) == 0.0


def test_packed_prompt_prefix_suffix() -> None:
    from swarm_sdk.prompting.budget import PackedPrompt

    p = PackedPrompt(system="sys", user="body")
    assert (p.prefix, p.suffix) == ("sys", "body")
    assert p.text == "sys\nbody"
