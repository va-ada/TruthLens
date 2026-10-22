from enum import Enum
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any


class Verdict(str, Enum):
    """The single verdict vocabulary used by judge, policy engine, API, DB, UI and benchmark."""
    SUPPORTED = "SUPPORTED"                            # evidence confirms the claim (currently true)
    SUPPORTED_HISTORICALLY = "SUPPORTED_HISTORICALLY"  # claim is about the past and evidence confirms it
    OUTDATED = "OUTDATED"                              # claim asserts a present state that only held in the past
    REFUTED = "REFUTED"                                # evidence contradicts the claim
    CONFLICTING = "CONFLICTING"                        # credible evidence on both sides, no clear winner
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"    # not enough relevant evidence to decide


# Legacy / LLM-variant names -> canonical verdict. Anything unknown becomes INSUFFICIENT_EVIDENCE.
_VERDICT_ALIASES = {
    "SUPPORTED_CURRENT": Verdict.SUPPORTED,
    "VERIFIED": Verdict.SUPPORTED,
    "TRUE": Verdict.SUPPORTED,
    "HISTORICAL SUPPORT ONLY": Verdict.SUPPORTED_HISTORICALLY,
    "CONTRADICTED": Verdict.REFUTED,
    "FALSE": Verdict.REFUTED,
    "CONFLICTING EVIDENCE": Verdict.CONFLICTING,
    "MISLEADING": Verdict.CONFLICTING,
    "INSUFFICIENT EVIDENCE": Verdict.INSUFFICIENT_EVIDENCE,
    "AMBIGUOUS_TIME_CONTEXT": Verdict.INSUFFICIENT_EVIDENCE,
    "AMBIGUOUS TIME CONTEXT": Verdict.INSUFFICIENT_EVIDENCE,
    "CURRENT STATUS UNVERIFIED": Verdict.INSUFFICIENT_EVIDENCE,
    "AMBIGUOUS": Verdict.INSUFFICIENT_EVIDENCE,
}


def normalize_verdict(value: Optional[str]) -> str:
    """Maps any verdict spelling (old taxonomy, LLM output) onto the canonical Verdict values."""
    key = (value or "").strip().upper().replace("-", "_")
    if key in Verdict.__members__:
        return Verdict[key].value
    alias = _VERDICT_ALIASES.get(key) or _VERDICT_ALIASES.get(key.replace("_", " "))
    return (alias or Verdict.INSUFFICIENT_EVIDENCE).value


def normalize_credibility(value: Any, default: float = 0.70) -> float:
    """Credibility is always 0-1 inside the app; tolerate 0-100 inputs from older code paths."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v > 1.0:
        v = v / 100.0
    return max(0.0, min(1.0, v))

class EvidenceChunk(BaseModel):
    id: str = Field(default_factory=lambda: "")
    chunk_id: str = Field(default_factory=lambda: "")
    document_name: str = ""
    source: str = ""
    source_type: str = "General"
    url: Optional[str] = None
    page_number: Optional[int] = 1
    text: str = ""
    text_excerpt: str = ""
    relevance_score: float = 0.0
    stance: str = "NEUTRAL"
    stance_score: float = 0.0  # probability the judge assigned to this stance (0-1)
    rationale: str = ""
    credibility_score: float = 0.70
    publication_date: Optional[str] = None
    retrieval_date: Optional[str] = None
    updated_at: Optional[str] = None
    authority: str = "Unverified"
    primary_or_secondary: str = "Secondary"
    publisher: Optional[str] = None
    entity_match: Optional[str] = None
    temporal_match: Optional[str] = None
    claim_relation: Optional[str] = None
    support_type: Optional[str] = None

class StructuredClaim(BaseModel):
    original_claim: str
    subject: Optional[str] = None
    predicate: Optional[str] = None
    object_entity: Optional[str] = None
    entities: List[str] = []
    country: Optional[str] = None
    organization: Optional[str] = None
    role: Optional[str] = None
    location: Optional[str] = None
    time_expression: Optional[str] = None
    claim_type: str = "AMBIGUOUS"
    currentness_required: bool = False
    historical: bool = False

class VerificationRecommendation(BaseModel):
    source_type: str
    target_domain: str
    queries: List[str] = []
    what_to_check: str
    what_confirms: str
    what_refutes: str

class ClaimVerificationRequest(BaseModel):
    claim: str = Field(..., min_length=3, max_length=2000, description="The claim or headline to verify")
    context_text: Optional[str] = Field(None, description="Direct article context provided by a client app (like Echo News) to improve accuracy")
    llm_provider: Optional[str] = Field("auto", description="auto, gemini, groq, openai, ollama, offline")
    api_key: Optional[str] = Field(None, description="Optional custom API key for this request")
    confidence_threshold: Optional[float] = Field(0.5, ge=0.0, le=1.0)
    top_k: Optional[int] = Field(8, ge=1, le=20)

    @field_validator("claim")
    @classmethod
    def claim_must_be_a_statement(cls, v: str) -> str:
        # "Earth" or "Modi" is a topic, not a checkable statement; judges happily "support" topics
        if len(v.split()) < 3:
            raise ValueError("Please enter a full statement to check, e.g. 'Earth is the third planet from the Sun'.")
        return v

class SimilarClaim(BaseModel):
    id: str
    claim: str
    verdict: str
    confidence_score: float
    timestamp: str
    similarity_score: float

class VerificationResponse(BaseModel):
    id: str
    claim: str
    claim_type: str = "AMBIGUOUS"
    verdict: str  # one of Verdict
    confidence_score: float  # 0-100, see verdict_aggregator for the formula
    verification_strength: str = "Insufficient" # Strong, Moderate, Weak, Insufficient
    explanation: str
    reason: str = ""
    key_reasoning: str
    entity_analysis: Dict[str, Any] = {}
    temporal_analysis: Dict[str, Any] = {}
    supporting_evidence: List[EvidenceChunk] = []
    contradicting_evidence: List[EvidenceChunk] = []
    neutral_evidence: List[EvidenceChunk] = []
    retrieved_sources: List[Dict[str, Any]] = []
    source_credibility_score: float = 0.0 
    evidence_agreement_score: float = 0.0 
    agreement_analysis: str = ""
    similar_claim_found: Optional[SimilarClaim] = None
    verification_recommendation: Optional[VerificationRecommendation] = None
    retrieved_at: Optional[str] = None
    limitations: List[str] = []
    entity_match: Optional[str] = None
    temporal_match: Optional[str] = None
    country_match: Optional[str] = None
    role_match: Optional[str] = None
    llm_provider_used: str = "orchestrator"
    cached: bool = False  # True when served from the repeated-claim cache
    timestamp: str

class DocumentItem(BaseModel):
    id: str
    filename: str
    source: str
    title: Optional[str] = None
    source_type: str
    file_type: str
    upload_date: str
    created_at: Optional[str] = None
    number_of_chunks: int
    chunks_count: Optional[int] = None
    processing_status: str

    def __init__(self, **data):
        if "title" not in data or not data["title"]:
            data["title"] = data.get("source") or data.get("filename", "Untitled")
        if "chunks_count" not in data or data["chunks_count"] is None:
            data["chunks_count"] = data.get("number_of_chunks", 0)
        if "created_at" not in data or not data["created_at"]:
            data["created_at"] = data.get("upload_date", "")
        super().__init__(**data)

class AnalyticsData(BaseModel):
    total_claims_verified: int
    verdict_counts: Dict[str, int]
    average_confidence: float
    average_source_credibility: float
    total_documents: int
    total_chunks: int
    top_sources: List[Dict[str, Any]]


class FeedbackRequest(BaseModel):
    """A user's report that a verdict looks wrong."""
    verification_id: str = Field(..., min_length=1, max_length=64)
    claim: str = Field(..., min_length=3, max_length=2000)
    verdict: str = Field(..., min_length=1, max_length=64)
    suggested_verdict: Optional[str] = None
    comment: Optional[str] = Field(None, max_length=1000)

    @field_validator("suggested_verdict")
    @classmethod
    def suggested_must_be_canonical(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        if v not in Verdict.__members__:
            raise ValueError(f"suggested_verdict must be one of: {', '.join(Verdict.__members__)}")
        return v
