"""Pure-logic tests: verdict vocabulary, aggregation, policy guardrails, claim parsing."""
import pytest

from backend.models.schemas import Verdict, normalize_verdict, normalize_credibility
from backend.services.orchestration import verdict_aggregator as agg
from backend.services.orchestration.policy_engine import policy_engine
from backend.services.orchestration.claim_parser import claim_parser
from backend.services.llm_service import to_past_tense


@pytest.mark.parametrize("raw,expected", [
    ("SUPPORTED_CURRENT", "SUPPORTED"), ("VERIFIED", "SUPPORTED"), ("supported", "SUPPORTED"),
    ("CONTRADICTED", "REFUTED"), ("REFUTED", "REFUTED"),
    ("HISTORICAL SUPPORT ONLY", "SUPPORTED_HISTORICALLY"),
    ("INSUFFICIENT EVIDENCE", "INSUFFICIENT_EVIDENCE"), ("AMBIGUOUS_TIME_CONTEXT", "INSUFFICIENT_EVIDENCE"),
    ("MISLEADING", "CONFLICTING"), ("banana", "INSUFFICIENT_EVIDENCE"), (None, "INSUFFICIENT_EVIDENCE"),
])
def test_normalize_verdict(raw, expected):
    assert normalize_verdict(raw) == expected


@pytest.mark.parametrize("raw,expected", [(0.9, 0.9), (98.0, 0.98), (100, 1.0), ("x", 0.70), (None, 0.70), (-1, 0.0)])
def test_normalize_credibility(raw, expected):
    assert normalize_credibility(raw) == pytest.approx(expected)


def _c(source, stance, score=0.9, cred=0.9, cid=None):
    return {"chunk_id": cid or f"{source}-{stance}", "source": source, "stance": stance, "score": score, "credibility_score": cred}


def test_aggregator_one_vote_per_source():
    # Three chunks from one document are one witness, not three
    classified = [_c("A", "SUPPORTING", cid=f"a{i}") for i in range(3)] + [_c("B", "CONTRADICTING")]
    votes = agg.source_votes(classified)
    assert len(votes) == 2
    assert agg.decide(classified) == "CONFLICTING"


def test_aggregator_decisions():
    assert agg.decide([]) == "INSUFFICIENT_EVIDENCE"
    assert agg.decide([_c("A", "NEUTRAL")]) == "INSUFFICIENT_EVIDENCE"
    assert agg.decide([_c("A", "SUPPORTING"), _c("B", "SUPPORTING")]) == "SUPPORTED"
    assert agg.decide([_c("A", "SUPPORTING")], historical=True) == "SUPPORTED_HISTORICALLY"
    assert agg.decide([_c("A", "CONTRADICTING"), _c("B", "SUPPORTING", score=0.3, cred=0.5)]) == "REFUTED"


def test_scores_insufficient_is_zero_confidence():
    s = agg.score("INSUFFICIENT_EVIDENCE", [_c("A", "SUPPORTING")])
    assert s["confidence_score"] == 0 and s["verification_strength"] == "Insufficient"


def test_scores_agreement_counts_sources():
    s = agg.score("SUPPORTED", [_c("A", "SUPPORTING"), _c("B", "SUPPORTING"), _c("C", "CONTRADICTING")])
    assert s["evidence_agreement_score"] == pytest.approx(66.7, abs=0.1)
    assert s["supporting_sources"] == 2 and s["contradicting_sources"] == 1
    assert 0 < s["confidence_score"] <= 100


def test_scores_perfect_evidence():
    s = agg.score("REFUTED", [_c("A", "CONTRADICTING", 1.0, 1.0), _c("B", "CONTRADICTING", 1.0, 1.0)])
    assert s["confidence_score"] == 100.0 and s["verification_strength"] == "Strong"


def _analysis(verdict, stances, entity="Match", temporal="Unverified"):
    return {"verdict": verdict, "entity_match": entity, "temporal_match": temporal,
            "chunk_classifications": [{"chunk_id": f"c{i}", "stance": s} for i, s in enumerate(stances)]}


def test_policy_never_discards_supported_refutation():
    # The old engine turned this into INSUFFICIENT because entity_match was "Mismatch"
    r = policy_engine.determine_verdict({}, _analysis("REFUTED", ["CONTRADICTING"], entity="Mismatch"), [])
    assert r["verdict"] == "REFUTED"


def test_policy_entity_mismatch_blocks_support():
    r = policy_engine.determine_verdict({}, _analysis("SUPPORTED", ["SUPPORTING"], entity="Mismatch"), [])
    assert r["verdict"] == "INSUFFICIENT_EVIDENCE"


@pytest.mark.parametrize("verdict,stances", [
    ("SUPPORTED", ["NEUTRAL"]), ("REFUTED", ["SUPPORTING"]), ("CONFLICTING", ["SUPPORTING"]),
])
def test_policy_verdict_needs_matching_evidence(verdict, stances):
    assert policy_engine.determine_verdict({}, _analysis(verdict, stances), [])["verdict"] == "INSUFFICIENT_EVIDENCE"


def test_policy_current_claim_needs_fresh_support():
    stale = [{"chunk_id": "c0", "publication_date": "2015-01-01"}]
    r = policy_engine.determine_verdict({"currentness_required": True}, _analysis("SUPPORTED", ["SUPPORTING"]), stale, 90)
    assert r["verdict"] == "INSUFFICIENT_EVIDENCE"
    from datetime import datetime, timezone
    fresh = [{"chunk_id": "c0", "retrieval_date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}]
    r = policy_engine.determine_verdict({"currentness_required": True}, _analysis("SUPPORTED", ["SUPPORTING"]), fresh, 90)
    assert r["verdict"] == "SUPPORTED" and r["temporal_match"] == "Match"


def test_policy_outdated_flag():
    r = policy_engine.determine_verdict({"currentness_required": True},
                                        _analysis("REFUTED", ["CONTRADICTING"], temporal="Outdated"), [])
    assert r["verdict"] == "OUTDATED"


@pytest.mark.parametrize("claim,ctype,current,historical", [
    ("Narendra Modi is the Prime Minister of India.", "PERSON_ROLE", False, False),
    ("Shinzo Abe is the current Prime Minister of Japan", "PERSON_ROLE", True, False),
    ("Joe Biden was the President of the United States in 2023.", "PERSON_ROLE", False, True),
    ("Antibiotics can cure viral infections like the flu.", "SCIENTIFIC", False, False),
    ("India is the third largest economy in the world.", "STATISTICAL", False, False),
    ("The UN is headquartered in New York.", "LOCATION", False, False),
    # substring traps that the old parser fell into
    ("It is well known that the currency is secure", "AMBIGUOUS", False, False),
])
def test_claim_parser(claim, ctype, current, historical):
    c = claim_parser.parse(claim)
    assert (c.claim_type, c.currentness_required, c.historical) == (ctype, current, historical)


def test_claim_parser_subject():
    assert claim_parser.parse("Is Narendra Modi PM of India").subject == "Narendra Modi"
    assert claim_parser.parse("Earth").subject is None


@pytest.mark.parametrize("claim,past", [
    ("Shinzo Abe is the current Prime Minister of Japan", "Shinzo Abe was the Prime Minister of Japan"),
    ("Tim Cook is currently the CEO of Apple", "Tim Cook was the CEO of Apple"),
    ("The current Prime Minister of Japan is Shinzo Abe", "The Prime Minister of Japan was Shinzo Abe"),
])
def test_to_past_tense(claim, past):
    assert to_past_tense(claim) == past
