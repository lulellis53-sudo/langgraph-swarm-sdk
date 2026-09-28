"""Plan models for the orchestration engine: steps, waves, results."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    id: str
    title: str
    description: str
    agent: str
    depends_on: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    steps: list[PlanStep]
    route: str = "answer"

    def ready_steps(self, done: set[str]) -> list[PlanStep]:
        """Steps whose dependencies are all satisfied and not yet done."""
        return [s for s in self.steps if s.id not in done and set(s.depends_on) <= done]

    def remaining(self, done: set[str]) -> list[PlanStep]:
        return [s for s in self.steps if s.id not in done]

    def waves(self) -> list[list[PlanStep]]:
        """Static topological levels: steps in the same wave run in parallel."""
        done: set[str] = set()
        levels: list[list[PlanStep]] = []
        while len(done) < len(self.steps):
            level = self.ready_steps(done)
            if not level:
                raise ValueError("plan has a dependency cycle or unknown dep")
            levels.append(level)
            done.update(s.id for s in level)
        return levels


class StepOutput(BaseModel):
    step_id: str
    agent: str
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached: bool = False
    wall_s: float = 0.0
    status: str = "ok"


class UsageTotals(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_calls: int = 0
    cached_calls: int = 0
    wall_s: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class PlanResult(BaseModel):
    outputs: dict[str, StepOutput] = Field(default_factory=dict)
    usage: UsageTotals = Field(default_factory=UsageTotals)

    @property
    def answer(self) -> str:
        """Merged result: completed step outputs joined in plan order is unknown here,
        so join in insertion order."""
        return "\n".join(o.content for o in self.outputs.values() if o.status == "ok")
