# Evidence Policy

## 1. Source credibility (0–1, used as a vote weight)

| Source | Credibility | Where set |
|---|---|---|
| Seed dossiers from official / intergovernmental pages (WHO, CDC, IMF, PMO India, UN…) | 0.95 | `Type:` header in `data/trusted_docs/*.txt` |
| Established news (RSS feeds) | 0.85–0.99 by feed | `news_sync_service.TRUSTED_RSS_FEEDS` |
| Wikipedia (live) | 0.80 | `live_search_service.py`, treated as an encyclopedia, not an official record |
| DuckDuckGo instant answer | 0.70 | `live_search_service.py` |
| Client-supplied article text (`context_text`) | 0.60 | orchestrator, since it is the claimant's own material |
| Uploaded documents | by filename/source keywords | `document_processor.detect_source_type` |

Every seed dossier section carries `Source`, `URL`, `Published`, `Retrieved` and `Type` lines, and those travel
with each passage into the evidence shown to the user. No invented report IDs.

## 2. Independence

Agreement counts **independent sources**, not passages. Several passages from one document are one vote, and
a single source triggers the limitation "corroboration not established".

## 3. Entity matching

Support requires that some evidence names the claim's subject. A contradiction from the offline judge must
cover at least half of the claim's key terms, so sentences about other people or topics are ignored.

## 4. Time

- Present-tense / "current" claims need supporting evidence dated within the claim type's freshness window
  (90 days for current office holders, 365 otherwise). Otherwise the verdict is INSUFFICIENT_EVIDENCE.
- A role claim refuted in the present but true in the past is OUTDATED.
- Claims with a year are checked against date ranges stated in the evidence.
