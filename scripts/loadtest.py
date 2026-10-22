"""
Concurrency load test for /api/verify (stdlib only).

    python scripts/loadtest.py --url http://127.0.0.1:8090 --concurrency 10 --requests 40 [--provider offline]

Each simulated user has its own X-Client-Id and a distinct X-Forwarded-For (only honoured when the server runs
with TRUST_PROXY=1). Without TRUST_PROXY, every request comes from one IP and the per-IP rate limit applies, so
raise VERIFY_RATE_PER_MIN on the test server. Reports status codes, latency percentiles and throughput.
"""
import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

CLAIMS = [
    "Antibiotics can cure viral infections like the flu.",
    "Narendra Modi is the Prime Minister of India.",
    "The United Nations is headquartered in New York.",
    "India is the third largest economy in the world.",
    "Water boils at 100 degrees Celsius at sea level.",
    "The Eiffel Tower is located in Berlin.",
    "Shinzo Abe is the current Prime Minister of Japan.",
    "Mount Everest is the highest mountain on Earth.",
    "COVID-19 mRNA vaccines alter human DNA.",
    "The Great Wall of China is visible from the Moon with the naked eye.",
]


def one(url: str, i: int, provider: str, unique: bool):
    claim = CLAIMS[i % len(CLAIMS)]
    if unique:
        claim = f"{claim[:-1]} (check {i})."  # defeat the result cache
    body = json.dumps({"claim": claim, "llm_provider": provider}).encode()
    req = urllib.request.Request(f"{url}/api/verify", data=body, headers={
        "Content-Type": "application/json",
        "X-Client-Id": str(uuid.uuid4()),
        "X-Forwarded-For": f"203.0.113.{i % 250 + 1}",
    })
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.load(r)
            return r.status, time.time() - t, data.get("verdict"), data.get("cached", False)
    except urllib.error.HTTPError as e:
        return e.code, time.time() - t, None, False
    except Exception as e:
        return type(e).__name__, time.time() - t, None, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8090")
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--requests", type=int, default=40)
    ap.add_argument("--provider", default="offline")
    ap.add_argument("--unique", action="store_true", help="make every claim unique (no cache hits)")
    a = ap.parse_args()

    started = time.time()
    with ThreadPoolExecutor(max_workers=a.concurrency) as pool:
        results = list(pool.map(lambda i: one(a.url, i, a.provider, a.unique), range(a.requests)))
    wall = time.time() - started

    statuses = Counter(r[0] for r in results)
    ok = sorted(r[1] for r in results if r[0] == 200)
    print(f"requests={a.requests} concurrency={a.concurrency} provider={a.provider} unique={a.unique}")
    print(f"status codes: {dict(statuses)}")
    print(f"cache hits: {sum(1 for r in results if r[3])}")
    if ok:
        q = statistics.quantiles(ok, n=20) if len(ok) >= 2 else [ok[0]] * 19
        print(f"latency s: p50={statistics.median(ok):.1f} p95={q[18]:.1f} max={max(ok):.1f}")
    print(f"wall={wall:.1f}s throughput={len(ok) / wall:.2f} verified/s")
    return 0 if statuses.get(200, 0) == a.requests else 1


if __name__ == "__main__":
    raise SystemExit(main())
