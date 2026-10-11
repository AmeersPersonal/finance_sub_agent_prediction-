# The backend's HTTP API image. Build context: backend/ (see .dockerignore).
#
#   docker build -t finance-backend .                 # from backend/
#   docker compose up --build                         # PostgreSQL + migrations + API (docker-compose.yml)
#
# It installs src/requirements-api.lock only: serving forecasts doesn't need the
# ml/ training stack (torch, scikit-learn, LightGBM), which would add gigabytes.
# Secrets come from the environment at run time; none are baked in, and neither
# are tests or private documents (src/ai/docs/).
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY src/requirements-api.lock /tmp/requirements-api.lock
RUN pip install --require-hashes -r /tmp/requirements-api.lock && rm /tmp/requirements-api.lock

WORKDIR /app/src
COPY src/ ./
# data/ (the BLS cache, models) is the only place the app writes; run as a non-root user.
RUN useradd --create-home --uid 10001 app && mkdir -p /app/data && chown app /app/data
USER app

EXPOSE 8000
# /health also checks the database connection.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]
# One worker: rate limits, prediction jobs and the score cache are in-process (api/state.py).
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
