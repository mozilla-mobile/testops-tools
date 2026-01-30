import os
from dataclasses import dataclass


def _env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    return v


@dataclass(frozen=True)
class Settings:
    # GCP / Vertex
    gcp_project: str | None = _env("GCP_PROJECT") or _env("GOOGLE_CLOUD_PROJECT")
    gcp_location: str = _env("GCP_LOCATION", "us-central1") or "us-central1"

    # BigQuery
    bq_project: str | None = _env("BQ_PROJECT")  # optional; defaults to gcp_project
    bq_dataset: str = _env("BQ_DATASET", "vertex_rag_demo") or "vertex_rag_demo"
    bq_notes_table: str = _env("BQ_NOTES_TABLE", "demo_Notes") or "demo_Notes"
    bq_embeddings_table: str = _env("BQ_EMBEDDINGS_TABLE", "demo_NoteEmbeddings") or "demo_NoteEmbeddings"

    # Column names (override if your schema differs)
    notes_id_col: str = _env("NOTES_ID_COL", "note_id") or "note_id"
    notes_content_col: str = _env("NOTES_CONTENT_COL", "content") or "content"
    notes_source_col: str = _env("NOTES_SOURCE_COL", "source") or "source"
    notes_created_col: str = _env("NOTES_CREATED_COL", "created_at") or "created_at"

    emb_id_col: str = _env("EMB_ID_COL", "note_id") or "note_id"
    emb_vector_col: str = _env("EMB_VECTOR_COL", "embedding") or "embedding"  # ARRAY<FLOAT64>
    emb_model_col: str = _env("EMB_MODEL_COL", "model") or "model"
    emb_updated_col: str = _env("EMB_UPDATED_COL", "updated_at") or "updated_at"

    # RAG settings
    rag_top_k: int = int(_env("RAG_TOP_K", "3") or "3")
    snippet_chars: int = int(_env("RAG_SNIPPET_CHARS", "800") or "800")

    # LLM + Embeddings
    gemini_model: str = _env("GEMINI_MODEL", "gemini-2.5-flash-lite") or "gemini-2.5-flash-lite"
    embedding_model: str = _env("EMBEDDING_MODEL", "text-embedding-004") or "text-embedding-004"

    # Optional: cap how many notes to load into memory cache
    bq_max_notes: int = int(_env("BQ_MAX_NOTES", "5000") or "5000")

    @property
    def effective_bq_project(self) -> str | None:
        return self.bq_project or self.gcp_project

    def require_project(self) -> str:
        if not self.gcp_project:
            raise RuntimeError("GCP_PROJECT / GOOGLE_CLOUD_PROJECT not set.")
        return self.gcp_project
