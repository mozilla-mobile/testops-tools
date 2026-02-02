from __future__ import annotations

from vertexai.preview.generative_models import GenerativeModel, Part

from common.config import Settings
from llm.vertex_init import init_vertex


def generate(
    settings: Settings,
    parts: list[Part] | Part,
    *,
    temperature: float = 0.3,
    max_output_tokens: int = 1024,
) -> str:
    """
    Generate text using a Gemini model on Vertex AI.

    `parts` can be:
      - a single Part (text or image)
      - a list of Parts (multimodal prompt)
    """
    init_vertex(settings)

    model = GenerativeModel(settings.gemini_model)

    response = model.generate_content(
        parts,
        generation_config={
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        },
    )

    # Vertex responses expose `.text` for convenience
    return getattr(response, "text", "") or ""
