"""
Public-deployment contract: private per-client history, retention, rate limits, verdict cache,
cloud-LLM daily budget, feedback, production guard, error shape, security headers. Offline.
"""
import importlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.main as main
import backend.rate_limit as rl
import backend.result_cache as rc
import backend.services.orchestration.verification_orchestrator as orch_mod
from backend import config
from backend.database import db
from backend.main import app

L = importlib.import_module("backend.services.llm_service")
ROOT = Path(__file__).resolve().parent.parent

EVIDENCE = [{
    "chunk_id": "who", "source": "WHO antibiotic resistance fact sheet", "credibility_score": 0.95,
    "text": "Antibiotics are medicines used to treat bacterial infections. "
            "Antibiotics do not work against viral infections such as colds and flu.",
}]
CLAIM = "Antibiotics can cure viral infections like the flu."


def cid() -> dict:
    return {"X-Client-Id": str(uuid.uuid4())}


@pytest.fixture
def calls(monkeypatch):
    """Stubs retrieval with fixed evidence and counts how often the full pipeline runs."""
    counter = {"n": 0}

    def fake_retrieve(*a, **k):
        counter["n"] += 1
        return [dict(c) for c in EVIDENCE]
    monkeypatch.setattr(orch_mod.evidence_retriever, "retrieve", fake_retrieve)
    rl.limiter.reset()
    rc.result_cache.clear()
    return counter


@pytest.fixture
def client(calls):
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------- 1-2. identity + private history

def test_two_clients_cannot_see_each_others_history(client):
    a, b = cid(), cid()
    va = client.post("/api/verify", json={"claim": CLAIM}, headers=a).json()
    client.post("/api/verify", json={"claim": "Antibiotics treat bacterial infections."}, headers=b)

    ha = client.get("/api/history", headers=a).json()
    hb = client.get("/api/history", headers=b).json()
    assert [h["id"] for h in ha] == [va["id"]]
    assert len(hb) == 1 and hb[0]["id"] != va["id"]
    assert client.get(f"/api/history/{va['id']}", headers=a).status_code == 200
    assert client.get(f"/api/history/{va['id']}", headers=b).status_code == 404


def test_no_or_invalid_client_id_gets_result_but_no_history(client):
    for headers in ({}, {"X-Client-Id": "not-a-uuid"}, {"X-Client-Id": "6f1c2d3e-4b5a-1c6d-8e7f-9a0b1c2d3e4f"}):  # v1, not v4
        r = client.post("/api/verify", json={"claim": CLAIM}, headers=headers)
        assert r.status_code == 200 and r.json()["verdict"] == "REFUTED"
        assert client.get("/api/history", headers=headers).json() == []


def test_only_hash_of_client_id_is_stored(client):
    h = cid()
    v = client.post("/api/verify", json={"claim": CLAIM}, headers=h).json()
    conn = db.get_connection()
    stored = conn.execute("SELECT client_hash FROM verification_history WHERE id = ?", (v["id"],)).fetchone()[0]
    conn.close()
    assert stored and stored != h["X-Client-Id"] and len(stored) == 64


def test_delete_history_only_deletes_callers_rows(client):
    a, b = cid(), cid()
    for _ in range(2):
        client.post("/api/verify", json={"claim": CLAIM}, headers=a)
    client.post("/api/verify", json={"claim": CLAIM}, headers=b)
    r = client.delete("/api/history", headers=a)
    assert r.json() == {"status": "deleted", "count": 2}
    assert client.get("/api/history", headers=a).json() == []
    assert len(client.get("/api/history", headers=b).json()) == 1


def test_history_limit_validated(client):
    assert client.get("/api/history?limit=101", headers=cid()).status_code == 422
    assert client.get("/api/history?limit=0", headers=cid()).status_code == 422


def test_similar_claim_comes_only_from_own_history(client):
    a, b = cid(), cid()
    client.post("/api/verify", json={"claim": CLAIM}, headers=a)
    other = client.post("/api/verify", json={"claim": CLAIM}, headers=b).json()
    assert other["similar_claim_found"] is None
    again = client.post("/api/verify", json={"claim": CLAIM}, headers=a).json()
    assert again["similar_claim_found"] and again["similar_claim_found"]["claim"] == CLAIM


def test_analytics_scoped_to_caller(client):
    a, b = cid(), cid()
    client.post("/api/verify", json={"claim": CLAIM}, headers=a)
    client.post("/api/verify", json={"claim": CLAIM}, headers=a)
    sa = client.get("/api/analytics", headers=a).json()
    sb = client.get("/api/analytics", headers=b).json()
    assert sa["total_claims_verified"] == 2 and sa["verdict_counts"]["REFUTED"] == 2
    assert sb["total_claims_verified"] == 0 and sum(sb["verdict_counts"].values()) == 0
    assert sa["total_documents"] == sb["total_documents"]  # global, no claim text


def test_legacy_rows_without_owner_are_never_returned(client):
    db.save_verification({"id": "legacy-1", "claim": "an old public claim", "verdict": "REFUTED",
                          "confidence_score": 50, "explanation": "x"})
    h = cid()
    assert all(r["id"] != "legacy-1" for r in client.get("/api/history", headers=h).json())
    assert client.get("/api/history/legacy-1", headers=h).status_code == 404


# ---------------------------------------------------------------- 3. retention

def test_retention_purges_old_history_and_feedback():
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat(timespec="seconds")
    recent = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(timespec="seconds")
    db.save_verification({"id": "old-1", "claim": "a b c", "verdict": "REFUTED", "confidence_score": 1,
                          "explanation": "x", "timestamp": old}, "h")
    db.save_verification({"id": "new-1", "claim": "a b c", "verdict": "REFUTED", "confidence_score": 1,
                          "explanation": "x", "timestamp": recent}, "h")
    fb = db.save_feedback("v", "a b c", "REFUTED", None, None, "h")
    conn = db.get_connection()
    conn.execute("UPDATE feedback SET created_at = ? WHERE id = ?",
                 ((datetime.now(timezone.utc) - timedelta(days=100)).isoformat(timespec="seconds"), fb))
    conn.commit()
    conn.close()

    purged = db.purge_old_records(30, 90)
    assert purged["history"] >= 1 and purged["feedback"] >= 1
    ids = {r["id"] for r in db.get_verification_history("h", 100)}
    assert "old-1" not in ids and "new-1" in ids


# ---------------------------------------------------------------- 4. rate limiting

def test_verify_rate_limit_429_with_retry_after(client, monkeypatch):
    monkeypatch.setattr(config, "VERIFY_RATE_PER_MIN", 3)
    for _ in range(3):
        assert client.post("/api/verify", json={"claim": CLAIM}).status_code == 200
    r = client.post("/api/verify", json={"claim": CLAIM})
    assert r.status_code == 429
    body = r.json()
    assert int(r.headers["Retry-After"]) == body["retry_after"] and 1 <= body["retry_after"] <= 60
    assert body["detail"] == f"Too many requests. Try again in {body['retry_after']} seconds."


def test_rate_limit_window_slides(client, monkeypatch):
    monkeypatch.setattr(config, "VERIFY_RATE_PER_MIN", 2)
    clock = {"t": 1000.0}
    monkeypatch.setattr(rl, "_now", lambda: clock["t"])
    assert client.post("/api/verify", json={"claim": CLAIM}).status_code == 200
    clock["t"] += 30
    assert client.post("/api/verify", json={"claim": CLAIM}).status_code == 200
    assert client.post("/api/verify", json={"claim": CLAIM}).status_code == 429
    clock["t"] += 31  # first hit is now > 60 s old
    assert client.post("/api/verify", json={"claim": CLAIM}).status_code == 200


def test_rate_limit_buckets_are_independent(client, monkeypatch):
    monkeypatch.setattr(config, "VERIFY_RATE_PER_MIN", 1)
    monkeypatch.setattr(config, "FEEDBACK_RATE_PER_MIN", 1)
    assert client.post("/api/verify", json={"claim": CLAIM}).status_code == 200
    assert client.post("/api/verify", json={"claim": CLAIM}).status_code == 429
    fb = {"verification_id": "x", "claim": CLAIM, "verdict": "REFUTED"}
    assert client.post("/api/feedback", json=fb).status_code == 201
    assert client.post("/api/feedback", json=fb).status_code == 429


def test_extract_url_and_upload_are_rate_limited(client, monkeypatch):
    monkeypatch.setattr(config, "URL_EXTRACT_RATE_PER_MIN", 1)
    monkeypatch.setattr(config, "UPLOAD_RATE_PER_MIN", 1)
    assert client.post("/api/news/extract-url", json={"url": "http://127.0.0.1/"}).status_code == 400
    assert client.post("/api/news/extract-url", json={"url": "http://127.0.0.1/"}).status_code == 429
    client.post("/api/upload", files={"file": ("x.json", b"{}", "application/json")})
    assert client.post("/api/upload", files={"file": ("x.json", b"{}", "application/json")}).status_code == 429


def test_x_forwarded_for_only_trusted_behind_proxy(client, monkeypatch):
    monkeypatch.setattr(config, "VERIFY_RATE_PER_MIN", 1)
    spoof = {"X-Forwarded-For": "203.0.113.9"}
    monkeypatch.setattr(config, "TRUST_PROXY", False)
    assert client.post("/api/verify", json={"claim": CLAIM}, headers=spoof).status_code == 200
    # Without trust, a new spoofed XFF does not buy a fresh quota
    assert client.post("/api/verify", json={"claim": CLAIM}, headers={"X-Forwarded-For": "198.51.100.7"}).status_code == 429
    rl.limiter.reset()
    monkeypatch.setattr(config, "TRUST_PROXY", True)
    assert client.post("/api/verify", json={"claim": CLAIM}, headers={"X-Forwarded-For": "203.0.113.9, 10.0.0.1"}).status_code == 200
    assert client.post("/api/verify", json={"claim": CLAIM}, headers={"X-Forwarded-For": "198.51.100.7"}).status_code == 200
    assert client.post("/api/verify", json={"claim": CLAIM}, headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 429


# ---------------------------------------------------------------- 5. verdict cache

def test_repeated_claim_is_served_from_cache(client, calls, monkeypatch):
    monkeypatch.setattr(config, "CACHE_TTL_S", 3600)
    h = cid()
    first = client.post("/api/verify", json={"claim": CLAIM}, headers=h).json()
    second = client.post("/api/verify", json={"claim": "  ANTIBIOTICS can cure viral infections like the flu!! "}, headers=h).json()
    assert calls["n"] == 1
    assert first["cached"] is False and second["cached"] is True
    assert second["verdict"] == first["verdict"] and second["id"] != first["id"]
    assert {r["id"] for r in client.get("/api/history", headers=h).json()} == {first["id"], second["id"]}


def test_cache_bypassed_for_context_or_other_provider(client, calls, monkeypatch):
    monkeypatch.setattr(config, "CACHE_TTL_S", 3600)
    client.post("/api/verify", json={"claim": CLAIM})
    client.post("/api/verify", json={"claim": CLAIM, "context_text": "Some article text that is long enough to count."})
    client.post("/api/verify", json={"claim": CLAIM, "llm_provider": "offline"})
    assert calls["n"] == 3


def test_cache_expires_after_ttl(client, calls, monkeypatch):
    monkeypatch.setattr(config, "CACHE_TTL_S", 100)
    clock = {"t": 500.0}
    monkeypatch.setattr(rc, "_now", lambda: clock["t"])
    client.post("/api/verify", json={"claim": CLAIM})
    clock["t"] += 101
    assert client.post("/api/verify", json={"claim": CLAIM}).json()["cached"] is False
    assert calls["n"] == 2


def test_cache_is_bounded_and_skips_degraded_results(monkeypatch):
    from backend.models.schemas import VerificationResponse
    monkeypatch.setattr(config, "CACHE_TTL_S", 3600)
    monkeypatch.setattr(config, "CACHE_MAX_ENTRIES", 3)
    cache = rc.ResultCache()

    def resp(limitations=()):
        return VerificationResponse(id="x", claim="c", verdict="REFUTED", confidence_score=1, explanation="e",
                                    key_reasoning="k", timestamp="t", limitations=list(limitations))
    for i in range(5):
        cache.put((f"claim {i}", "auto"), resp())
    assert len(cache) == 3 and cache.get(("claim 0", "auto")) is None and cache.get(("claim 4", "auto"))
    assert cache.put(("x", "auto"), resp(["Cloud judge unavailable (HTTP 503); used the offline judge instead."])) is False


# ---------------------------------------------------------------- 6. cloud LLM daily budget

class _Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body, self.text = status, body, json.dumps(body or {})

    def json(self):
        return self._body


GOOD = {"verdict": "REFUTED", "explanation": "x", "key_reasoning": "y",
        "chunk_classifications": [{"chunk_id": "who", "stance": "CONTRADICTING", "score": 0.9, "rationale": "r"}]}


@pytest.fixture
def budget(monkeypatch):
    conn = db.get_connection()
    conn.execute("DELETE FROM llm_budget")
    conn.commit()
    conn.close()
    monkeypatch.setattr(L, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(L, "GEMINI_FALLBACK_MODELS", [])
    monkeypatch.setattr(L, "DEFAULT_LLM_PROVIDER", "auto")
    monkeypatch.setattr(L.time, "sleep", lambda s: None)
    posts = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        posts["n"] += 1
        return _Resp(200, {"candidates": [{"content": {"parts": [{"text": __import__("json").dumps(GOOD)}]}}]})
    monkeypatch.setattr(L.requests, "post", fake_post)
    return posts


def test_budget_counts_calls_and_falls_back_offline(monkeypatch, budget):
    monkeypatch.setattr(config, "LLM_DAILY_BUDGET", 2)
    chunks = [dict(c) for c in EVIDENCE]
    assert L.llm_service.verify_with_llm(CLAIM, chunks)["llm_provider_used"].startswith("Google Gemini")
    assert L.llm_service.verify_with_llm(CLAIM, chunks)["llm_provider_used"].startswith("Google Gemini")
    third = L.llm_service.verify_with_llm(CLAIM, chunks)
    assert budget["n"] == 2
    assert third["llm_provider_used"].startswith("Offline")
    assert third["judge_notes"] == ["Daily cloud-judge budget reached; used the offline judge."]
    assert db.llm_budget_used() == 2


def test_budget_zero_means_unlimited(monkeypatch, budget):
    monkeypatch.setattr(config, "LLM_DAILY_BUDGET", 0)
    for _ in range(3):
        assert L.llm_service.verify_with_llm(CLAIM, [dict(c) for c in EVIDENCE])["llm_provider_used"].startswith("Google")
    assert budget["n"] == 3


def test_budget_persists_in_db_and_is_per_day():
    assert db.llm_budget_try_consume(1, day="2001-01-01") is True
    assert db.llm_budget_try_consume(1, day="2001-01-01") is False
    assert db.llm_budget_try_consume(1, day="2001-01-02") is True
    assert db.llm_budget_used("2001-01-01") == 1


@pytest.mark.parametrize("path", ["/health", "/api/health"])
def test_health_reports_budget(client, monkeypatch, path):
    monkeypatch.setattr(config, "LLM_DAILY_BUDGET", 77)
    b = client.get(path).json()["llm_budget"]
    assert b["limit"] == 77 and isinstance(b["used"], int)


# ---------------------------------------------------------------- 7. feedback

def test_feedback_roundtrip_and_admin_listing(client, monkeypatch):
    import backend.security as security
    r = client.post("/api/feedback", json={"verification_id": "v1", "claim": CLAIM, "verdict": "REFUTED",
                                           "suggested_verdict": "SUPPORTED", "comment": "WHO page says otherwise"},
                    headers=cid())
    assert r.status_code == 201 and r.json()["status"] == "received" and uuid.UUID(r.json()["id"])
    monkeypatch.setattr(security, "ADMIN_TOKEN", "a" * 20)
    assert client.get("/api/feedback").status_code == 401
    rows = client.get("/api/feedback", headers={"X-Admin-Token": "a" * 20}).json()
    mine = next(row for row in rows if row["id"] == r.json()["id"])
    assert mine["suggested_verdict"] == "SUPPORTED" and mine["comment"] == "WHO page says otherwise"
    assert "client_hash" not in mine


@pytest.mark.parametrize("payload", [
    {"verification_id": "v", "claim": "ab", "verdict": "REFUTED"},
    {"verification_id": "v", "claim": CLAIM, "verdict": "REFUTED", "suggested_verdict": "TRUE"},
    {"verification_id": "v", "claim": CLAIM, "verdict": "REFUTED", "comment": "x" * 1001},
    {"claim": CLAIM, "verdict": "REFUTED"},
])
def test_feedback_validation(client, payload):
    r = client.post("/api/feedback", json=payload)
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)


# ---------------------------------------------------------------- 8. production guard

@pytest.mark.parametrize("token,ok", [("", False), ("short", False), ("x" * 16, True)])
def test_production_requires_strong_admin_token(monkeypatch, token, ok):
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    monkeypatch.setattr(config, "ADMIN_TOKEN", token)
    if ok:
        main.assert_production_ready()
    else:
        with pytest.raises(RuntimeError, match="ADMIN_TOKEN"):
            main.assert_production_ready()


def test_production_hides_api_docs(tmp_path):
    env = {**os.environ, "APP_ENV": "production", "ADMIN_TOKEN": "x" * 24, "TRUTHLENS_DATA_DIR": str(tmp_path)}
    code = ("from fastapi.testclient import TestClient; from backend.main import app; c = TestClient(app); "
            "print([c.get(p).status_code for p in ('/docs', '/redoc', '/openapi.json')])")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert out.stdout.strip().splitlines()[-1] == "[404, 404, 404]", out.stderr[-500:]


def test_development_keeps_docs(client):
    assert client.get("/openapi.json").status_code == 200


# ---------------------------------------------------------------- 9. error shape

def test_validation_error_detail_is_a_readable_string(client):
    r = client.post("/api/verify", json={"claim": "Earth"})
    assert r.status_code == 422
    assert r.json()["detail"].startswith("claim: Please enter a full statement")


def test_unknown_api_route_has_detail_string(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and isinstance(r.json()["detail"], str)


def test_unhandled_error_does_not_leak(client, monkeypatch):
    import backend.api.routes as routes

    def boom(*a, **k):
        raise RuntimeError("secret /Users/adi/.env path in exception")
    monkeypatch.setattr(routes.verification_service, "verify", boom)
    r = client.post("/api/verify", json={"claim": CLAIM})
    assert r.status_code == 500 and r.json() == {"detail": "Internal server error"}
    assert "secret" not in r.text
    assert r.headers["X-Content-Type-Options"] == "nosniff" and "Content-Security-Policy" in r.headers


# ---------------------------------------------------------------- 10. security headers

@pytest.mark.parametrize("path", ["/", "/api/health", "/health", "/favicon.svg", "/some/client/route"])
def test_security_headers_present(client, path):
    r = client.get(path)
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert r.headers["X-Frame-Options"] == "DENY"
    csp = r.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "connect-src 'self'" in csp


def test_csp_is_configurable(client, monkeypatch):
    monkeypatch.setattr(config, "CSP", "default-src 'none'")
    assert client.get("/health").headers["Content-Security-Policy"] == "default-src 'none'"


def test_error_responses_also_carry_security_headers(client):
    r = client.get("/api/nope")
    assert r.headers["X-Frame-Options"] == "DENY"


def test_verify_sheds_load_with_503_when_busy(monkeypatch):
    import threading
    import backend.api.routes as routes
    from fastapi.testclient import TestClient
    from backend.main import app
    monkeypatch.setattr(routes, "_verify_slots", threading.BoundedSemaphore(1))
    routes._verify_slots.acquire()  # simulate one verification already in flight at capacity 1
    try:
        r = TestClient(app).post("/api/verify", json={"claim": "Water boils at 100 degrees Celsius."})
    finally:
        routes._verify_slots.release()
    assert r.status_code == 503 and r.headers.get("retry-after") == "30"
    assert "busy" in r.json()["detail"]
