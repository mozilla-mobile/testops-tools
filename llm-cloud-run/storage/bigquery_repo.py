from __future__ import annotations

from typing import List
from google.cloud import bigquery

from common.config import Settings
from retrieval.types import Note


class BigQueryNotesRepository:
    def __init__(self, settings: Settings):
        self.settings = settings
        project = settings.effective_bq_project
        self.client = bigquery.Client(project=project)  # ADC / service account on Cloud Run

    def _table(self, table_name: str) -> str:
        project = self.settings.effective_bq_project
        return f"{project}.{self.settings.bq_dataset}.{table_name}"

    def fetch_notes_with_embeddings(self, *, limit: int = 5000) -> List[Note]:
        s = self.settings
        notes_t = self._table(s.bq_notes_table)
        emb_t = self._table(s.bq_embeddings_table)

        query = f"""
        SELECT
          n.{s.notes_id_col} AS note_id,
          n.{s.notes_content_col} AS content,
          n.{s.notes_source_col} AS source,
          CAST(n.{s.notes_created_col} AS STRING) AS created_at,
          e.{s.emb_vector_col} AS embedding
        FROM `{notes_t}` n
        LEFT JOIN `{emb_t}` e
          ON n.{s.notes_id_col} = e.{s.emb_id_col}
        WHERE n.{s.notes_content_col} IS NOT NULL
        ORDER BY n.{s.notes_created_col} DESC
        LIMIT @limit
        """

        job = self.client.query(
            query,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("limit", "INT64", int(limit))]
            ),
        )
        rows = list(job.result())

        notes: List[Note] = []
        for r in rows:
            emb = r.get("embedding")
            notes.append(
                Note(
                    note_id=str(r.get("note_id", "")),
                    content=r.get("content") or "",
                    source=r.get("source"),
                    created_at=r.get("created_at"),
                    embedding=list(emb) if emb is not None else None,
                )
            )
        return notes

    def insert_note(self, *, note_id: str, content: str, source: str | None = None) -> None:
        s = self.settings
        table_id = self._table(s.bq_notes_table)

        row = {
            s.notes_id_col: note_id,
            s.notes_content_col: content,
            s.notes_source_col: source,
        }
        errors = self.client.insert_rows_json(table_id, [row])
        if errors:
            raise RuntimeError(f"BigQuery insert_note errors: {errors}")

    def insert_embedding(self, *, note_id: str, embedding: list[float], model: str | None = None) -> None:
        s = self.settings
        table_id = self._table(s.bq_embeddings_table)

        row = {
            s.emb_id_col: note_id,
            s.emb_vector_col: embedding,  # must be ARRAY<FLOAT64>
            s.emb_model_col: model or s.embedding_model,
        }
        errors = self.client.insert_rows_json(table_id, [row])
        if errors:
            raise RuntimeError(f"BigQuery insert_embedding errors: {errors}")
