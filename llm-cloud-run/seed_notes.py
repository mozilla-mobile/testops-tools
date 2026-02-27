#!/usr/bin/env python3
"""Seed BigQuery tables from notes.json.

Reads each note, generates an embedding via Vertex AI, and inserts both
the note and its embedding into the configured BigQuery tables.
Skips notes that already exist (idempotent).

Usage (requires GCP credentials via ADC or service account):

    # Uses defaults from Settings / environment
    python seed_notes.py

    # Point at a different JSON file
    python seed_notes.py --notes-file path/to/notes.json

    # Dry-run: log what would be inserted without touching BigQuery
    python seed_notes.py --dry-run

Environment variables honoured (see common/config.py):
    GCP_PROJECT, GCP_LOCATION, BQ_PROJECT, BQ_DATASET,
    BQ_NOTES_TABLE, BQ_EMBEDDINGS_TABLE, EMBEDDING_MODEL, ...
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# ── project imports (same packages the Cloud Run service uses) ──────
from common.config import Settings
from common.logging_utils import setup_logging
from llm.embeddings import embed_text
from storage.bigquery_repo import BigQueryNotesRepository

logger = logging.getLogger(__name__)

DEFAULT_NOTES_FILE = Path(__file__).parent / "notes.json"


def load_notes(path: Path) -> list[dict]:
    """Return the list of note dicts from a JSON file."""
    with open(path) as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON array in {path}, got {type(data).__name__}")
    return data


def seed(
    settings: Settings,
    repo: BigQueryNotesRepository,
    notes: list[dict],
    *,
    dry_run: bool = False,
) -> None:
    total = len(notes)
    skipped = 0
    inserted = 0
    logger.info("Seeding %d note(s) (dry_run=%s)", total, dry_run)

    for idx, note in enumerate(notes, start=1):
        note_id = note["id"]
        content = note["content"]
        source = note.get("source")
        signature = note.get("signature")
        match_regex = note.get("match_regex")

        logger.info("[%d/%d] Processing note %s …", idx, total, note_id)

        # ── idempotency check ───────────────────────────────────────
        if not dry_run and repo.note_exists(note_id):
            logger.info("  Note %s already exists, skipping.", note_id)
            skipped += 1
            continue

        # ── generate embedding ──────────────────────────────────────
        logger.info("  Generating embedding (%s) …", settings.embedding_model)
        if dry_run:
            embedding = []
        else:
            embedding = embed_text(settings, content)
        logger.info("  Embedding dimension: %d", len(embedding))

        # ── insert into BigQuery ────────────────────────────────────
        if dry_run:
            logger.info("  [DRY-RUN] Would insert note and embedding for %s", note_id)
            continue

        repo.insert_note(
            note_id=note_id,
            content=content,
            source=source,
            signature=signature,
            match_regex=match_regex,
        )
        logger.info("  Inserted note %s", note_id)

        repo.insert_embedding(note_id=note_id, embedding=embedding)
        logger.info("  Inserted embedding for %s", note_id)

        inserted += 1

        # Be polite to the Vertex AI quota (embedding API).
        if idx < total:
            time.sleep(0.25)

    logger.info("Done – %d inserted, %d skipped, %d total.", inserted, skipped, total)


def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser(description="Seed BigQuery notes from JSON")
    parser.add_argument(
        "--notes-file",
        type=Path,
        default=DEFAULT_NOTES_FILE,
        help=f"Path to the notes JSON file (default: {DEFAULT_NOTES_FILE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log actions without writing to BigQuery",
    )
    args = parser.parse_args()

    if not args.notes_file.exists():
        logger.error("Notes file not found: %s", args.notes_file)
        sys.exit(1)

    notes = load_notes(args.notes_file)
    if not notes:
        logger.warning("Notes file is empty, nothing to do.")
        return

    settings = Settings()
    logger.info(
        "BigQuery target: %s.%s  (notes=%s, embeddings=%s)",
        settings.effective_bq_project,
        settings.bq_dataset,
        settings.bq_notes_table,
        settings.bq_embeddings_table,
    )

    repo = BigQueryNotesRepository(settings)
    seed(settings, repo, notes, dry_run=args.dry_run)


if __name__ == "__main__":
    main()