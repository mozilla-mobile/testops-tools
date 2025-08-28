from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from vertexai.preview.generative_models import GenerativeModel
import vertexai
import os

app = FastAPI()

vertexai.init(project=os.getenv("GCP_PROJECT"), location="us-central1")


class LLMRequest(BaseModel):
    prompt: str
    content: str


@app.get("/")
async def root():
    return JSONResponse(
        content={"message": "Welcome to the LLM API"},
        status_code=200
    )


@app.post("/")
async def analyze(request: LLMRequest):
    full_prompt = f"{request.prompt.strip()}\n\n{request.content.strip()}"
    model = GenerativeModel("gemini-2.5-flash-lite")
    response = model.generate_content(
        full_prompt,
        generation_config={
            "temperature": 0.3,
            "max_output_tokens": 1024
        }
    )
    return {"output": response.text}
