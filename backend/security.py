import hashlib
import hmac
import ipaddress
import re
import socket
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Optional

from fastapi import Header, HTTPException

from backend.config import ADMIN_TOKEN

ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".txt", ".md"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_FETCH_BYTES = 2 * 1024 * 1024


def require_admin(x_admin_token: Optional[str] = Header(None)) -> None:
    """Guards destructive/expensive endpoints. Open only when ADMIN_TOKEN is unset (local dev)."""
    if ADMIN_TOKEN and not hmac.compare_digest((x_admin_token or "").encode(), ADMIN_TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Admin token required for this action.")


UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def client_hash(x_client_id: Optional[str] = Header(None)) -> Optional[str]:
    """
    Anonymous per-browser identity: the UI sends a random UUIDv4 kept in localStorage. Only its sha256
    is stored. No/invalid id -> None (requests still work, but nothing is saved or returned as history).
    """
    cid = (x_client_id or "").strip().lower()
    if not UUID4.match(cid):
        return None
    return hashlib.sha256(cid.encode()).hexdigest()


def safe_upload_name(filename: Optional[str]) -> str:
    """
    Reduces a client-supplied filename to a bare basename so it can never escape UPLOADS_DIR
    (path traversal), and prefixes a short uuid so uploads cannot overwrite each other.
    """
    base = Path((filename or "").replace("\\", "/")).name.strip()
    if not base or base.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid file name.")
    ext = Path(base).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported file format. Please upload PDF, TXT, or MD.")
    return f"{uuid.uuid4().hex[:8]}_{base}"


def resolve_inside(directory: Path, name: str) -> Path:
    """Returns directory/name, refusing anything that resolves outside directory."""
    root = directory.resolve()
    target = (root / name).resolve()
    if target.parent != root:
        raise HTTPException(status_code=400, detail="Invalid file path.")
    return target


def _is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return addr.is_global and not addr.is_multicast


def assert_public_http_url(url: str) -> None:
    """
    SSRF guard: only http(s) URLs whose host resolves exclusively to public IPs.
    Blocks loopback, private ranges, link-local (cloud metadata 169.254.169.254) and reserved space.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Only public http(s) URLs are allowed.")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror:
        raise ValueError("Could not resolve the URL's host.")
    if not infos or not all(_is_public_ip(info[4][0]) for info in infos):
        raise ValueError("URLs pointing to private or internal addresses are not allowed.")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-checks every redirect hop so a public URL cannot bounce the fetch to an internal one."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        assert_public_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_public_url(url: str, headers: dict, timeout: int = 8) -> str:
    """Fetches a public web page with SSRF checks and a hard size cap; returns decoded text."""
    assert_public_http_url(url)
    opener = urllib.request.build_opener(_SafeRedirectHandler)
    req = urllib.request.Request(url, headers=headers)
    with opener.open(req, timeout=timeout) as res:
        raw = res.read(MAX_FETCH_BYTES + 1)
    return raw[:MAX_FETCH_BYTES].decode("utf-8", errors="ignore")
