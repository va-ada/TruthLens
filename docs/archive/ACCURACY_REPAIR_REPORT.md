# TruthLens Accuracy Repair Report
**Date**: September 27, 2026
**Target**: Temporal Fact-Checking, Entity Verification, and Confidence Score Calibration

## 1. Overview
The previous implementation of TruthLens suffered from three major accuracy flaws:
1. **Time-Blindness**: The retrieval system matched entities by name without considering the publication or event date, leading to "SUPPORTED CURRENT" verdicts for historically true claims.
2. **Entity Misalignment (Country/Role Mismatch)**: The offline NLI engine relied on basic keyword overlap. A claim about the "Prime Minister of India" could be validated by an article about the "Prime Minister of Japan" if the person's name matched.
3. **Fake Precision**: The `evidence_agreement_score` and `confidence_score` arbitrarily boosted numbers based on the *quantity* of retrieved chunks rather than independent sources, resulting in 100% agreement when duplicate chunks were loaded.

## 2. Implemented Fixes

### A. Deep Temporal Verification
- **Schema Update**: Extended `EvidenceChunk` to natively support `publication_date` and `retrieval_date`.
- **Live Search Enhancements**: Updated Wikipedia and DDG retrievers to explicitly attach a live `retrieval_date` timestamp and dynamically parse Wikipedia `timestamp` properties for the `publication_date`.
- **Prompt Injection**: The LLM prompt now injects the server's absolute `CURRENT REFERENCE DATE AND TIME` and maps `publication_date`/`retrieval_date` to every chunk, strictly instructing the model to reject stale evidence for current-status claims.

### B. Strict Entity & Country Alignment
- **New Extraction Fields**: Added `entity_match`, `temporal_match`, `country_match`, and `role_match` as mandatory structured output fields from the reasoning engine.
- **Vercel & Local Unification**: Refactored `AgentOrchestrator._judge_evaluate` to delegate all evaluations to `llm_service.verify_with_llm`. This ensures the same robust Entity and Temporal checks are run in Local offline mode (via the enhanced offline NLI or Ollama) as they are in Vercel Cloud (via Gemini 3.1 Pro).
- **Mismatch Detection**: The LLM prompt now includes explicit logic to enforce strict matching on Person, Role, and Country. A name match with a mismatched country now correctly triggers a "CONTRADICTED" or "INSUFFICIENT EVIDENCE" verdict.

### C. Calibrated Confidence Scoring
- **Independent Source Agreement**: The `evidence_agreement_score` calculation was rewritten to group chunks by independent `source`. The fake `(+2.5%)` duplicate-chunk multiplier was removed. 100% agreement now genuinely requires all independent retrieved sources to agree.
- **NLI Score Calibration**: The offline fallback NLI engine was adjusted to rely primarily on credibility and semantic relevance without arbitrary chunk-count boosting.

## 3. Results
TruthLens is now fully "Time-Aware". When a user asks "Who is the current Prime Minister of Japan", older articles mentioning Shinzo Abe are correctly flagged as `OUTDATED` rather than `SUPPORTED_CURRENT`. Entity overlap bugs (e.g., matching a Japanese Prime Minister to an Indian context) are trapped by the `country_match` and `role_match` validation layer.
