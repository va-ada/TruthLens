<div align="center">

# TruthLens
### Evidence-grounded, explainable fact checking

Paste a claim, a news link or a forwarded WhatsApp message. TruthLens retrieves evidence, judges each passage
for or against the claim, and returns a verdict that shows its sources, its reasoning and its uncertainty.

</div>

---

## What it does

1. **Understands the claim.** It recognises who/what the claim is about, whether it is a role, location,
   statistic or science claim, and whether it is about the past or needs *current* evidence.
2. **Retrieves evidence**, in parallel, from:
   - a local vault (ChromaDB) of sourced reference pages in `data/trusted_docs/`, plus uploaded documents and daily RSS news;
   - live Wikipedia.

   It runs support queries and **contradiction queries** ("<person> former <role>", "<topic> myth"), then
   reranks with a cross-encoder.
3. **Judges each passage** as supporting, contradicting or neutral, using either:
   - **Gemini** (or Groq / OpenAI), if a key is configured, with retries and fallback models; or
   - an **offline NLI model** (`cross-encoder/nli-deberta-v3-base`), with rules for off-topic sentences,
     "it's a myth that…" framing and date ranges.
4. **Applies guardrails and scores.**
   - Deterministic rules only make verdicts more cautious.
   - Confidence and agreement are computed per **independent source**, weighted by stance probability × source credibility.
5. **Explains.** The UI shows each passage's stance with the sentence that decided it, entity and time checks,
   limitations, and how to verify the claim yourself. Every verdict is labelled *AI-assisted*.

| Verdict | Meaning |
|---|---|
| `SUPPORTED` | Evidence confirms the claim is true now |
| `SUPPORTED_HISTORICALLY` | A past-tense claim, confirmed for that time |
| `OUTDATED` | Claims a present fact that only held in the past (e.g. a former office holder) |
| `REFUTED` | Evidence contradicts the claim |
| `CONFLICTING` | Credible sources disagree |
| `INSUFFICIENT_EVIDENCE` | The evidence doesn't settle it (confidence shown as "—") |

Design details: [`docs/VERIFICATION_ENGINE.md`](docs/VERIFICATION_ENGINE.md) · [`docs/EVIDENCE_POLICY.md`](docs/EVIDENCE_POLICY.md)

## Measured accuracy

Measured with `backend/evaluation/run_benchmark.py`. Verdicts are collapsed to FEVER's three classes
(TRUE / FALSE / NOT ENOUGH INFO); chance is 33%.

| Dataset | Judge | n | Accuracy | Macro-F1 |
|---|---|---|---|---|
| FEVER dev, seeded sample (`datasets/fever_dev_sample.jsonl`) | **Gemini** (2.5-flash → flash-lite fallback) | 50 | **76.0%** | 0.761 |
| FEVER dev, seeded sample | Offline NLI (DeBERTa-v3-base) | 150 | **62.7%** | 0.629 |
| Smoke set (`benchmark_dataset.json`) | Gemini 2.5-flash | 10 | 100% | — |
| Smoke set | Offline NLI | 10 | 70% | — |

For reference, the original engine scored 2/10 on its own smoke set. The offline judge's FEVER accuracy rose from
56.0% to 62.7% when live Wikipedia retrieval moved from page summaries to full-article passages. Runs vary by a
few claims because evidence comes from live Wikipedia. The main remaining offline error is true claims judged
NOT ENOUGH INFO (evidence not found or not recognised).

FEVER claims are written against 2017 Wikipedia, so some time-sensitive ones have since changed. Per-claim
results are in `backend/evaluation/results/`; dataset provenance is in `backend/evaluation/datasets/README.md`.

## Run it

### Production (HTTPS on a server)
`docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` puts Caddy (automatic HTTPS) in
front of the app with production settings, rate limits and load shedding. Step-by-step guide, server sizing,
backups and measured capacity: [`deploy/DEPLOY.md`](deploy/DEPLOY.md).

### Docker (local)
```bash
cp .env.example .env            # add GEMINI_API_KEY (optional) and ADMIN_TOKEN
docker compose up --build -d    # first build ~10 min; models are baked into the image
open http://127.0.0.1:8000      # or the TRUTHLENS_PORT you set in .env
```
See [`docs/DOCKER_SETUP.md`](docs/DOCKER_SETUP.md).

### Local (Python ≥ 3.12)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
uvicorn backend.main:app --port 8000
```
The first start downloads ~1 GB of models. `GET /health` shows which judge is active.

### Tests
```bash
pytest -q              # offline suite (no network, no API calls)
pytest -m network      # live Wikipedia integration tests
```

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/verify` | `{"claim": "...", "context_text"?: "...", "llm_provider"?: "auto\|gemini\|groq\|openai\|offline"}` → verdict, confidence, per-passage evidence with rationale, entity/temporal analysis, recommendation, limitations |
| `POST /api/news/extract-url` | Headline from a public news URL (internal/private addresses are refused) |
| `POST /api/news/clean-forward` | Strips "Forwarded / BREAKING / share to 10 groups" boilerplate from a message |
| `GET/DELETE /api/history`, `GET /api/analytics` | The caller's own past verifications (scoped by the browser's anonymous `X-Client-Id`; kept 30 days) |
| `POST /api/feedback` | "Report wrong verdict" (admin reads them with `GET /api/feedback`) |
| `POST /api/upload`, `DELETE /api/documents/{id}`, `POST /api/seed`, `POST /api/news/sync` | Admin actions (`X-Admin-Token` when `ADMIN_TOKEN` is set) |
| `GET /health` | Status, indexed chunks, active judge |

Interactive docs at `/docs`.

## Limitations

- Verdicts are AI-assisted and can be wrong. Check the cited sources before sharing.
- The offline judge reads text literally. It misses paraphrases and can't do arithmetic beyond year ranges.
  Gemini mode is more robust but needs a key and is subject to Google's rate limits and outages; each verdict
  says which judge ran.
- Evidence comes from the vault and Wikipedia. If neither covers a topic, the answer is INSUFFICIENT_EVIDENCE.
- A free-tier Gemini key allows only ~20 requests/day per model. After that the fallback models and then the
  offline judge answer, and the verdict says so. Use a paid key for real traffic.
- Offline judging is CPU-heavy (~12 s per claim). Beyond 4 concurrent checks, users get "busy, retry in 30 s".
- Vercel deployment is not supported in this version (see the Docker doc).

## License
MIT. See [LICENSE](LICENSE).
