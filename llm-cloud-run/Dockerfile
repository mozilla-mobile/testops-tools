FROM python:3.10-slim

WORKDIR /app

RUN pip install fastapi uvicorn google-cloud-aiplatform vertexai

COPY main.py .

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]