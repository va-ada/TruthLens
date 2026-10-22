"""Cloud judge resilience: retries on overload, Gemini fallback models, honest offline fallback. No network."""
import json

import pytest

import importlib

# backend.services re-exports an `llm_service` INSTANCE that shadows the module attribute
L = importlib.import_module("backend.services.llm_service")

CHUNKS = [{"chunk_id": "a", "source": "WHO", "credibility_score": 0.95,
           "text": "Antibiotics do not work against viral infections such as colds and flu."}]
GOOD = {"verdict": "REFUTED", "explanation": "x", "key_reasoning": "y",
        "chunk_classifications": [{"chunk_id": "a", "stance": "CONTRADICTING", "score": 0.9, "rationale": "r"}]}


class Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body, self.text = status, body, json.dumps(body or {"error": status})

    def json(self):
        return self._body


def gemini_ok():
    return Resp(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(GOOD)}]}}]})


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    L.LLMService._cooldown_until.clear()
    monkeypatch.setattr(L.time, "sleep", lambda s: None)
    monkeypatch.setattr(L, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(L, "GEMINI_MODEL", "primary")
    monkeypatch.setattr(L, "GEMINI_FALLBACK_MODELS", ["backup"])
    monkeypatch.setattr(L, "DEFAULT_LLM_PROVIDER", "auto")


def scripted(monkeypatch, plan):
    """plan: {model_name: [responses...]} consumed in order; records calls."""
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        model = url.split("/models/")[1].split(":")[0]
        calls.append(model)
        assert "key=" not in url and headers["x-goog-api-key"] == "test-key"
        return plan[model].pop(0)
    monkeypatch.setattr(L.requests, "post", fake_post)
    return calls


def test_retries_then_succeeds(monkeypatch):
    calls = scripted(monkeypatch, {"primary": [Resp(503), gemini_ok()]})
    r = L.llm_service.verify_with_llm("Antibiotics cure flu", [dict(c) for c in CHUNKS])
    assert r["verdict"] == "REFUTED" and r["llm_provider_used"] == "Google Gemini (primary)"
    assert calls == ["primary"] * 2


def test_rate_limit_moves_to_next_model_without_retry(monkeypatch):
    calls = scripted(monkeypatch, {"primary": [Resp(429)], "backup": [gemini_ok()]})
    r = L.llm_service.verify_with_llm("Antibiotics cure flu", [dict(c) for c in CHUNKS])
    assert calls == ["primary", "backup"] and r["llm_provider_used"] == "Google Gemini (backup)"


def test_falls_back_to_backup_model(monkeypatch):
    calls = scripted(monkeypatch, {"primary": [Resp(503)] * 2, "backup": [gemini_ok()]})
    r = L.llm_service.verify_with_llm("Antibiotics cure flu", [dict(c) for c in CHUNKS])
    assert r["llm_provider_used"] == "Google Gemini (backup)" and calls == ["primary"] * 2 + ["backup"]


def test_non_retryable_error_skips_retries(monkeypatch):
    calls = scripted(monkeypatch, {"primary": [Resp(404)], "backup": [Resp(403)]})
    r = L.llm_service.verify_with_llm("Antibiotics cure flu", [dict(c) for c in CHUNKS])
    assert calls == ["primary", "backup"]
    assert r["llm_provider_used"].startswith("Offline")
    assert "HTTP 404" in r["judge_notes"][0] and "offline judge" in r["judge_notes"][0]


def test_offline_by_choice_has_no_judge_note(monkeypatch):
    monkeypatch.setattr(L, "GEMINI_API_KEY", "")
    r = L.llm_service.verify_with_llm("Antibiotics cure flu", [dict(c) for c in CHUNKS])
    assert r["llm_provider_used"].startswith("Offline") and "judge_notes" not in r


def test_rate_limited_model_is_skipped_during_cooldown(monkeypatch):
    calls = scripted(monkeypatch, {"primary": [Resp(429)], "backup": [gemini_ok(), gemini_ok()]})
    L.llm_service.verify_with_llm("Antibiotics cure flu", [dict(c) for c in CHUNKS])
    r = L.llm_service.verify_with_llm("Antibiotics cure flu", [dict(c) for c in CHUNKS])
    # second request goes straight to the backup model
    assert calls == ["primary", "backup", "backup"] and r["llm_provider_used"] == "Google Gemini (backup)"
