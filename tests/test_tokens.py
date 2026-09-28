"""Token budgets and usage rollups — property tests plus a few examples."""

from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import assume, given, settings

from swarm_sdk.tokens import TokenBudget, count_text
from swarm_sdk.usage import UsageLog

_TEXT = st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc")), max_size=64)
_NONEMPTY = _TEXT.filter(lambda s: bool(s.strip()))


@given(text=_TEXT)
@settings(max_examples=60)
def test_count_text_non_negative(text: str) -> None:
    assert count_text(text) >= 0
    assert count_text("") == 0


@given(
    system=_TEXT,
    memories=st.lists(_TEXT, max_size=8),
    turns=st.lists(_TEXT, max_size=10),
    max_tokens=st.integers(min_value=1, max_value=48),
    tool_cap=st.integers(min_value=1, max_value=24),
)
@settings(max_examples=50)
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
    assert packed.system
    assert packed.text.startswith(packed.system)


@given(
    system=_NONEMPTY,
    max_tokens=st.integers(min_value=1, max_value=32),
)
@settings(max_examples=40)
def test_pack_preserves_system_when_nothing_else_fits(system: str, max_tokens: int) -> None:
    budget = TokenBudget(max_tokens=max_tokens, tool_cap=8)
    packed = budget.pack(system=system, memories=[], turns=[])
    assert budget.count(packed.text) <= max_tokens
    assert packed.user == ""


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
@settings(max_examples=50)
def test_usage_summary_sums_tokens_per_agent(rows: list[tuple[str, int, bool]]) -> None:
    log = UsageLog()
    expected: dict[str, int] = {}
    for agent, tokens, cached in rows:
        log.add(agent, tokens, cached)
        expected[agent] = expected.get(agent, 0) + tokens
    summary = {row["agent"]: row["tokens"] for row in log.summary()}
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


@given(max_tokens=st.integers(max_value=0))
@settings(max_examples=10)
def test_token_budget_rejects_non_positive_max(max_tokens: int) -> None:
    assume(max_tokens < 1)
    try:
        TokenBudget(max_tokens=max_tokens)
    except ValueError:
        return
    raise AssertionError("expected ValueError for max_tokens < 1")
