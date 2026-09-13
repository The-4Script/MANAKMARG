# MANAK MARG — single container: FastAPI API + built React frontend + prebuilt SQLite data.
#   docker build -t manakmarg .
#   docker run -p 7860:7860 manakmarg        -> http://localhost:7860

# ---- Stage 1: build the frontend ----
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Leave empty when the API serves the frontend (default).
ARG VITE_API_BASE_URL=
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

# ---- Stage 2: Python runtime ----
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MANAKMARG_HOME=/app \
    HOST=0.0.0.0 \
    PORT=7860
WORKDIR /app

# Non-root user with uid 1000 (required by Hugging Face Spaces, harmless elsewhere).
RUN useradd --create-home --uid 1000 app

COPY backend/ backend/
RUN pip install -e backend

COPY data/ data/
COPY docs/ docs/
COPY deploy/ deploy/
COPY --from=frontend /app/frontend/dist frontend/dist

# Restore the prebuilt database and runtime index at build time so the container starts instantly.
# If the bundle is not in the build context, `start` downloads it from MANAKMARG_DATA_URL at runtime instead.
RUN if [ -f deploy/data/manakmarg-data.tar.gz ]; then python -m manakmarg import-data; fi \
    && mkdir -p data/processed data/indexes data/uploads data/manifests \
    && chown -R app:app /app

USER app
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"7860\")}/api/health', timeout=4)" || exit 1

CMD ["python", "-m", "manakmarg", "start"]
