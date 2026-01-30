from __future__ import annotations

import logging
from typing import List

from common.config import Settings
from llm.embeddings import embed_text
from retrieval.retriever import Retriever
from retrieval.types import Note
from retrieval.utils import cosine
from storage.bigquery_repo import BigQueryNotesRepository


class PythonCosineRetriever(Retriever):
    """
    Bridge retriever:
    - Notes + embeddings are stored in BigQuery
    - Similarity is computed in Python (swap later for vector-native search)
    """

    def __init__(self, settings: Settings, repo: BigQueryNotesRepository):
        self.settings = settings
        self.repo = repo
        self._cache: list[Note] | None = None

    def _load_notes_once(self) -> list[Note]:
        if self._cache is not None:
            return self._cache
        notes = self.repo.fetch_notes_with_embeddings(limit=self.settings.bq_max_notes)
        self._cache = notes
        logging.getLogger(__name__).info("Loaded %d notes (with embeddings) from BigQuery.", len(notes))
        return notes

    def retrieve(self, snippet: str, *, top_k: int) -> List[Note]:
        notes = self._load_notes_once()
        if not notes:
            return []

        qvec = embed_text(self.settings, snippet)

        scored: list[tuple[float, Note]] = []
        for n in notes:
            if not n.embedding:
                continue
            scored.append((cosine(qvec, n.embedding), n))

        scored.sort(key=lambda t: t[0], reverse=True)
        return [n for _, n in scored[:top_k]]