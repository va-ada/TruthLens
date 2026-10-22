from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.models.schemas import Verdict, normalize_verdict

SUPPORT_VERDICTS = {Verdict.SUPPORTED.value, Verdict.SUPPORTED_HISTORICALLY.value}
REFUTE_VERDICTS = {Verdict.REFUTED.value, Verdict.OUTDATED.value}


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value.strip(), fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class PolicyEngine:
    """
    Deterministic guardrails applied after the judge (LLM or offline NLI).
    Rules only ever make a verdict MORE cautious when the evidence does not back it; they never turn a
    supported refutation into "insufficient" (the old engine did, discarding correct REFUTED answers).
    """

    def determine_verdict(self, claim_info: dict, evidence_analysis: dict, chunks: List[Dict[str, Any]],
                          freshness_days: int = 365) -> dict:
        verdict = normalize_verdict(evidence_analysis.get("verdict"))
        entity_match = evidence_analysis.get("entity_match", "Unverified")
        temporal_match = evidence_analysis.get("temporal_match", "Unverified")
        classifications = evidence_analysis.get("chunk_classifications") or []
        applied: List[str] = []

        supporting_ids = {str(c.get("chunk_id")) for c in classifications if c.get("stance") == "SUPPORTING"}
        contradicting_ids = {str(c.get("chunk_id")) for c in classifications if c.get("stance") == "CONTRADICTING"}

        # R1: a verdict must be backed by at least one passage on its side
        if verdict in SUPPORT_VERDICTS and not supporting_ids:
            verdict = Verdict.INSUFFICIENT_EVIDENCE.value
            applied.append("Judge claimed support, but no passage was classified as supporting.")
        if verdict in REFUTE_VERDICTS and not contradicting_ids:
            verdict = Verdict.INSUFFICIENT_EVIDENCE.value
            applied.append("Judge claimed contradiction, but no passage was classified as contradicting.")
        if verdict == Verdict.CONFLICTING.value and not (supporting_ids and contradicting_ids):
            verdict = Verdict.INSUFFICIENT_EVIDENCE.value
            applied.append("Judge claimed conflicting evidence, but passages do not point both ways.")

        # R2: support requires that some evidence actually names the claim's subject
        if verdict in SUPPORT_VERDICTS and entity_match == "Mismatch":
            verdict = Verdict.INSUFFICIENT_EVIDENCE.value
            applied.append("Supporting passages never mention the claim's subject (entity mismatch).")

        # R3: present-tense claims need evidence the judge flagged as outdated to be OUTDATED, and need
        # fresh evidence to be SUPPORTED
        if claim_info.get("currentness_required"):
            if temporal_match == "Outdated" and verdict != Verdict.SUPPORTED_HISTORICALLY.value:
                verdict = Verdict.OUTDATED.value
            elif verdict == Verdict.SUPPORTED.value:
                now = datetime.now(timezone.utc)
                dates = [_parse_date(c.get("publication_date") or c.get("retrieval_date"))
                         for c in chunks if str(c.get("chunk_id")) in supporting_ids]
                fresh = [d for d in dates if d and (now - d).days <= freshness_days]
                if not fresh:
                    verdict = Verdict.INSUFFICIENT_EVIDENCE.value
                    temporal_match = "Unverified"
                    applied.append(f"Claim is about the present, but no supporting passage is dated within {freshness_days} days.")
                else:
                    temporal_match = "Match"

        return {
            "verdict": verdict,
            "explanation": evidence_analysis.get("explanation", ""),
            "key_reasoning": evidence_analysis.get("key_reasoning", ""),
            "entity_match": entity_match,
            "temporal_match": temporal_match,
            "country_match": evidence_analysis.get("country_match", "Not Applicable"),
            "role_match": evidence_analysis.get("role_match", "Not Applicable"),
            "policy_notes": applied
        }


policy_engine = PolicyEngine()
