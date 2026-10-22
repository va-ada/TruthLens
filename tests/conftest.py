import os
import sys
import tempfile
from pathlib import Path

# Must run before any backend import: point all storage at a throwaway directory
os.environ["TRUTHLENS_DATA_DIR"] = tempfile.mkdtemp(prefix="truthlens-test-")
os.environ.pop("VERCEL", None)
for key in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "ADMIN_TOKEN", "ALLOWED_ORIGINS"):
    os.environ[key] = ""
os.environ["DEFAULT_LLM_PROVIDER"] = "offline"
os.environ["WIKI_CACHE_TTL_S"] = "0"  # tests patch HTTP; never serve them cached responses
# Generous limits and no verdict cache by default, so unrelated tests are not throttled or served
# cached answers; tests of those features set the values they need explicitly.
for key in ("VERIFY_RATE_PER_MIN", "URL_EXTRACT_RATE_PER_MIN", "FEEDBACK_RATE_PER_MIN", "UPLOAD_RATE_PER_MIN"):
    os.environ[key] = "100000"
os.environ["CACHE_TTL_S"] = "0"
os.environ.pop("APP_ENV", None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
