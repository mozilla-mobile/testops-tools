FROM ghcr.io/astral-sh/uv:0.10.4-python3.12-trixie
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src/ src/
RUN uv sync --frozen
CMD ["uv", "run", "python", "src/fetch_metrics.py", "--package", "org.mozilla.firefox", "--metric-set", "crashrate", "--resolve-versions", "--top", "10"]