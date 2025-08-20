FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
ENV PORT=8080
# Default to API; override CMD for Jobs in the deploy step
CMD ["python", "serve.py"]
