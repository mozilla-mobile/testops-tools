from __future__ import annotations

import logging
from typing import List

from google import genai
from google.genai.types import EmbedContentConfig

from common.config import Settings

_CLIENT: genai.Client | None = None
_log = logging.getLogger(__name__)


def _get_client(settings: Settings) -> genai.Client:
    """Return a module-level genai Client, creating it once."""
    global _CLIENT
    if _CLIENT is None:
        project = settings.require_project()
        _CLIENT = genai.Client(
            vertexai=True,
            project=project,
            location=settings.gcp_location,
        )
        _log.info(
            "genai Client initialized (project=%s, location=%s).",
            project,
            settings.gcp_location,
        )
    return _CLIENT


def embed_text(settings: Settings, text: str) -> List[float]:
    """Return an embedding vector for given text using Vertex Embeddings."""
    client = _get_client(settings)
    response = client.models.embed_content(
        model=settings.embedding_model,
        contents=text,
        config=EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
    )
    return list(response.embeddings[0].values)
