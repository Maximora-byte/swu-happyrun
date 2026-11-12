# Build from the repository root: docker build -f deploy/Dockerfile .
FROM ghcr.io/astral-sh/uv:0.12.19 AS uv
FROM python:3.11-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --extra server --no-dev --no-editable \
    && mkdir /data \
    && chown 10001:10001 /data
ENV PATH="/app/.venv/bin:$PATH"
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=6s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/v1/ready', timeout=5)" || exit 1
CMD ["python", "-m", "swu_happyrun", "server", "--database", "/data/happyrun.sqlite3", "--host", "0.0.0.0", "--port", "8080"]
