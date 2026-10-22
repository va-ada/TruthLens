"""
API smoke tests (replaces run_backend_test.py). Fully offline: retrieval is stubbed with fixed
evidence, so these check the HTTP contract, not live search. No startup event runs (TestClient is
not used as a context manager), so the news scheduler never fires.
"""
import pytest
from fastapi.testclient import TestClient

import backend.services.orchestration.verification_orchestrator as orch_mod
from backend.main import app
from backend.models.schemas import Verdict

CANONICAL = {v.value for v in Verdict}
EVIDENCE = [{
    "chunk_id": "who", "source": "WHO antibiotic resistance fact sheet", "credibility_score": 0.95,
    "text": "Antibiotics are medicines used to treat bacterial infections. "
            "Antibiotics do not work against viral infections such as colds and flu.",
}]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(orch_mod.evidence_retriever, "retrieve", lambda *a, **k: [dict(c) for c in EVIDENCE])
    return TestClient(app)


@pytest.fixture
def empty_client(monkeypatch):
    monkeypatch.setattr(orch_mod.evidence_retriever, "retrieve", lambda *a, **k: [])
    return TestClient(app)


def _check_verification(d):
    for field in ("id", "claim", "verdict", "confidence_score", "explanation", "supporting_evidence",
                  "contradicting_evidence", "neutral_evidence", "evidence_agreement_score",
                  "verification_strength", "llm_provider_used", "timestamp", "limitations"):
        assert field in d, field
    assert d["verdict"] in CANONICAL
    assert 0 <= d["confidence_score"] <= 100
    assert 0 <= d["evidence_agreement_score"] <= 100
    if d["verdict"] == Verdict.INSUFFICIENT_EVIDENCE.value:
        assert d["confidence_score"] == 0


@pytest.mark.parametrize("path", ["/health", "/api/health"])
def test_health(client, path):
    r = client.get(path)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy" and isinstance(body["indexed_chunks"], int)


def test_news_status_shape(client):
    r = client.get("/api/news/status")
    assert r.status_code == 200
    d = r.json()
    assert isinstance(d["active_feeds"], list) and len(d["active_feeds"]) >= 1
    assert isinstance(d["recent_articles"], list)


def test_trending_is_list_of_claims(client):
    r = client.get("/api/news/trending")
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list) and items and all(i.get("claim") for i in items)


def test_documents_history_analytics(client):
    assert isinstance(client.get("/api/documents").json(), list)
    assert isinstance(client.get("/api/history").json(), list)
    a = client.get("/api/analytics")
    assert a.status_code == 200
    assert set(a.json()["verdict_counts"]) == CANONICAL


def test_verify_refutes_with_evidence(client):
    r = client.post("/api/verify", json={"claim": "Antibiotics can cure viral infections like the flu."})
    assert r.status_code == 200, r.text
    d = r.json()
    _check_verification(d)
    assert d["verdict"] == "REFUTED"
    assert d["contradicting_evidence"] and d["contradicting_evidence"][0]["source"] == EVIDENCE[0]["source"]


def test_verify_without_evidence_is_insufficient_zero_confidence(empty_client):
    r = empty_client.post("/api/verify", json={"claim": "The moon is made of green cheese."})
    assert r.status_code == 200
    d = r.json()
    _check_verification(d)
    assert d["verdict"] == "INSUFFICIENT_EVIDENCE" and d["confidence_score"] == 0


def test_verification_is_saved_to_history(client):
    h = {"X-Client-Id": "6f1c2d3e-4b5a-4c6d-8e7f-9a0b1c2d3e4f"}
    d = client.post("/api/verify", json={"claim": "Antibiotics cure the flu."}, headers=h).json()
    r = client.get(f"/api/history/{d['id']}", headers=h)
    assert r.status_code == 200 and r.json()["verdict"] == d["verdict"]


@pytest.mark.parametrize("payload", [{}, {"claim": ""}, {"claim": "ab"}, {"claim": "Earth"}, {"claim": "Narendra Modi"},
                                     {"claim": "x " * 1001}, {"claim": "a valid claim", "top_k": 99}])
def test_verify_rejects_bad_input(client, payload):
    assert client.post("/api/verify", json=payload).status_code == 422


def test_clean_forward(client):
    r = client.post("/api/news/clean-forward", json={"text": "Forwarded as received: BREAKING NEWS: Antibiotics cure flu. Please share to all groups"})
    assert r.status_code == 200
    assert r.json()["cleaned_claim"] == "Antibiotics cure flu."
    assert client.post("/api/news/clean-forward", json={"text": ""}).status_code == 400


@pytest.mark.parametrize("text", ["BREAKING!! Antibiotics cure flu.", "Forwarded!!! Antibiotics cure flu.",
                                  "URGENT: Antibiotics cure flu.", "Viral message - Antibiotics cure flu."])
def test_clean_forward_punctuated_prefix(client, text):
    r = client.post("/api/news/clean-forward", json={"text": text})
    assert r.json()["cleaned_claim"] == "Antibiotics cure flu."


def test_clean_forward_keeps_words_that_merely_start_with_a_cue(client):
    r = client.post("/api/news/clean-forward", json={"text": "Urgently needed blood donors are rare."})
    assert r.json()["cleaned_claim"] == "Urgently needed blood donors are rare."


def test_unknown_history_404(client):
    assert client.get("/api/history/does-not-exist").status_code == 404
