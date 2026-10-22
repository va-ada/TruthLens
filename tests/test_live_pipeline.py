"""
Live end-to-end pipeline test: real local index + live Wikipedia + offline NLI judge.
Network-dependent, so it is skipped by default; run with:  pytest -m network
Only clear-cut, stable claims are used, each with ONE acceptable verdict.
"""
import pytest

from backend.api.routes import seed_trusted_knowledge_base
from backend.models.schemas import ClaimVerificationRequest
from backend.services.verification_service import verification_service

pytestmark = pytest.mark.network


@pytest.fixture(scope="module", autouse=True)
def seeded():
    seed_trusted_knowledge_base()


@pytest.mark.parametrize("claim,expected", [
    ("Narendra Modi is the Prime Minister of India.", "SUPPORTED"),
    ("Donald Trump is the Prime Minister of India.", "REFUTED"),
    ("Antibiotics can cure viral infections like the flu.", "REFUTED"),
    ("Shinzo Abe is the current Prime Minister of Japan", "OUTDATED"),
])
def test_live_pipeline_verdicts(claim, expected):
    res = verification_service.verify(ClaimVerificationRequest(claim=claim, llm_provider="offline"))
    assert res.verdict == expected, (res.verdict, res.key_reasoning)
    assert res.confidence_score > 0
    side = res.supporting_evidence if expected == "SUPPORTED" else res.contradicting_evidence
    assert side, "verdict must be backed by evidence on its side"
    assert all(e.source and e.rationale for e in side)
