import hypothesis.strategies as st
from hypothesis import given, settings

from swarm_sdk.tokens import TokenBudget


@given(
    system=st.text(max_size=80),
    memories=st.lists(st.text(max_size=40), max_size=6),
    turns=st.lists(st.text(max_size=40), max_size=8),
    max_tokens=st.integers(min_value=1, max_value=40),
    tool_cap=st.integers(min_value=1, max_value=20),
)
@settings(max_examples=40)
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
    assert packed.text.startswith(packed.system[:1] or packed.system)
