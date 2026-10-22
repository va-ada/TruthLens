import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from backend.models.schemas import (
    ClaimVerificationRequest,
    VerificationResponse,
    EvidenceChunk,
    Verdict,
    normalize_credibility
)
from backend.services.orchestration.claim_parser import claim_parser
from backend.services.orchestration.source_planner import source_planner
from backend.services.orchestration.evidence_retriever import evidence_retriever
from backend.services.orchestration.recommendation_engine import recommendation_engine
from backend.services.orchestration.policy_engine import policy_engine
from backend.services.orchestration import verdict_aggregator
from backend.services.llm_service import llm_service


class VerificationOrchestrator:
    def process(self, request: ClaimVerificationRequest) -> VerificationResponse:
        claim_str = request.claim.strip()

        # 1. Parse structured claim, 2. plan sources, 3. retrieve evidence
        structured_claim = claim_parser.parse(claim_str)
        strategy = source_planner.get_source_strategy(structured_claim)
        raw_chunks = evidence_retriever.retrieve(claim_str, strategy, top_k=request.top_k or 8)

        # Client-supplied article text (e.g. from a news app) is evidence too, but it is the
        # claimant's own material, so it gets ordinary rather than maximal credibility
        if request.context_text and len(request.context_text.strip()) > 20:
            raw_chunks.insert(0, {
                "chunk_id": f"client-context-{uuid.uuid4().hex[:8]}",
                "document_name": "Source Article from Client",
                "source": "Directly Supplied Context from Client",
                "source_type": "Client-Supplied Context",
                "text": request.context_text.strip(),
                "relevance_score": 1.0,
                "credibility_score": 0.60
            })

        # Unique, string chunk ids so judge classifications map back to exactly one chunk
        seen_ids = set()
        for i, c in enumerate(raw_chunks):
            cid = str(c.get("chunk_id") or f"chunk-{i}")
            if cid in seen_ids:
                cid = f"{cid}-{i}"
            seen_ids.add(cid)
            c["chunk_id"] = cid
            c["credibility_score"] = normalize_credibility(c.get("credibility_score"))

        # 4. Judge: cloud LLM if configured, else offline DeBERTa NLI
        analysis = llm_service.verify_with_llm(
            claim_str,
            raw_chunks,
            provider=request.llm_provider or "auto",
            custom_api_key=request.api_key,
            historical=structured_claim.historical,
            changes_over_time=structured_claim.claim_type == "PERSON_ROLE" or structured_claim.currentness_required
        )

        # 5. Deterministic guardrails
        claim_info = {
            "currentness_required": structured_claim.currentness_required,
            "claim_type": structured_claim.claim_type
        }
        policy_result = policy_engine.determine_verdict(
            claim_info, analysis, raw_chunks, freshness_days=strategy.get("required_freshness_days", 365)
        )
        verdict = policy_result["verdict"]

        # 6. Evidence lists, carrying each chunk's stance probability and rationale
        by_id = {c["chunk_id"]: c for c in raw_chunks}
        classified: List[Dict[str, Any]] = []
        supporting, contradicting, neutral = [], [], []
        for cls in analysis.get("chunk_classifications", []):
            chunk = by_id.get(str(cls.get("chunk_id")))
            if not chunk:
                continue
            classified.append({**cls, "source": chunk.get("source") or chunk.get("document_name"),
                               "credibility_score": chunk["credibility_score"]})
            ec = EvidenceChunk(
                id=str(uuid.uuid4()),
                chunk_id=chunk["chunk_id"],
                document_name=chunk.get("document_name", "Unknown Document"),
                source=chunk.get("source", "Unknown Source"),
                source_type=chunk.get("source_type", "General"),
                url=chunk.get("url") or None,
                page_number=chunk.get("page_number") or 1,
                text=chunk.get("text", ""),
                text_excerpt=chunk.get("text", "")[:200],
                relevance_score=float(chunk.get("relevance_score", 0.0)),
                stance=cls.get("stance", "NEUTRAL"),
                stance_score=float(cls.get("score", 0.0)),
                rationale=cls.get("rationale", ""),
                credibility_score=chunk["credibility_score"],
                publication_date=chunk.get("publication_date") or None,
                retrieval_date=chunk.get("retrieval_date") or None,
                support_type=chunk.get("support_type")
            )
            {"SUPPORTING": supporting, "CONTRADICTING": contradicting}.get(ec.stance, neutral).append(ec)

        # 7. Confidence / agreement from evidence (same formula for LLM and offline judges)
        scores = verdict_aggregator.score(verdict, classified)

        # 8. Recommendation, limitations, analysis blocks
        recommendation = recommendation_engine.generate(structured_claim, strategy)
        limitations = (list(strategy.get("retrieval_notes", [])) + list(analysis.get("judge_notes", []))
                       + list(policy_result.get("policy_notes", [])))
        provider = analysis.get("llm_provider_used", "Orchestrator")
        if provider.startswith("Offline"):
            limitations.append("Judged offline by an NLI model, which reads each passage literally and cannot reason about dates or numbers the way an LLM can.")
        if not raw_chunks:
            limitations.append("No evidence was retrieved from the knowledge vault or live sources.")
        elif scores["supporting_sources"] + scores["contradicting_sources"] == 1 and verdict != Verdict.INSUFFICIENT_EVIDENCE.value:
            limitations.append("Only one independent source took a position; corroboration not established.")

        return VerificationResponse(
            id=str(uuid.uuid4()),
            claim=claim_str,
            claim_type=structured_claim.claim_type,
            verdict=verdict,
            confidence_score=scores["confidence_score"],
            verification_strength=scores["verification_strength"],
            explanation=policy_result["explanation"] or analysis.get("explanation", ""),
            key_reasoning=policy_result["key_reasoning"] if isinstance(policy_result["key_reasoning"], str) else "\n".join(policy_result["key_reasoning"]),
            entity_analysis={
                "subject": structured_claim.subject,
                "role": structured_claim.role,
                "entity_match": policy_result["entity_match"],
                "country_match": policy_result["country_match"],
                "role_match": policy_result["role_match"],
            },
            temporal_analysis={
                "time_expression": structured_claim.time_expression,
                "requires_current_evidence": structured_claim.currentness_required,
                "historical_claim": structured_claim.historical,
                "temporal_match": policy_result["temporal_match"],
            },
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            neutral_evidence=neutral,
            evidence_agreement_score=scores["evidence_agreement_score"],
            agreement_analysis=(f"{scores['supporting_sources']} independent source(s) support, "
                                f"{scores['contradicting_sources']} contradict."),
            verification_recommendation=recommendation,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            limitations=limitations,
            entity_match=policy_result["entity_match"],
            temporal_match=policy_result["temporal_match"],
            country_match=policy_result["country_match"],
            role_match=policy_result["role_match"],
            llm_provider_used=provider,
            timestamp=datetime.now(timezone.utc).isoformat()
        )


verification_orchestrator = VerificationOrchestrator()
