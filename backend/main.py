import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware

from backend.api.routes import router as api_router, seed_trusted_knowledge_base, llm_budget_status
from backend import config as app_config
from backend.rate_limit import RateLimited
from backend.services.retrieval_service import retrieval_service
from backend.services.news_sync_service import news_sync_service
from backend.database.db import init_db, purge_old_records
from backend.config import (
    IS_VERCEL, ALLOWED_ORIGINS, ADMIN_TOKEN, DEFAULT_LLM_PROVIDER, IS_PRODUCTION,
    GEMINI_API_KEY, GEMINI_MODEL, GROQ_API_KEY, GROQ_MODEL, OPENAI_API_KEY, OPENAI_MODEL
)

ROOT_DIR = Path(__file__).resolve().parent.parent
logger = logging.getLogger("truthlens")

# DEPLOYMENT NOTE: run exactly ONE uvicorn worker per container. The rate limiter, verdict cache and the
# torch model lock are in-process state; several workers would each keep their own copy (limits would
# multiply, the cache would fragment, and each worker would load ~1 GB of models). Scale horizontally
# with more containers behind the proxy, and move rate limits / cache to a shared store (e.g. Redis)
# if that is ever needed.

# The ONLY files served from disk besides index.html. The old catch-all served any file under the
# project root, which exposed .env (API keys), the SQLite history database and all source code.
PUBLIC_FILES = {
    "favicon.ico": "image/x-icon",
    "favicon.svg": "image/svg+xml",
    "favicon.png": "image/png",
    "apple-touch-icon.png": "image/png",
}
API_PREFIXES = ("api/", "docs", "redoc", "openapi.json", "health", "static/")


def assert_production_ready() -> None:
    """APP_ENV=production refuses to start without a real admin token (admin endpoints would be open)."""
    if app_config.IS_PRODUCTION and len(app_config.ADMIN_TOKEN or "") < 16:
        raise RuntimeError(
            "APP_ENV=production requires ADMIN_TOKEN of at least 16 characters "
            "(generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\")."
        )


def run_retention() -> None:
    try:
        purged = purge_old_records(app_config.HISTORY_RETENTION_DAYS, app_config.FEEDBACK_RETENTION_DAYS)
        if purged["history"] or purged["feedback"]:
            print(f"[TruthLens] Retention purge: {purged}")
    except Exception as e:
        print(f"[TruthLens] Retention purge failed: {e}")


async def retention_scheduler() -> None:
    """Purges expired history/feedback once a day."""
    while True:
        await asyncio.sleep(24 * 3600)
        await asyncio.get_event_loop().run_in_executor(None, run_retention)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes SQLite, auto-seeds dossiers, warms up models, and runs the daily news scheduler."""
    assert_production_ready()
    if not ADMIN_TOKEN:
        print("[TruthLens] ADMIN_TOKEN is not set: upload/delete/seed/sync endpoints are unprotected (fine for local dev only).")

    try:
        init_db()
    except Exception as e:
        print(f"[TruthLens] DB init notice: {e}")
    run_retention()
    retention_task = asyncio.create_task(retention_scheduler())

    try:
        # If vector database is empty, automatically seed initial trusted documents
        if retrieval_service.count() == 0:
            print("[TruthLens] Knowledge base is empty on boot. Seeding initial trusted reference dossiers...")
            seed_trusted_knowledge_base()
            print(f"[TruthLens] Initial seed complete. Chunks indexed: {retrieval_service.count()}")
    except Exception as e:
        print(f"[TruthLens] Notice on startup seeding: {e}")

    scheduler = None
    if not IS_VERCEL:
        # Load local models once, before serving, instead of racing to load them on the first request
        try:
            from backend.services.embedding_service import embedding_service
            from backend.services.rag.local_reranker import local_reranker
            from backend.services.nlp.nli_evaluator import nli_evaluator
            embedding_service._load_model()
            local_reranker._load_model()
            print(f"[TruthLens] Models ready. Offline NLI judge available: {nli_evaluator.available()}")
        except Exception as e:
            print(f"[TruthLens] Model warm-up notice: {e}")

        scheduler = asyncio.create_task(news_sync_service.start_daily_scheduler())
        print("[TruthLens] Daily live news automated scheduler task launched.")

    yield

    retention_task.cancel()
    if scheduler:
        news_sync_service.is_running = False
        scheduler.cancel()


app = FastAPI(
    title="TruthLens: Explainable RAG Fact Verification Engine",
    description="Automated evidence-based fact verification with semantic retrieval, reranking, and explainable AI verdicts.",
    version="2.1.0",
    lifespan=lifespan,
    # Interactive API docs are a development aid; hidden in production
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)


# ---------------------------------------------------------------- consistent error shape: {"detail": str}

@app.exception_handler(RateLimited)
async def rate_limited_handler(request: Request, exc: RateLimited):
    return JSONResponse(
        status_code=429,
        content={"detail": f"Too many requests. Try again in {exc.retry_after} seconds.", "retry_after": exc.retry_after},
        headers={"Retry-After": str(exc.retry_after)},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return JSONResponse(status_code=exc.status_code, content={"detail": detail}, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """422 with one readable sentence instead of pydantic's error list."""
    errors = exc.errors()
    if errors:
        first = errors[0]
        msg = str(first.get("msg", "Invalid request.")).removeprefix("Value error, ")
        field = ".".join(str(x) for x in first.get("loc", []) if x not in ("body", "query", "path", "header"))
        detail = f"{field}: {msg}" if field and field not in msg else msg
    else:
        detail = "Invalid request."
    return JSONResponse(status_code=422, content={"detail": detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Full traceback goes to the server log only; clients never see exception text
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    # 500s are produced outside the middleware stack, so add the security headers here too
    return apply_security_headers(JSONResponse(status_code=500, content={"detail": "Internal server error"}), request.url.path)


# ---------------------------------------------------------------- security headers

def apply_security_headers(response, path: str):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    # Swagger/ReDoc pages load their own CDN assets; they only exist outside production
    if not path.startswith(("/docs", "/redoc")):
        response.headers.setdefault("Content-Security-Policy", app_config.CSP)
    return response


@app.middleware("http")
async def security_headers(request: Request, call_next):
    return apply_security_headers(await call_next(request), request.url.path)

# Compress text responses (the built app.js is ~1 MB raw, ~280 KB gzipped) when no proxy does it
app.add_middleware(GZipMiddleware, minimum_size=1024)

# CORS only for explicitly configured origins (the bundled UI is same-origin)
if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "X-Admin-Token", "X-Client-Id"],
    )

app.include_router(api_router)

# Built frontend assets (compiled JS/CSS, vendored libraries). Only this directory is served wholesale.
STATIC_DIR = ROOT_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def configured_judge() -> str:
    """Which judge /api/verify will try first, so the UI can say what actually runs."""
    provider = (DEFAULT_LLM_PROVIDER or "auto").lower()
    if provider in ("auto", "gemini") and GEMINI_API_KEY:
        return f"Google Gemini ({GEMINI_MODEL})"
    if provider in ("auto", "groq") and GROQ_API_KEY:
        return f"Groq ({GROQ_MODEL})"
    if provider in ("auto", "openai") and OPENAI_API_KEY:
        return f"OpenAI ({OPENAI_MODEL})"
    return "Offline NLI (DeBERTa-v3 cross-encoder)"


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "TruthLens Fact Verification Engine",
        "indexed_chunks": retrieval_service.count(),
        "judge": configured_judge(),
        "llm_budget": llm_budget_status()
    }


@app.get("/", include_in_schema=False)
async def serve_index():
    return FileResponse(str(ROOT_DIR / "index.html"), media_type="text/html")


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa(full_path: str):
    if full_path.startswith(API_PREFIXES):
        raise HTTPException(status_code=404, detail=f"API endpoint '/{full_path}' not found")
    if full_path in PUBLIC_FILES:
        return FileResponse(str(ROOT_DIR / full_path), media_type=PUBLIC_FILES[full_path])
    # Any other path is a client-side route: return the app shell, never a file from disk
    return FileResponse(str(ROOT_DIR / "index.html"), media_type="text/html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)
