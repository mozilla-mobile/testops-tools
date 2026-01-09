import logging
import math
import os
import json

from fastapi import FastAPI, Form, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional

import vertexai
from vertexai.preview.generative_models import GenerativeModel, Part
from vertexai.language_models import TextEmbeddingModel

logging.basicConfig(level=logging.INFO)

app = FastAPI()

# ---- Vertex AI init ----
GCP_PROJECT = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
if not GCP_PROJECT:
    logging.warning("GCP_PROJECT / GOOGLE_CLOUD_PROJECT not set; vertexai.init may fail.")
vertexai.init(project=GCP_PROJECT, location="us-central1")

# ---- RAG: notes.json + embeddings ----

NOTES = []          # list of note dicts
NOTE_VECTORS = []   # list of embedding vectors (lists of floats)
EMBED_MODEL: Optional[TextEmbeddingModel] = None


def embed_text(text: str):
    """Return embedding vector for given text using Vertex embedding model."""
    global EMBED_MODEL
    if EMBED_MODEL is None:
        EMBED_MODEL = TextEmbeddingModel.from_pretrained("text-embedding-004")
    return EMBED_MODEL.get_embeddings([text])[0].values


def cosine(a, b):
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def load_notes():
    """Load notes.json and precompute embeddings for each note.content."""
    global NOTES, NOTE_VECTORS
    notes_path = os.path.join(os.path.dirname(__file__), "notes.json")
    if not os.path.exists(notes_path):
        logging.warning("notes.json not found; RAG will be disabled.")
        NOTES = []
        NOTE_VECTORS = []
        return

    try:
        with open(notes_path, "r", encoding="utf-8") as f:
            NOTES = json.load(f)
        if not isinstance(NOTES, list):
            raise ValueError("notes.json must be a list of note objects")
    except Exception as e:
        logging.error(f"Failed to load notes.json: {e}")
        NOTES = []
        NOTE_VECTORS = []
        return

    NOTE_VECTORS = []
    for note in NOTES:
        content = note.get("content", "")
        if not content:
            NOTE_VECTORS.append([])
            continue
        vec = embed_text(content)
        NOTE_VECTORS.append(vec)

    logging.info(f"Loaded {len(NOTES)} notes for RAG.")


def retrieve_top_notes(snippet: str, top_k: int = 3):
    """Return top_k most similar notes for given log snippet."""
    if not NOTES or not NOTE_VECTORS:
        return []

    qvec = embed_text(snippet)
    scored = []
    for note, vec in zip(NOTES, NOTE_VECTORS):
        if not vec:
            continue
        score = cosine(qvec, vec)
        scored.append((score, note))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [note for score, note in scored[:top_k]]
    return top


# load notes when the module is imported
load_notes()

# ---- FastAPI endpoint ----


@app.post("/analyze")
async def analyze(
    prompt: str = Form(...),
    log_file: Optional[UploadFile] = File(None),
    image: Optional[UploadFile] = File(None),
):
    """
    Main endpoint:
    - prompt: user instruction (required)
    - log_file: optional text log file (e.g., crash stack)
    - image: optional image (e.g., screenshot)
    """

    parts = []

    # --- Handle log file (if provided) ---
    log_text = ""
    if log_file is not None:
        # You can adjust allowed types as needed
        allowed_logs = {"text/plain", "text/x-log", "application/octet-stream"}
        if log_file.content_type not in allowed_logs:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported log file type: {log_file.content_type}. "
                       f"Allowed: {', '.join(sorted(allowed_logs))}",
            )
        log_bytes = await log_file.read()
        try:
            log_text = log_bytes.decode(errors="ignore")
        except Exception:
            log_text = ""
        logging.info(
            f"Received log file: {log_file.filename}, "
            f"type: {log_file.content_type}, size: {len(log_bytes)} bytes"
        )

    # --- RAG: retrieve notes based on a snippet of the log (or prompt fallback) ---
    snippet_source = log_text or prompt
    snippet = snippet_source[:800]  # small snippet for similarity search

    top_notes = retrieve_top_notes(snippet, top_k=3)
    if top_notes:
        context_lines = []
        for i, n in enumerate(top_notes, start=1):
            context_lines.append(
                f"[{i}] {n.get('content', '')} "
                f"(Source: {n.get('source', 'unknown')})"
            )
        context_block = "\n".join(context_lines)
        augmented_prompt = (
            "You are a crash analysis assistant. Use the context below to help:\n\n"
            f"Context:\n{context_block}\n\n"
            f"User task:\n{prompt}"
        )
    else:
        augmented_prompt = prompt

    # --- Build text part(s) for Gemini ---
    # main text (augmented prompt)
    parts.append(Part.from_text(augmented_prompt))

    # optionally include a raw snippet of the log as extra text
    if log_text:
        parts.append(
            Part.from_text(
                "\n\nRaw crash snippet (truncated):\n" + log_text[:4000]
            )
        )

    # --- Handle image (if provided) ---
    if image is not None:
        allowed_images = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
        if image.content_type not in allowed_images:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unsupported image type: {image.content_type}. "
                    f"Allowed: {', '.join(sorted(allowed_images))}"
                ),
            )
        img_bytes = await image.read()
        parts.append(
            Part.from_data(mime_type=image.content_type, data=img_bytes)
        )
        logging.info(
            f"Including image in prompt: {image.filename}, "
            f"type: {image.content_type}, size: {len(img_bytes)} bytes"
        )

    # --- Call Gemini ---
    model = GenerativeModel("gemini-2.5-flash-lite")
    try:
        response = model.generate_content(
            parts if len(parts) > 1 else parts[0],
            generation_config={
                "temperature": 0.3,
                "max_output_tokens": 1024,
            },
        )
        output_text = response.text
    except Exception as e:
        logging.exception("Error calling Gemini model")
        raise HTTPException(status_code=500, detail=str(e))

    return JSONResponse({"output": output_text})
