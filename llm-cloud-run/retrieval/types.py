from __future__ import annotations
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Note:
    note_id: str
    content: str
    source: str | None = None
    created_at: str | None = None
    embedding: List[float] | None = None
