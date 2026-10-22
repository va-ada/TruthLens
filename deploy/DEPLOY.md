# Deploying TruthLens

Target: one Linux server (any VPS or cloud VM) running Docker, with Caddy providing HTTPS.
Measured footprint: ~0.8 GB RAM with all three local models loaded and ~4 GB disk for the image.

## 1. Server

| | Minimum | Recommended |
|---|---|---|
| CPU | 2 vCPU | 4 vCPU (the offline judge is CPU-bound) |
| RAM | 2 GB | 4 GB |
| Disk | 15 GB | 25 GB (image + backups) |
| OS | Ubuntu 22.04/24.04 or Debian 12 with Docker Engine + compose plugin | |

Open inbound ports **80 and 443** only (SSH as you normally would).

## 2. DNS

Create an `A` record (and `AAAA` if you have IPv6) for your domain, e.g. `truthlens.example.com`, pointing to the
server. Caddy requests the certificate on first start, so DNS must resolve first.

## 3. Configure

```bash
git clone <your repo> truthlens && cd truthlens
cp .env.example .env
```
Edit `.env`:

| Variable | Value |
|---|---|
| `DOMAIN` | `truthlens.example.com` |
| `ADMIN_TOKEN` | a long random string: `openssl rand -hex 24` (startup refuses anything < 16 chars in production) |
| `GEMINI_API_KEY` | optional; without it the offline NLI judge is used |
| `GEMINI_MODEL` / `GEMINI_FALLBACK_MODELS` | defaults are `gemini-2.5-flash` → lite → latest → 3.5 (older models are more reliable) |
| `LLM_DAILY_BUDGET` | cap on cloud-judge calls per day (protects your API bill / free-tier quota) |
| `VERIFY_RATE_PER_MIN` | per-IP verification limit (default 10) |
| `HISTORY_RETENTION_DAYS` | how long users' private history is kept (default 30) |

## 4. Start

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps      # both "healthy"/"running"
curl -s https://truthlens.example.com/health
```
The first build takes ~10 minutes (wheels + models). After that, starts take seconds.

## 5. Verify the deployment

- `https://<domain>/` loads the app over HTTPS, and `http://` redirects to it.
- `/health` shows `"status": "healthy"` and the judge you expect.
- `https://<domain>/.env` and `/backend/config.py` return the app page, never the file.
- `/docs` returns 404 in production.
- Verifying the same claim 11 times in a minute returns HTTP 429 on the 11th.

## 6. Operations

| Task | Command |
|---|---|
| Logs | `docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f --tail 200` |
| Backup (safe while running) | `scripts/backup.sh /var/backups/truthlens` (keeps newest 14) |
| Nightly backup | `crontab -e` → `30 3 * * * cd /path/to/truthlens && scripts/backup.sh /var/backups/truthlens >> /var/log/truthlens-backup.log 2>&1` |
| Restore | `docker compose ... down && scripts/restore.sh backups/truthlens-<stamp>.tar.gz && docker compose ... up -d` |
| Update | `git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` |
| User feedback reports | `curl -H "X-Admin-Token: $ADMIN_TOKEN" https://<domain>/api/feedback` |

Copy backups off the server too (e.g. `rsync` to another machine or object storage). A backup that lives only
on the same disk does not protect against losing the server.

## 7. Capacity

Measured on a 10-core Apple-silicon laptop, inside Docker (CPU-only PyTorch), with the machine otherwise idle:

| Judge | Single claim | 10 concurrent users |
|---|---|---|
| Gemini (2.5-flash + fallbacks) | ~3–6 s | median 5.3 s, 20/20 succeeded |
| Offline NLI (DeBERTa-v3-base) | ~12 s (≈9 s of it serialised CPU) | median 92 s, 40/40 succeeded (before load shedding) |

- **Load shedding:** at most `MAX_CONCURRENT_VERIFICATIONS` (default 4) verifications run at once. Further
  requests get an immediate `503 "busy, retry in ~30 s"` instead of queueing for minutes. In offline mode the
  worst wait is therefore about 4 × 12 s.
- **Cloud quota is the real limit.** A free-tier Gemini key allowed only ~20 requests/day per model during
  testing. After that, the fallback models and then the (slower) offline judge take over. For real traffic, use
  a paid key and set `LLM_DAILY_BUDGET` to your spending limit.
- `NLI_MODEL=cross-encoder/nli-deberta-v3-small` is an option for small CPU-only servers: about 2× faster per
  sentence pair in a clean CPU benchmark (120 vs 242 ms at 4 threads), slightly less accurate (58.0% vs 60.0% FEVER
  under the same conditions). Base stays the default.


The app runs **one worker per container** by design: the rate limiter, result cache, LLM budget, Wikipedia
request cap and model lock all live in-process. Measure your own server with
`docker run --rm --network <project>_default -v "$PWD/scripts:/s:ro" python:3.12-slim python /s/loadtest.py --url http://truthlens:8000`.
For more traffic, run several containers behind the proxy and move the rate limiter and caches to Redis first.

## Not supported
Vercel / serverless: the offline judge needs PyTorch, which exceeds serverless size limits.
