from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any


app = FastAPI()


class Payload(BaseModel):
    input: Any

def process(x):
    # call Vertex AI from here
    return {"result": f"processed: {x}"}

@app.post("/process")
async def process_endpoint(p: Payload):
    return process(p.input)
