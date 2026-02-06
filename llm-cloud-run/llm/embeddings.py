from __future__ import annotations

from typing import List
from vertexai.language_models import TextEmbeddingModel

from common.config import Settings
from llm.vertex_init import init_vertex

_MODEL: TextEmbeddingModel | None = None


def embed_text(settings: Settings, text: str) -> List[float]:
    """Return an embedding vector for given text using Vertex Embeddings."""
    global _MODEL
    init_vertex(settings)
    if _MODEL is None:
        _MODEL = TextEmbeddingModel.from_pretrained(settings.embedding_model)
    return _MODEL.get_embeddings([text])[0].values
