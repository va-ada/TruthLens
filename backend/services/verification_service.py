import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from backend.models.schemas import (
    ClaimVerificationRequest,
    VerificationResponse,
    SimilarClaim
)
from backend.services.retrieval_service import retrieval_service
from backend.result_cache import result_cache, normalize_claim
from backend.services.orchestration.verification_orchestrator import verification_orchestrator
from backend.database.db import (
    save_verification,
    find_most_similar_claim
)

class VerificationService:
    @staticmethod
    def _cache_key(request: ClaimVerificationRequest):
        """Only plain claims are cached: client context or a caller-supplied key change the judgement."""
        if request.context_text or request.api_key:
            return None
        return (normalize_claim(request.claim), (request.llm_provider or "auto").lower())

    def verify(self, request: ClaimVerificationRequest, client_hash: Optional[str] = None) -> VerificationResponse:
        claim = request.claim.strip()

        # Step 1: Check the caller's own history for a similar claim (never other people's)
        similar_match = find_most_similar_claim(claim, client_hash)
        similar_claim_obj = None
        if similar_match:
            similar_claim_obj = SimilarClaim(
                id=similar_match["id"],
                claim=similar_match["claim"],
                verdict=similar_match["verdict"],
                confidence_score=similar_match["confidence_score"],
                timestamp=similar_match["timestamp"],
                similarity_score=similar_match["similarity_score"]
            )

        # Step 2: Check if knowledge base has documents and auto-seed if needed
        total_chunks_available = retrieval_service.count()
        if total_chunks_available == 0:
            try:
                from backend.api.routes import seed_trusted_knowledge_base
                seed_trusted_knowledge_base()
            except Exception as e:
                print(f"[VerificationService] Auto-seed notice: {e}")

        # Repeated identical claim: reuse the verdict (fresh id/timestamp, still saved to the caller's history)
        key = self._cache_key(request)
        cached = result_cache.get(key) if key else None
        if cached:
            cached.id = str(uuid.uuid4())
            cached.timestamp = datetime.now(timezone.utc).isoformat()
            cached.claim = claim
            cached.cached = True
            cached.similar_claim_found = similar_claim_obj
            if client_hash:
                save_verification(cached.model_dump(), client_hash)
            return cached

        # Step 3: Delegate to the Evidence-First Orchestrator
        orchestrator_response = verification_orchestrator.process(request)

        # Step 4: Extract retrieved sources for UI grouping
        sources_dict: Dict[str, Dict[str, Any]] = {}
        all_chunks = orchestrator_response.supporting_evidence + orchestrator_response.contradicting_evidence + orchestrator_response.neutral_evidence
        
        cred_sum = 0.0
        for c in all_chunks:
            s_name = c.source or "Unknown"
            p_num = c.page_number or 1
            cred_val = float(c.credibility_score or 0.70)
            cred_sum += cred_val
            
            if s_name not in sources_dict:
                sources_dict[s_name] = {
                    "document_name": c.document_name or s_name,
                    "source": s_name,
                    "source_type": c.source_type or "General",
                    "url": c.url or "",
                    "credibility_score": round(cred_val * 100, 1),
                    "pages": [p_num]
                }
            elif p_num not in sources_dict[s_name]["pages"]:
                sources_dict[s_name]["pages"].append(p_num)
            
            # If a source already existed but was missing URL, update it
            if not sources_dict[s_name].get("url") and c.url:
                sources_dict[s_name]["url"] = c.url

        retrieved_sources_list = list(sources_dict.values())
        for s in retrieved_sources_list:
            s["pages"].sort()
            
        orchestrator_response.retrieved_sources = retrieved_sources_list
        orchestrator_response.source_credibility_score = round((cred_sum / max(1, len(all_chunks))) * 100, 1)

        if key:
            result_cache.put(key, orchestrator_response)  # cached without the caller-specific similar claim
        if similar_claim_obj:
            orchestrator_response.similar_claim_found = similar_claim_obj

        # Step 5: Save to the caller's history (anonymous callers get a result but no stored history)
        if client_hash:
            save_verification(orchestrator_response.model_dump(), client_hash)

        return orchestrator_response

verification_service = VerificationService()
