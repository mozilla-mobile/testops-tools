from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from retrieval.types import Note


class Retriever(ABC):
    @abstractmethod
    def retrieve(self, snippet: str, *, top_k: int) -> List[Note]:
        raise NotImplementedError
