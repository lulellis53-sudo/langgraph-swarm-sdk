from typing import Protocol

import numpy as np
from pydantic import BaseModel


class MemoryHit(BaseModel):
    id: int
    text: str
    score: float


class MemoryStore(Protocol):
    def add(self, text: str, vector: np.ndarray) -> int: ...

    def search(self, vector: np.ndarray, k: int) -> list[MemoryHit]: ...
