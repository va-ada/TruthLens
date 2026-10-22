# Verification Engine

How `POST /api/verify` turns a claim into a verdict. Entry point:
`backend/services/orchestration/verification_orchestrator.py`.

## Pipeline

1. **Claim parser** (`claim_parser.py`): whole-word rules classify the claim (`PERSON_ROLE`, `LOCATION`,
   `SCIENTIFIC`, `STATISTICAL`, `HISTORICAL_FACT`, `AMBIGUOUS`), find the subject and role, and decide whether
   it is **historical** (past tense or a past year) or needs **current** evidence ("current", "now", "today").
2. **Source planner** (`source_planner.py`) picks support queries and **contradiction queries**, for example
   `"<person> former <role>"`, `"<topic> myth misconception"`, plus a freshness window.
3. **Evidence retriever** (`evidence_retriever.py`, `live_search_service.py`) runs the queries against the local
   ChromaDB vault (seed dossiers, uploads, news) and live Wikipedia:
   - an exact-title lookup for names in the claim, up to 4 searches and up to 6 article extracts (≤ 11 requests
     per claim), split into 3-sentence passages, keeping each article's opening plus its most claim-relevant passages;
   - at most 4 Wikipedia requests in flight per process, one retry on timeout/429/5xx, and a 6-hour response cache;
   - failed requests are reported under `limitations` instead of silently looking like "no evidence".

   Results are deduplicated and reranked with the MS-MARCO cross-encoder.
4. **Judge** (`llm_service.py`):
   - **Cloud LLM** if a key is configured: Gemini first, then fallback Gemini models, then Groq or OpenAI.
     Overloads are retried once and rate limits move to the next model. The judge returns per-passage stances
     as JSON.
   - **Offline**: `cross-encoder/nli-deberta-v3-base` NLI (`nlp/nli_evaluator.py`), scored per sentence window.
     - A contradiction only counts if the sentence covers ≥ 50% of the claim's key terms. Otherwise NLI labels
       unrelated sentences as contradictions.
     - "It is a myth that X" counts **against** X. "It was claimed that X" counts as neither side.
     - Date ranges: "X was president in 2023" against "served 2021–2025" checks whether the year falls in the range.
     - OUTDATED: a present-tense role claim that is refuted, while its past-tense form is entailed.
   - If a configured cloud judge fails, the offline judge runs and the response says so under `limitations`.
5. **Policy engine** (`policy_engine.py`) applies deterministic guardrails. They only ever make a verdict more cautious:
   - Every verdict must be backed by at least one passage on its side.
   - A support verdict needs evidence that names the claim's subject.
   - A present-tense claim needs supporting evidence dated within the freshness window.
   - The engine never converts a supported REFUTED verdict into "insufficient".
6. **Aggregation** (`verdict_aggregator.py`) gives one vote per independent source, weighted by stance
   probability × source credibility. It produces confidence, agreement and strength (formula in the module
   docstring). INSUFFICIENT_EVIDENCE always has confidence 0.
7. **Recommendation engine** tells the user where and how to check the claim themselves.

## Verdicts

| Verdict | Meaning |
|---|---|
| `SUPPORTED` | Evidence confirms the claim is true now |
| `SUPPORTED_HISTORICALLY` | A past-tense claim, confirmed for that time |
| `OUTDATED` | Claims a present fact that only held in the past |
| `REFUTED` | Evidence contradicts the claim |
| `CONFLICTING` | Credible sources on both sides, no 2:1 winner |
| `INSUFFICIENT_EVIDENCE` | Evidence doesn't settle it (confidence 0) |

Older spellings (`SUPPORTED_CURRENT`, `VERIFIED`, `CONTRADICTED`, …) are mapped by `schemas.normalize_verdict`.

## Known limitations

- The offline NLI reads text literally. It misses paraphrases ("viral" vs "viruses") and can't do arithmetic
  beyond the year-range rule.
- Namesakes: pages about different people with the same name ("Ian Brennan, music producer") can count as
  contradicting evidence. A predicate-overlap filter was tried and reverted because it dropped real
  contradictions (FEVER 56.7% → 53.3%).
- "A film" / existential claims: a different film by the same director can read as a contradiction.
- Retrieval sometimes finds only tangential passages. The verdict is then honestly INSUFFICIENT_EVIDENCE.
- Wikipedia's "last edited" timestamp is used as a freshness signal. It shows the page is maintained, not that
  every sentence is current.
- See `backend/evaluation/` for measured accuracy.
