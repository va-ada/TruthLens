import socket

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import backend.api.routes as routes
import backend.security as security
from backend.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """App client with uploads in tmp_path and indexing/DB writes stubbed out."""
    monkeypatch.setattr(routes, "UPLOADS_DIR", tmp_path)
    monkeypatch.setattr(routes.retrieval_service, "add_chunks", lambda chunks: len(chunks))
    monkeypatch.setattr(routes, "save_document", lambda **kw: "doc-1")
    return TestClient(app)


# --- Path traversal (A1) ---

@pytest.mark.parametrize("name", ["../../evil.txt", "..\\..\\evil.txt", "/etc/evil.txt", "a/b/../../../evil.txt"])
def test_safe_upload_name_strips_directories(name):
    safe = security.safe_upload_name(name)
    assert "/" not in safe and "\\" not in safe and ".." not in safe
    assert safe.endswith("_evil.txt")


@pytest.mark.parametrize("name", ["", None, ".env", "../.."])
def test_safe_upload_name_rejects_empty_or_hidden(name):
    with pytest.raises(HTTPException) as e:
        security.safe_upload_name(name)
    assert e.value.status_code == 400


@pytest.mark.parametrize("name", ["x.json", "x.exe", "x.html", "noext"])
def test_safe_upload_name_rejects_bad_extensions(name):
    with pytest.raises(HTTPException):
        security.safe_upload_name(name)


def test_resolve_inside_blocks_escape(tmp_path):
    with pytest.raises(HTTPException):
        security.resolve_inside(tmp_path, "../outside.txt")
    assert security.resolve_inside(tmp_path, "ok.txt") == (tmp_path / "ok.txt").resolve()


def test_upload_traversal_lands_inside_uploads(client, tmp_path):
    body = b"A perfectly ordinary paragraph of reference text for the upload test."
    r = client.post("/api/upload", files={"file": ("../../TRAVERSAL.txt", body, "text/plain")})
    assert r.status_code == 200, r.text
    saved = list(tmp_path.iterdir())
    assert len(saved) == 1 and saved[0].name.endswith("_TRAVERSAL.txt")
    assert not (tmp_path.parent.parent / "TRAVERSAL.txt").exists()


# --- Upload size / type (A4) ---

def test_upload_over_10mb_rejected_and_not_left_on_disk(client, tmp_path):
    big = b"a" * (security.MAX_UPLOAD_BYTES + 1)
    r = client.post("/api/upload", files={"file": ("big.txt", big, "text/plain")})
    assert r.status_code == 413
    assert list(tmp_path.iterdir()) == []


def test_upload_json_rejected(client):
    r = client.post("/api/upload", files={"file": ("x.json", b"{}", "application/json")})
    assert r.status_code == 400


# --- SSRF (A2) ---

@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8077/",
    "http://localhost/",
    "http://10.0.0.1/",
    "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "file:///etc/passwd",
    "ftp://example.com/",
])
def test_assert_public_http_url_blocks_internal(url):
    with pytest.raises(ValueError):
        security.assert_public_http_url(url)


def test_assert_public_http_url_allows_public(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, ("93.184.216.34", 443))])
    security.assert_public_http_url("https://example.com/news")


def test_assert_public_http_url_blocks_mixed_dns(monkeypatch):
    # A host that resolves to one public and one private IP must be refused
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [
        (None, None, None, None, ("93.184.216.34", 443)),
        (None, None, None, None, ("10.0.0.5", 443)),
    ])
    with pytest.raises(ValueError):
        security.assert_public_http_url("https://example.com/")


def test_extract_url_endpoint_returns_400_for_localhost(client):
    r = client.post("/api/news/extract-url", json={"url": "http://127.0.0.1:8077/"})
    assert r.status_code == 400


# --- Admin token (A3) ---

def test_admin_endpoints_require_token_when_configured(client, monkeypatch):
    monkeypatch.setattr(security, "ADMIN_TOKEN", "s3cret")
    assert client.delete("/api/documents/nope").status_code == 401
    assert client.post("/api/seed").status_code == 401
    assert client.post("/api/news/sync").status_code == 401
    assert client.post("/api/news/train-dataset").status_code == 401
    r = client.post("/api/upload", files={"file": ("a.txt", b"x" * 50, "text/plain")})
    assert r.status_code == 401
    # Correct token passes the guard (404 = reached the handler, document doesn't exist)
    assert client.delete("/api/documents/nope", headers={"X-Admin-Token": "s3cret"}).status_code == 404


def test_admin_endpoints_open_when_token_unset(client, monkeypatch):
    monkeypatch.setattr(security, "ADMIN_TOKEN", "")
    assert client.delete("/api/documents/nope").status_code == 404


# --- CORS (A5) ---

def test_no_cors_headers_for_foreign_origin_by_default(client):
    r = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


# --- Static file exposure (found during Phase 7: catch-all route served any project file) ---

@pytest.mark.parametrize("path", ["/.env", "/.env.example", "/backend/config.py", "/server.log",
                                  "/backend/database/truthlens.db", "/requirements.txt", "/.git/config",
                                  "/..%2f..%2fetc/hosts"])
def test_private_files_are_never_served(client, path):
    r = client.get(path)
    # Unknown paths get the SPA shell (HTML) — never the file's own bytes
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert b"<!DOCTYPE html>" in r.content[:200]
    assert b"API_KEY" not in r.content


@pytest.mark.parametrize("path,ctype", [("/favicon.svg", "image/svg+xml"), ("/favicon.png", "image/png")])
def test_public_assets_still_served(client, path, ctype):
    r = client.get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith(ctype)


def test_unknown_api_path_is_404(client):
    assert client.get("/api/does-not-exist").status_code == 404


def test_static_assets_are_gzipped(client):
    r = client.get("/static/app.js", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers.get("content-encoding") == "gzip"
