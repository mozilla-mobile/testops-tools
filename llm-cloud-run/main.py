from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI, Form, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse

from common.config import Settings
from common.logging_utils import setup_logging
from storage.bigquery_repo import BigQueryNotesRepository
from retrieval.python_cosine import PythonCosineRetriever
from services.analyze_service import analyze as analyze_service


def create_app() -> FastAPI:
    setup_logging()
    settings = Settings()

    app = FastAPI()

    # Dependencies (constructed once per process)
    repo = BigQueryNotesRepository(settings)
    retriever = PythonCosineRetriever(settings, repo)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.post("/analyze")
    async def analyze(
        prompt: str = Form(...),
        log_file: Optional[UploadFile] = File(None),
        image: Optional[UploadFile] = File(None),
    ):
        log_text = ""
        if log_file is not None:
            allowed_logs = {"text/plain", "text/x-log", "application/octet-stream"}
            if log_file.content_type not in allowed_logs:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Unsupported log file type: {log_file.content_type}. "
                        f"Allowed: {', '.join(sorted(allowed_logs))}"
                    ),
                )
            log_bytes = await log_file.read()
            try:
                log_text = log_bytes.decode(errors="ignore")
            except Exception:
                log_text = ""
            logging.getLogger(__name__).info(
                "Received log file: %s type=%s size=%d",
                log_file.filename,
                log_file.content_type,
                len(log_bytes),
            )

        image_bytes = None
        image_mime = None
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
            image_bytes = await image.read()
            image_mime = image.content_type
            logging.getLogger(__name__).info(
                "Including image: %s type=%s size=%d",
                image.filename,
                image.content_type,
                len(image_bytes),
            )

        try:
            output = analyze_service(
                settings,
                retriever=retriever,
                prompt=prompt,
                log_text=log_text,
                image_bytes=image_bytes,
                image_mime_type=image_mime,
            )
        except Exception as e:
            logging.getLogger(__name__).exception("Analyze failed")
            raise HTTPException(status_code=500, detail=str(e))

        return JSONResponse({"output": output})

    return app
