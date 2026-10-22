# TruthLens Accuracy Root-Cause Analysis

## 1. Temporal Metadata Missing from Evidence
The core problem causing "SUPPORTED CURRENT" verdicts for historically true claims is that evidence chunks passed to the LLM (or NLI engine) lack explicit temporal metadata. 
- The `RetrievalService` does not extract or index `publication_date`, `valid_from`, or `event_date`. 
- The LLM prompt tries to reason about time, but because the evidence text itself often doesn't contain a date (e.g. "Shinzo Abe is the Prime Minister of Japan"), the LLM assumes the text represents the current state of the world.

## 2. Inadequate Freshness Prioritization
When a claim asks about the "current" status, the system simply retrieves the most semantically similar chunks from ChromaDB or Wikipedia. If an old document is highly semantically similar, it will be ranked first. There is no filter or weight for "freshness" in the cross-encoder or vector search.

## 3. Entity and Role Mismatch in the Offline NLI Engine
The offline NLI engine (`_offline_nli_verify` in `llm_service.py`) uses a basic keyword overlap and proximity heuristic to determine if a chunk supports a claim. 
- It checks if `subject_tokens` and `role_predicate_tokens` match.
- If the claim is "Shinzo Abe is the current PM of India" and the chunk says "Shinzo Abe is the PM of Japan", the NLI engine might see "Shinzo Abe", "PM", and determine it's a match, completely ignoring the country mismatch ("India" vs "Japan").
- Furthermore, the offline engine lacks a structured entity-extraction pipeline, making it incapable of distinguishing between Person, Role, and Country.

## 4. Fake "Agreement" and "Confidence" Scores
In `verification_service.py`, the confidence score and agreement scores are calculated based purely on the number of chunks that matched the claim (e.g., if 2 out of 3 chunks are classified as "SUPPORTING", the agreement is high). 
- If the retrieval service pulls 3 identical copies of the same outdated news article, the system will report "100% Agreement" and very high confidence, misleading the user.
- The confidence score mixes "relevance", "credibility", and a hardcoded base score, producing a falsely precise number (e.g., 93.9%) that has no statistical calibration.

## 5. Live Search Does Not Track Retrieval Dates properly
`live_search_service.py` fetches Wikipedia extracts and appends a `[Source Last Updated: <timestamp>]` to the end of the text. However, this is just a string append, not a structured metadata field. It also doesn't track the *retrieval* date.

## Fix Plan
1. **Schema Update**: Add strict temporal and entity fields to the data model (`EvidenceChunk`).
2. **Metadata Enrichment**: Update `retrieval_service.py` to index and retrieve date fields.
3. **Structured Orchestrator**: Update `agent_orchestrator.py` to explicitly perform Entity Extraction, Country Matching, and Temporal Context Analysis before producing a verdict.
4. **LLM Prompt Improvement**: Force the LLM to output explicit dates and entity matches, rather than just a verdict string.
5. **Score Calibration**: Remove fake precision from confidence scores; replace them with evidence-based bands (e.g., "High", "Medium", "Low") or a transparent formula based on source independence and freshness.
6. **Verdict Engine**: Implement a deterministic ruleset in `agent_orchestrator.py` that overrides the LLM if current evidence is not fresh enough for a current claim.
