from fastapi import FastAPI, Form, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
from vertexai.preview.generative_models import GenerativeModel, Part
import logging
import os
import vertexai

logging.basicConfig(level=logging.INFO)

app = FastAPI()

vertexai.init(project=os.getenv("GCP_PROJECT"), location="us-central1")


class LLMRequest(BaseModel):
    prompt: str
    content: str


@app.get("/")
async def root():
    return JSONResponse(content={"message": "Welcome to the LLM API"}, status_code=200)


@app.post("/")  # JSON-only
async def analyze_json(request: LLMRequest):
    full_prompt = f"{request.prompt.strip()}\n\n{request.content.strip()}"
    model = GenerativeModel("gemini-2.5-flash-lite")
    response = model.generate_content(
        full_prompt,
        generation_config={"temperature": 0.3, "max_output_tokens": 1024},
    )
    return {"output": response.text}


@app.post("/analyze")  # accepts multipart/form-data
async def analyze_multipart(
    prompt: str = Form(...),
    content: str = Form(""),
    image: Optional[UploadFile] = File(None),
):
    """
    Accepts:
      - prompt (form field)
      - content (form field)
      - image (file, optional) – PNG/JPEG/WEBP
    """

    # Build the prompt parts for Gemini
    parts = [Part.from_text(prompt.strip()), Part.from_text(content.strip())]

    if image:
        # Basic content-type guard
        allowed = {"image/png", "image/jpeg", "image/webp"}
        if image.content_type not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported image type: {image.content_type}. Allowed: {', '.join(allowed)}",
            )
        img_bytes = await image.read()
        parts.append(Part.from_data(mime_type=image.content_type, data=img_bytes))
        logging.info(f"Including image in prompt: {image.filename}, type: {image.content_type}, size: {len(img_bytes)} bytes")

    model = GenerativeModel("gemini-2.5-flash-lite")
    response = model.generate_content(
        parts if len(parts) > 1 else parts[0],
        generation_config={"temperature": 0.3, "max_output_tokens": 1024},
    )
    return {"output": response.text}
