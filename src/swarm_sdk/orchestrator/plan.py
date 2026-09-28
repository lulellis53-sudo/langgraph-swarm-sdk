"""Plan models for the orchestration engine: steps, waves, results.

A :class:`Plan` is a validated, JSON-serializable description of work produced
by the Orchestrator agent. Steps declare their dependencies explicitly; the
plan is executed in topological *waves* — steps in the same wave have no
interdependencies and run in parallel (see :mod:`swarm_sdk.orchestrator.graph`).

Token-saving note: a step receives only the outputs of the step ids listed in
``inputs`` (defaulting to ``depends_on``), never the full transcript.

Coder parallelism: sibling Coder steps in the same wave must claim disjoint
``files`` so two workers never write the same path concurrently.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from pydantic import BaseModel, Field, field_validator

#: Agent name that owns write-scoped implementation steps.
CODER_AGENT = "Coder"


def normalize_claimed_file(path: str) -> str:
    """Normalize a step's write-path to a relative POSIX path.

    Args:
        path: Claimed file path from the plan JSON (any OS separator).

    Returns:
        A relative POSIX path with ``.`` collapsed and duplicates left to the
        caller to unique.

    Raises:
        ValueError: When the path is empty, absolute, or contains ``..``.
    """
    raw = path.strip().replace("\\", "/")
    if not raw:
        raise ValueError("claimed file path must be non-empty")
    parsed = PurePosixPath(raw)
    if parsed.is_absolute() or any(part == ".." for part in parsed.parts):
        raise ValueError(f"claimed file must be a relative path without '..': {path}")
    return str(parsed)


class PlanStep(BaseModel):
    """One unit of work assigned to exactly one agent.

    Attributes:
        id: Unique step identifier, e.g. ``"S1"``. Referenced by other steps'
            ``depends_on`` / ``inputs`` lists.
        title: Short human-readable label for logs and UI.
        description: The full instruction the worker agent receives as its user
            prompt. Keep it self-contained; it is all the context the step gets
            beyond its declared ``inputs``.
        agent: Name of the agent that owns this step. Must exist in the loaded
            ``Agents/{Name}/agent.yaml`` manifests.
        task: Optional ``agent.yaml`` task id (e.g. ``"implement_in_files"``).
            Empty means "any task that agent accepts".
        files: Exclusive relative write-paths this step may change. Required
            and disjoint when two or more Coder steps share a wave.
        depends_on: Step ids that must complete (with status ``ok``) before this
            step may start. Defines the wave barrier structure.
        inputs: Step ids whose outputs are injected into this step's prompt.
            Defaults to ``depends_on`` when empty; list a subset to receive less
            context (fewer tokens).
    """

    id: str
    title: str
    description: str
    agent: str
    task: str = ""
    files: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)

    @field_validator("files")
    @classmethod
    def _normalize_files(cls, value: list[str]) -> list[str]:
        """Collapse separators, reject escapes, and unique while preserving order."""
        seen: list[str] = []
        for item in value:
            path = normalize_claimed_file(item)
            if path not in seen:
                seen.append(path)
        return seen


class Plan(BaseModel):
    """A decomposed goal: ordered-ish steps plus the route used to merge them.

    Attributes:
        steps: All plan steps. Execution order is derived from ``depends_on``,
            not from list position.
        route: How the final answer is merged from step outputs. ``"answer"``
            concatenates completed outputs; reserved for future routing modes.

    Raises:
        ValueError: From :meth:`waves` when the plan contains a dependency
            cycle or references an unknown step id.
    """

    steps: list[PlanStep]
    route: str = "answer"

    def ready_steps(self, done: set[str]) -> list[PlanStep]:
        """Steps whose dependencies are all satisfied and not yet executed.

        Args:
            done: Ids of steps that have already completed.

        Returns:
            The parallel frontier: steps that may all run concurrently now.
        """
        return [s for s in self.steps if s.id not in done and set(s.depends_on) <= done]

    def remaining(self, done: set[str]) -> list[PlanStep]:
        """Steps not yet completed.

        Args:
            done: Ids of steps that have already completed.

        Returns:
            All steps whose id is not in ``done``.
        """
        return [s for s in self.steps if s.id not in done]

    def waves(self) -> list[list[PlanStep]]:
        """Static topological levels of the plan.

        Each level (wave) is a list of steps with no interdependencies; steps
        within a wave are dispatched concurrently by the LangGraph engine.

        Returns:
            One list of steps per wave, in execution order.

        Raises:
            ValueError: If a dependency cycle exists or a step references a
                step id that is never defined.
        """
        done: set[str] = set()
        levels: list[list[PlanStep]] = []
        while len(done) < len(self.steps):
            level = self.ready_steps(done)
            if not level:
                raise ValueError("plan has a dependency cycle or unknown dep")
            levels.append(level)
            done.update(s.id for s in level)
        return levels

    def assert_file_partition(self) -> None:
        """Reject overlapping write-paths and unscoped parallel Coder steps.

        Call before executing a plan so two workers cannot race on the same
        file. Topology is still :meth:`waves`; this is a write-set check.

        Raises:
            ValueError: When two steps in the same wave claim the same path, a
                claimed path is invalid, or two or more Coder steps share a
                wave without each declaring a non-empty ``files`` list.
        """
        for wave in self.waves():
            _assert_wave_files(wave)


def _assert_wave_files(wave: list[PlanStep]) -> None:
    """Check one wave's claimed files for overlap and Coder scoping.

    Args:
        wave: Mutually independent steps (one topological level).

    Raises:
        ValueError: Overlapping claims, or parallel Coder steps with no files.
    """
    claimed: dict[str, str] = {}
    for step in wave:
        for path in step.files:
            owner = claimed.get(path)
            if owner is not None:
                raise ValueError(f"parallel steps {owner} and {step.id} both claim {path}")
            claimed[path] = step.id
    coders = [step for step in wave if step.agent == CODER_AGENT]
    if len(coders) < 2:
        return
    missing = [step.id for step in coders if not step.files]
    if missing:
        raise ValueError(f"parallel Coder steps must declare disjoint files; unscoped: {missing}")


class StepOutput(BaseModel):
    """Result of executing one plan step.

    Attributes:
        step_id: Id of the plan step this output belongs to.
        agent: Name of the agent that produced the output.
        content: The worker's response text (verbatim; the orchestrator merges,
            it does not reinterpret).
        prompt_tokens: Approximate tokens sent (system contract + user prompt).
            Counted with the whitespace tokenizer; ``0`` for cache hits.
        completion_tokens: Approximate tokens received from the model.
        cached: ``True`` when the answer came from the semantic/exact cache and
            no LLM call was made (zero token cost).
        wall_s: Wall-clock seconds spent on this step.
        status: ``"ok"`` on success; reserved for failure statuses.
    """

    step_id: str
    agent: str
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached: bool = False
    wall_s: float = 0.0
    status: str = "ok"


class UsageTotals(BaseModel):
    """Aggregated cost of a whole plan run.

    Attributes:
        prompt_tokens: Sum of prompt tokens across all non-cached LLM calls.
        completion_tokens: Sum of completion tokens across non-cached calls.
        llm_calls: Number of calls that actually hit a provider.
        cached_calls: Number of steps answered from cache (free).
        wall_s: Total wall-clock seconds for the plan run.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_calls: int = 0
    cached_calls: int = 0
    wall_s: float = 0.0

    @property
    def total_tokens(self) -> int:
        """prompt + completion tokens across all non-cached calls."""
        return self.prompt_tokens + self.completion_tokens


class PlanResult(BaseModel):
    """Outcome of running a plan through the LangGraph engine.

    Attributes:
        outputs: Completed step outputs keyed by step id, in completion order.
        usage: Aggregated token/call cost of the run.
    """

    outputs: dict[str, StepOutput] = Field(default_factory=dict)
    usage: UsageTotals = Field(default_factory=UsageTotals)

    @property
    def answer(self) -> str:
        """Merged result: all successful step outputs joined by newlines.

        The orchestrator merges verbatim; no summarization happens here.
        """
        return "\n".join(o.content for o in self.outputs.values() if o.status == "ok")
