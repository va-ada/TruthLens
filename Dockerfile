# ============================================================
# TruthLens — Dockerfile
# Single-container deployment: FastAPI + static SPA + ChromaDB + local models
# ============================================================
# - Python 3.12 slim (pinned deps need >=3.12), CPU-only PyTorch (no multi-GB CUDA wheels)
# - All three local models are downloaded at build time, so the container starts offline:
#     sentence-transformers/all-MiniLM-L6-v2   (embeddings)
#     cross-encoder/ms-marco-MiniLM-L-6-v2     (reranker)
#     cross-encoder/nli-deberta-v3-base        (offline NLI judge)
# - Runs as a non-root user; ChromaDB, SQLite and uploads persist via volumes
# ============================================================

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface

RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---------- Dependencies (cached layer) ----------
COPY requirements.txt .
RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch==$(grep -E '^torch==' requirements.txt | cut -d= -f3)" \
    && pip install -r requirements.txt

# ---------- Models (cached layer) ----------
RUN python -c "\
from sentence_transformers import SentenceTransformer; \
from sentence_transformers.cross_encoder import CrossEncoder; \
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2'); \
CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2'); \
CrossEncoder('cross-encoder/nli-deberta-v3-base')"

# ---------- Application ----------
COPY . .

# Only runtime-writable dirs are chowned (chown -R /app would duplicate the ~1 GB model layer)
RUN useradd --create-home --uid 10001 truthlens \
    && mkdir -p /app/storage /app/data/uploads /app/data/trusted_docs \
    && chown -R truthlens:truthlens /app/storage /app/data
USER truthlens
# Models are baked in; never try to reach the Hugging Face hub at runtime
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD python -c "import requests; r=requests.get('http://localhost:8000/health', timeout=5); exit(0 if r.status_code==200 else 1)" || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
