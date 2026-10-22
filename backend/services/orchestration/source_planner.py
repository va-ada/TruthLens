from backend.models.schemas import StructuredClaim


class SourcePlanner:
    def get_source_strategy(self, claim: StructuredClaim) -> dict:
        """
        Determines which sources would actually verify this claim, the queries that look for
        supporting evidence, and the queries that actively look for refuting evidence.
        """
        # Fall back to the whole claim when no subject could be parsed (avoids queries like "None current role")
        subject = claim.subject or claim.original_claim
        strategy = {
            "target_domains": [],
            "preferred_source_type": "Primary",
            "search_live": True,
            "search_local": True,
            "required_freshness_days": 365,
            "primary_queries": [],
            "contradiction_queries": []
        }

        if claim.claim_type == "PERSON_ROLE":
            strategy["preferred_source_type"] = "Government / Official"
            role = claim.role or "role"
            strategy["primary_queries"] = [f"{subject} {role}"]
            strategy["contradiction_queries"] = [f"{subject} former {role}", f"current {role} {claim.original_claim.split(' of ')[-1]}" if " of " in claim.original_claim else f"{subject} replaced"]
            if claim.currentness_required:
                strategy["required_freshness_days"] = 90

        elif claim.claim_type == "LOCATION":
            strategy["preferred_source_type"] = "Official Website / Directory"
            strategy["primary_queries"] = [f"{subject} location address"]
            strategy["contradiction_queries"] = [f"{subject} headquarters"]
            strategy["target_domains"] = [".edu", ".gov", ".org"]

        elif claim.claim_type == "SCIENTIFIC":
            strategy["preferred_source_type"] = "Peer Reviewed / Medical"
            strategy["primary_queries"] = [subject]
            strategy["contradiction_queries"] = [f"{subject} myth misconception"]

        elif claim.claim_type == "STATISTICAL":
            strategy["preferred_source_type"] = "Original Publisher / Dataset"
            strategy["primary_queries"] = [subject]
            strategy["contradiction_queries"] = [f"{subject} statistics ranking"]

        else:
            strategy["preferred_source_type"] = "Reputable Secondary"
            strategy["primary_queries"] = [subject]

        return strategy


source_planner = SourcePlanner()
