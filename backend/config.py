import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

IS_VERCEL = bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))

BASE_DIR = Path(__file__).resolve().parent.parent
TRUSTED_DOCS_DIR = BASE_DIR / "data" / "trusted_docs"

if os.getenv("TRUTHLENS_DATA_DIR"):
    # Isolated storage root (used by the test suite so it never touches real data)
    _root = Path(os.environ["TRUTHLENS_DATA_DIR"])
    DATA_DIR = _root / "data"
    UPLOADS_DIR = DATA_DIR / "uploads"
    CHROMA_PERSIST_DIR = _root / "chroma_db"
    DB_PATH = _root / "truthlens.db"
elif IS_VERCEL:
    DATA_DIR = Path("/tmp/data")
    UPLOADS_DIR = DATA_DIR / "uploads"
    CHROMA_PERSIST_DIR = Path("/tmp/chroma_db")
    DB_PATH = Path("/tmp/truthlens.db")
else:
    DATA_DIR = BASE_DIR / "data"
    UPLOADS_DIR = DATA_DIR / "uploads"
    CHROMA_PERSIST_DIR = BASE_DIR / "chroma_db"
    DB_PATH = BASE_DIR / "backend" / "database" / "truthlens.db"

# Safely create required directories
for d in [DATA_DIR, TRUSTED_DOCS_DIR, UPLOADS_DIR, CHROMA_PERSIST_DIR, DB_PATH.parent]:
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

# Vector DB & Embeddings
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2")
CHROMA_COLLECTION_NAME = "truthlens_evidence_vault"

# RAG Hyperparameters
RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "12"))  # Candidate chunks fetched
RERANK_TOP_K = int(os.getenv("RERANK_TOP_K", "5"))         # Top chunks passed to LLM
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.35"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "450"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "60"))

# Source Credibility Scoring Weights
SOURCE_CREDIBILITY_WEIGHTS = {
    "government": 0.95,
    "official": 0.95,
    "peer-reviewed": 0.95,
    "academic": 0.92,
    "established news": 0.85,
    "reputable media": 0.82,
    "general": 0.65,
    "unknown": 0.50
}

# LLM Providers Configuration
DEFAULT_LLM_PROVIDER = os.getenv("DEFAULT_LLM_PROVIDER", "auto")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
# Model names change over time; override in .env without touching code
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_FALLBACK_MODELS = [m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-flash-lite-latest,gemini-flash-latest,gemini-3.5-flash").split(",") if m.strip()]
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
# Per-call timeout; overloaded preview models can hang ~40 s before answering 503
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "20"))

# Security
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
# Comma-separated origins allowed to call the API cross-origin (the bundled UI is same-origin and needs none)
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]

# Production / public deployment
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"
# Only trust X-Forwarded-For when running behind a reverse proxy that sets it (e.g. Caddy)
TRUST_PROXY = os.getenv("TRUST_PROXY", "0").strip() in ("1", "true", "yes")

# Per-client-IP rate limits (requests per rolling minute)
VERIFY_RATE_PER_MIN = int(os.getenv("VERIFY_RATE_PER_MIN", "10"))
URL_EXTRACT_RATE_PER_MIN = int(os.getenv("URL_EXTRACT_RATE_PER_MIN", "10"))
FEEDBACK_RATE_PER_MIN = int(os.getenv("FEEDBACK_RATE_PER_MIN", "5"))
UPLOAD_RATE_PER_MIN = int(os.getenv("UPLOAD_RATE_PER_MIN", "5"))

# Verdict cache for repeated identical claims (0 disables)
CACHE_TTL_S = int(os.getenv("CACHE_TTL_S", "21600"))
CACHE_MAX_ENTRIES = int(os.getenv("CACHE_MAX_ENTRIES", "1000"))

# Max cloud-LLM HTTP calls per UTC day across the whole server (0 = unlimited)
LLM_DAILY_BUDGET = int(os.getenv("LLM_DAILY_BUDGET", "500"))

# Data retention
HISTORY_RETENTION_DAYS = int(os.getenv("HISTORY_RETENTION_DAYS", "30"))
FEEDBACK_RETENTION_DAYS = int(os.getenv("FEEDBACK_RETENTION_DAYS", "90"))

# Content-Security-Policy header (empty = default, which expects a self-hosted, pre-built frontend)
DEFAULT_CSP = (
    "default-src 'self'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https:; connect-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)
CSP = os.getenv("CSP", "").strip() or DEFAULT_CSP

# Wikimedia API etiquette: the User-Agent must say how to reach the operator (email or URL)
OPERATOR_CONTACT = os.getenv("OPERATOR_CONTACT") or "https://github.com/Prashantj44/Truth-Lens"

# Load shedding: verifications in flight per container before /api/verify answers 503 "busy"
MAX_CONCURRENT_VERIFICATIONS = int(os.getenv("MAX_CONCURRENT_VERIFICATIONS", "4"))
