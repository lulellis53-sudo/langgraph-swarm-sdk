from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SpawnRequest(_message.Message):
    __slots__ = ("goal", "agents")
    GOAL_FIELD_NUMBER: _ClassVar[int]
    AGENTS_FIELD_NUMBER: _ClassVar[int]
    goal: str
    agents: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, goal: _Optional[str] = ..., agents: _Optional[_Iterable[str]] = ...) -> None: ...

class PlanStepMsg(_message.Message):
    __slots__ = ("id", "title", "description", "agent", "depends_on", "inputs", "task", "files")
    ID_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    AGENT_FIELD_NUMBER: _ClassVar[int]
    DEPENDS_ON_FIELD_NUMBER: _ClassVar[int]
    INPUTS_FIELD_NUMBER: _ClassVar[int]
    TASK_FIELD_NUMBER: _ClassVar[int]
    FILES_FIELD_NUMBER: _ClassVar[int]
    id: str
    title: str
    description: str
    agent: str
    depends_on: _containers.RepeatedScalarFieldContainer[str]
    inputs: _containers.RepeatedScalarFieldContainer[str]
    task: str
    files: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, id: _Optional[str] = ..., title: _Optional[str] = ..., description: _Optional[str] = ..., agent: _Optional[str] = ..., depends_on: _Optional[_Iterable[str]] = ..., inputs: _Optional[_Iterable[str]] = ..., task: _Optional[str] = ..., files: _Optional[_Iterable[str]] = ...) -> None: ...

class PlanHandle(_message.Message):
    __slots__ = ("plan_id", "steps")
    PLAN_ID_FIELD_NUMBER: _ClassVar[int]
    STEPS_FIELD_NUMBER: _ClassVar[int]
    plan_id: str
    steps: _containers.RepeatedCompositeFieldContainer[PlanStepMsg]
    def __init__(self, plan_id: _Optional[str] = ..., steps: _Optional[_Iterable[_Union[PlanStepMsg, _Mapping]]] = ...) -> None: ...

class StepOutputMsg(_message.Message):
    __slots__ = ("step_id", "agent", "content", "prompt_tokens", "completion_tokens", "cached", "wall_s", "status")
    STEP_ID_FIELD_NUMBER: _ClassVar[int]
    AGENT_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    PROMPT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    COMPLETION_TOKENS_FIELD_NUMBER: _ClassVar[int]
    CACHED_FIELD_NUMBER: _ClassVar[int]
    WALL_S_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    step_id: str
    agent: str
    content: str
    prompt_tokens: int
    completion_tokens: int
    cached: bool
    wall_s: float
    status: str
    def __init__(self, step_id: _Optional[str] = ..., agent: _Optional[str] = ..., content: _Optional[str] = ..., prompt_tokens: _Optional[int] = ..., completion_tokens: _Optional[int] = ..., cached: _Optional[bool] = ..., wall_s: _Optional[float] = ..., status: _Optional[str] = ...) -> None: ...

class UsageMsg(_message.Message):
    __slots__ = ("prompt_tokens", "completion_tokens", "llm_calls", "cached_calls", "wall_s")
    PROMPT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    COMPLETION_TOKENS_FIELD_NUMBER: _ClassVar[int]
    LLM_CALLS_FIELD_NUMBER: _ClassVar[int]
    CACHED_CALLS_FIELD_NUMBER: _ClassVar[int]
    WALL_S_FIELD_NUMBER: _ClassVar[int]
    prompt_tokens: int
    completion_tokens: int
    llm_calls: int
    cached_calls: int
    wall_s: float
    def __init__(self, prompt_tokens: _Optional[int] = ..., completion_tokens: _Optional[int] = ..., llm_calls: _Optional[int] = ..., cached_calls: _Optional[int] = ..., wall_s: _Optional[float] = ...) -> None: ...

class PlanResultMsg(_message.Message):
    __slots__ = ("outputs", "usage", "plan_id")
    OUTPUTS_FIELD_NUMBER: _ClassVar[int]
    USAGE_FIELD_NUMBER: _ClassVar[int]
    PLAN_ID_FIELD_NUMBER: _ClassVar[int]
    outputs: _containers.RepeatedCompositeFieldContainer[StepOutputMsg]
    usage: UsageMsg
    plan_id: str
    def __init__(self, outputs: _Optional[_Iterable[_Union[StepOutputMsg, _Mapping]]] = ..., usage: _Optional[_Union[UsageMsg, _Mapping]] = ..., plan_id: _Optional[str] = ...) -> None: ...

class PlanStatusMsg(_message.Message):
    __slots__ = ("plan_id", "status", "steps_done", "steps_total")
    PLAN_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    STEPS_DONE_FIELD_NUMBER: _ClassVar[int]
    STEPS_TOTAL_FIELD_NUMBER: _ClassVar[int]
    plan_id: str
    status: str
    steps_done: int
    steps_total: int
    def __init__(self, plan_id: _Optional[str] = ..., status: _Optional[str] = ..., steps_done: _Optional[int] = ..., steps_total: _Optional[int] = ...) -> None: ...

class RunRequest(_message.Message):
    __slots__ = ("text", "thread_id")
    TEXT_FIELD_NUMBER: _ClassVar[int]
    THREAD_ID_FIELD_NUMBER: _ClassVar[int]
    text: str
    thread_id: str
    def __init__(self, text: _Optional[str] = ..., thread_id: _Optional[str] = ...) -> None: ...

class RunResponse(_message.Message):
    __slots__ = ("text", "cached", "active_agent", "tokens", "mode")
    TEXT_FIELD_NUMBER: _ClassVar[int]
    CACHED_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_AGENT_FIELD_NUMBER: _ClassVar[int]
    TOKENS_FIELD_NUMBER: _ClassVar[int]
    MODE_FIELD_NUMBER: _ClassVar[int]
    text: str
    cached: bool
    active_agent: str
    tokens: int
    mode: str
    def __init__(self, text: _Optional[str] = ..., cached: _Optional[bool] = ..., active_agent: _Optional[str] = ..., tokens: _Optional[int] = ..., mode: _Optional[str] = ...) -> None: ...

class RecallRequest(_message.Message):
    __slots__ = ("query", "top_k")
    QUERY_FIELD_NUMBER: _ClassVar[int]
    TOP_K_FIELD_NUMBER: _ClassVar[int]
    query: str
    top_k: int
    def __init__(self, query: _Optional[str] = ..., top_k: _Optional[int] = ...) -> None: ...

class MemoryHit(_message.Message):
    __slots__ = ("id", "text", "score")
    ID_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    SCORE_FIELD_NUMBER: _ClassVar[int]
    id: int
    text: str
    score: float
    def __init__(self, id: _Optional[int] = ..., text: _Optional[str] = ..., score: _Optional[float] = ...) -> None: ...

class RecallResponse(_message.Message):
    __slots__ = ("hits",)
    HITS_FIELD_NUMBER: _ClassVar[int]
    hits: _containers.RepeatedCompositeFieldContainer[MemoryHit]
    def __init__(self, hits: _Optional[_Iterable[_Union[MemoryHit, _Mapping]]] = ...) -> None: ...
