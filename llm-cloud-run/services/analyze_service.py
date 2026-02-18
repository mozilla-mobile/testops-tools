from __future__ import annotations

from vertexai.preview.generative_models import Part

from common.config import Settings
from llm.gemini_client import generate
from retrieval.retriever import Retriever


def build_augmented_prompt(prompt: str, *, top_notes: list[dict]) -> str:
    if not top_notes:
        return prompt

    context_lines = []
    for i, n in enumerate(top_notes, start=1):
        content = n.get("content", "")
        source = n.get("source") or "unknown"
        context_lines.append(f"[{i}] {content} (Source: {source})")

    context_block = "\n".join(context_lines)
    return (
        "You are a crash analysis assistant. Use the context below to help:\n\n"
        f"Context:\n{context_block}\n\n"
        f"User task:\n{prompt}"
    )


def analyze(
    settings: Settings,
    *,
    retriever: Retriever,
    prompt: str,
    log_text: str = "",
    image_bytes: bytes | None = None,
    image_mime_type: str | None = None,
) -> str:
    snippet_source = log_text or prompt
    snippet = snippet_source[: settings.snippet_chars]

    notes = retriever.retrieve(snippet, top_k=settings.rag_top_k)
    top_notes = [{"content": n.content, "source": n.source} for n in notes]

    augmented_prompt = build_augmented_prompt(prompt, top_notes=top_notes)

    parts: list[Part] = [Part.from_text(augmented_prompt)]

    if log_text:
        parts.append(Part.from_text("\n\nRaw crash snippet (truncated):\n" + log_text[:4000]))

    if image_bytes and image_mime_type:
        parts.append(Part.from_data(mime_type=image_mime_type, data=image_bytes))

    return generate(settings, parts if len(parts) > 1 else parts[0], temperature=0.3, max_output_tokens=1024)
