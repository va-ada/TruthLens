"""
Turns per-chunk stances into a verdict, confidence and agreement score.

Why per *source*: several chunks from one document are one witness, not several. Counting chunks
let one duplicated article produce "100% agreement" (see docs/ACCURACY_ROOT_CAUSE.md), so every
source casts exactly one vote, on the side where its strongest chunk sits.

Weight of a vote = stance probability (NLI/LLM, 0-1) x source credibility (0-1).

    S, C           = summed support / contradiction weights over independent sources
    verdict        = SUPPORTED   if S >= 2C  (SUPPORTED_HISTORICALLY for past-tense claims)
                     REFUTED     if C >= 2S
                     CONFLICTING otherwise
    agreement      = winning-side sources / all sources that took a side      (0-100)
    confidence     = mean winning-side weight x agreement                      (0-100)
                     CONFLICTING: mean weight x (minority / majority)
                     INSUFFICIENT_EVIDENCE: 0  (there is nothing to be confident about)
"""
from typing import Any, Dict, List

from backend.models.schemas import Verdict, normalize_credibility

SUPPORTING = "SUPPORTING"
CONTRADICTING = "CONTRADICTING"
DOMINANCE_RATIO = 2.0

_SIDE_FOR_VERDICT = {
    Verdict.SUPPORTED.value: SUPPORTING,
    Verdict.SUPPORTED_HISTORICALLY.value: SUPPORTING,
    Verdict.REFUTED.value: CONTRADICTING,
    Verdict.OUTDATED.value: CONTRADICTING,
}


def source_votes(classified: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """One vote per independent source: {source: {"side", "weight"}} (neutral sources are dropped)."""
    best: Dict[str, Dict[str, float]] = {}
    for c in classified:
        stance = c.get("stance")
        if stance not in (SUPPORTING, CONTRADICTING):
            continue
        source = c.get("source") or c.get("document_name") or c.get("chunk_id") or "unknown"
        weight = float(c.get("score", 0.75)) * normalize_credibility(c.get("credibility_score"))
        sides = best.setdefault(source, {SUPPORTING: 0.0, CONTRADICTING: 0.0})
        sides[stance] = max(sides[stance], weight)
    votes = {}
    for source, sides in best.items():
        side = SUPPORTING if sides[SUPPORTING] >= sides[CONTRADICTING] else CONTRADICTING
        votes[source] = {"side": side, "weight": sides[side]}
    return votes


def decide(classified: List[Dict[str, Any]], historical: bool = False) -> str:
    """Evidence-only verdict (used by the offline judge; the LLM judge proposes its own)."""
    votes = source_votes(classified)
    s = sum(v["weight"] for v in votes.values() if v["side"] == SUPPORTING)
    c = sum(v["weight"] for v in votes.values() if v["side"] == CONTRADICTING)
    if s == 0 and c == 0:
        return Verdict.INSUFFICIENT_EVIDENCE.value
    if s >= DOMINANCE_RATIO * c:
        return (Verdict.SUPPORTED_HISTORICALLY if historical else Verdict.SUPPORTED).value
    if c >= DOMINANCE_RATIO * s:
        return Verdict.REFUTED.value
    return Verdict.CONFLICTING.value


def score(verdict: str, classified: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Confidence / agreement / strength for a given final verdict, from the evidence alone."""
    votes = list(source_votes(classified).values())
    taking_side = len(votes)
    result = {
        "confidence_score": 0.0,
        "evidence_agreement_score": 0.0,
        "verification_strength": "Insufficient",
        "supporting_sources": sum(1 for v in votes if v["side"] == SUPPORTING),
        "contradicting_sources": sum(1 for v in votes if v["side"] == CONTRADICTING),
    }
    if verdict == Verdict.INSUFFICIENT_EVIDENCE.value or taking_side == 0:
        return result

    if verdict == Verdict.CONFLICTING.value:
        s_w = sum(v["weight"] for v in votes if v["side"] == SUPPORTING)
        c_w = sum(v["weight"] for v in votes if v["side"] == CONTRADICTING)
        mean_w = sum(v["weight"] for v in votes) / taking_side
        balance = min(s_w, c_w) / max(s_w, c_w) if max(s_w, c_w) > 0 else 0.0
        majority = max(result["supporting_sources"], result["contradicting_sources"])
        result["evidence_agreement_score"] = round(100.0 * majority / taking_side, 1)
        result["confidence_score"] = round(100.0 * mean_w * balance, 1)
        result["verification_strength"] = "Moderate" if result["confidence_score"] >= 45 else "Weak"
        return result

    side = _SIDE_FOR_VERDICT.get(verdict)
    winners = [v for v in votes if v["side"] == side]
    if not winners:
        return result
    agreement = len(winners) / taking_side
    mean_w = sum(v["weight"] for v in winners) / len(winners)
    confidence = 100.0 * mean_w * agreement
    result["evidence_agreement_score"] = round(100.0 * agreement, 1)
    result["confidence_score"] = round(confidence, 1)
    if confidence >= 70 and len(winners) >= 2:
        result["verification_strength"] = "Strong"
    elif confidence >= 45:
        result["verification_strength"] = "Moderate"
    else:
        result["verification_strength"] = "Weak"
    return result
