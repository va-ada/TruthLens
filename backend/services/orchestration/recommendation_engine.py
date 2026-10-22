from backend.models.schemas import StructuredClaim, VerificationRecommendation

class RecommendationEngine:
    def __init__(self):
        pass

    def generate(self, claim: StructuredClaim, strategy: dict) -> VerificationRecommendation:
        subject = claim.subject or "the subject of the claim"
        target_domain = ", ".join(strategy.get("target_domains", [])) if strategy.get("target_domains") else "Official domain for the entity"
        source_type = strategy.get("preferred_source_type", "Official source")
        
        what_to_check = "Look for the specific proposition stated in the claim."
        what_confirms = "The source explicitly states the information matching the claim."
        what_refutes = "The source provides contradictory information or lists a different current status."
        
        if claim.claim_type == "PERSON_ROLE":
            what_to_check = f"Look for the official personnel directory, current leadership page, or recent verified press releases regarding {subject}."
            if claim.currentness_required:
                what_confirms = f"The official source lists {subject} as currently holding the role, with no recent announcements of them stepping down."
                what_refutes = f"The official source lists someone else in the role, or lists {subject} as 'former' or deceased."
        elif claim.claim_type == "LOCATION":
            what_to_check = f"Look for the 'Contact Us' or official address page of {subject}."
            what_confirms = f"The official address exactly matches the location in the claim."
            what_refutes = f"The official address points to a different city/country."
            
        return VerificationRecommendation(
            source_type=source_type,
            target_domain=target_domain,
            queries=strategy.get("primary_queries", []),
            what_to_check=what_to_check,
            what_confirms=what_confirms,
            what_refutes=what_refutes
        )

recommendation_engine = RecommendationEngine()
