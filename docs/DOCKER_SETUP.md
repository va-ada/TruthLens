# TruthLens — Docker Setup

One container runs everything:
- the FastAPI API and the single-page UI (`index.html`)
- ChromaDB and SQLite
- three local models baked into the image: the MiniLM embedder, the MS-MARCO reranker and the DeBERTa-v3 NLI judge

PyTorch is the CPU build. The app runs as a non-root user, and the image is about 4 GB, mostly PyTorch and the models.

## Quick start

```bash
cp .env.example .env          # then edit: GEMINI_API_KEY (optional), ADMIN_TOKEN, TRUTHLENS_PORT
docker compose up --build -d  # first build: ~10 min (downloads ~1.5 GB of wheels + ~0.9 GB of models)
open http://127.0.0.1:${TRUTHLENS_PORT:-8000}
```

The port is bound to **127.0.0.1 only**. Set `TRUTHLENS_PORT` in `.env` if 8000 is taken on the host.

## Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` / `GROQ_API_KEY` / `OPENAI_API_KEY` | Optional cloud judge. Without a key the offline DeBERTa NLI judge is used |
| `GEMINI_MODEL`, `GEMINI_FALLBACK_MODELS` | Model names; Google retires models, so these are configurable |
| `ADMIN_TOKEN` | Required `X-Admin-Token` for upload / delete / seed / news-sync. **Set it for anything beyond local use** |
| `ALLOWED_ORIGINS` | Comma-separated origins allowed to call the API cross-origin (the bundled UI needs none) |
| `TRUTHLENS_PORT` | Host port for compose |

`GET /health` reports which judge is active (`"judge": "Google Gemini (...)"` or `"Offline NLI ..."`).

## Data

All runtime data (ChromaDB, SQLite history, uploads) lives in **one named volume**, `truthlens-storage`,
mounted at `/app/storage` (via `TRUTHLENS_DATA_DIR`). No volume is mounted over code directories, so rebuilding
the image always ships the new code.

| Action | Command |
|---|---|
| Logs | `docker compose logs -f` |
| Stop | `docker compose down` |
| Reset all data | `docker compose down -v` (deletes the volume) |
| Rebuild from scratch | `docker compose build --no-cache` |

## Troubleshooting

- **Port already in use**: set `TRUTHLENS_PORT=8090` (or any free port) in `.env`.
- **Cloud judge not used**: check `/health`. Then check `docker compose logs` for `Gemini returned HTTP 4xx/5xx`.
  A 503 or 429 falls back to other models and then to offline, and each verdict lists that under limitations.
- **First request slow**: it shouldn't be, because models load at startup (`Models ready` in the logs).

## Vercel

The Vercel path (`vercel.json`, `api/index.py`) is **not supported** in this version. The offline judge needs
PyTorch, which exceeds Vercel's function size limit, and Vercel would serve the repository files statically.
Use Docker.
