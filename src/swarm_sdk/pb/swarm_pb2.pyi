class RunRequest:
    text: str
    thread_id: str

    def __init__(self, text: str = ..., thread_id: str = ...) -> None: ...


class RunResponse:
    text: str
    cached: bool
    active_agent: str
    tokens: int
    mode: str

    def __init__(
        self,
        text: str = ...,
        cached: bool = ...,
        active_agent: str = ...,
        tokens: int = ...,
        mode: str = ...,
    ) -> None: ...


class RecallRequest:
    query: str
    top_k: int

    def __init__(self, query: str = ..., top_k: int = ...) -> None: ...


class MemoryHit:
    id: int
    text: str
    score: float

    def __init__(self, id: int = ..., text: str = ..., score: float = ...) -> None: ...


class RecallResponse:
    hits: list[MemoryHit]

    def __init__(self, hits: list[MemoryHit] | None = ...) -> None: ...
