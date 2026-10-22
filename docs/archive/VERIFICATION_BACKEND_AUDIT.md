# Verification Backend Audit

## Current Architecture Flow
1. **Frontend Request**: The UI sends a claim string to `/api/verify`.
2. **Verification Service (`backend/services/verification_service.py`)**: Acts as a simple wrapper, taking the raw claim and passing it to the orchestrator.
3. **Agent Orchestrator (`backend/services/agents/agent_orchestrator.py`)**: 
   - Uses a primitive keyword-based heuristic to assign a domain ("politics", "science", "general").
   - Executes a generic retrieval pass fetching chunks from ChromaDB and Live Web (DuckDuckGo/Wikipedia).
   - Reranks chunks using a Cross-Encoder.
   - Passes the raw claim string and raw chunks to the `llm_service`.
4. **LLM Service (`backend/services/llm_service.py`)**:
   - Injects the raw string and all text chunks into a large prompt.
   - Relies on the LLM (or fallback keyword overlap algorithm) to guess the verdict and output a JSON.
5. **Score Calculation (`backend/services/verification_service.py`)**: Calculates confidence and agreement based on raw retrieved chunk properties.

## Root Causes of Failure
1. **No Structured Claim Representation**: The system never formally understands *what* the claim actually is (e.g., who is the subject, what is the role, is it a location claim, does it require current evidence?). It just passes raw strings to semantic search.
2. **Generic, Blind Retrieval**: It searches DuckDuckGo and Wikipedia generically for every claim. It does not map "ABC Institute location" to a targeted search of "site:abc.edu.in". Thus, Wikipedia articles matching keywords are retrieved instead of official primary sources.
3. **Lack of Claim-Specific Source Requirements**: A claim about a current office holder and a claim about a historical quote are treated exactly the same by the retrieval engine. It does not enforce that current office claims *require* official government/institutional sources.
4. **Fake Source Credibility**: Wikipedia is often arbitrarily assigned high credibility, leading the system to present it as an "official reference" when it is a secondary/encyclopedic source.
5. **One-Shot Verification (No Contradiction Search)**: The system fetches top-K semantic matches. If the top matches happen to support a false claim (due to semantic overlap), it never actively formulates a "contradiction query" to seek out refuting evidence.
6. **LLM Dependency for Verdicts**: The verdict is left to the LLM's raw generation rather than being explicitly computed through a deterministic policy (e.g., `IF entity_match AND temporal_match THEN Verified`).
7. **Useless Recommendations**: The system currently does not tell the user *how* to verify the claim themselves; it provides no exact search queries or target domains.

## Resolution Plan
Implement a `VerificationOrchestrator` that drives a structured pipeline:
1. **ClaimExtractor**: Parse raw text into a `StructuredClaim` (subject, role, temporal requirements).
2. **SourcePlanner**: Define the exact domain/source types needed (e.g., `.gov`, official website).
3. **EvidenceRetriever**: Execute multi-stage retrieval (Support + Contradiction queries).
4. **EvidenceValidator**: Deduplicate, extract temporal metadata, and match entities.
5. **PolicyEngine**: Compute final verdict deterministically from validated evidence.
6. **RecommendationEngine**: Generate explicit user-verification guidance.
