"""
Benchmarks a running TruthLens server against a labelled claim set.

Verdicts are collapsed to the 3 FEVER-style classes:
    TRUE  = SUPPORTED, SUPPORTED_HISTORICALLY
    FALSE = REFUTED, OUTDATED
    NEI   = INSUFFICIENT_EVIDENCE, CONFLICTING   ("not enough info")

Usage:
    python backend/evaluation/run_benchmark.py --url http://127.0.0.1:8077 \
        [--dataset backend/evaluation/datasets/fever_dev_sample.jsonl] [--limit 50] [--seed 42] \
        [--provider offline|auto|gemini|groq|openai]

Datasets: .jsonl or .json (list) rows with "claim" and "label" (TRUE/FALSE/NEI; FEVER labels also accepted).
Writes backend/evaluation/results/<UTC timestamp>-<requested provider>-<judge>-<dataset>.json with every prediction.
"""
import argparse
import json
import random
import re
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLASSES = ["TRUE", "FALSE", "NEI"]
VERDICT_TO_CLASS = {
    "SUPPORTED": "TRUE", "SUPPORTED_HISTORICALLY": "TRUE",
    "REFUTED": "FALSE", "OUTDATED": "FALSE",
    "INSUFFICIENT_EVIDENCE": "NEI", "CONFLICTING": "NEI",
}
LABEL_ALIASES = {"SUPPORTS": "TRUE", "REFUTES": "FALSE", "NOT ENOUGH INFO": "NEI"}


def load_dataset(path: Path):
    text = path.read_text(encoding="utf-8")
    rows = json.loads(text) if path.suffix == ".json" else [json.loads(l) for l in text.splitlines() if l.strip()]
    out = []
    for r in rows:
        label = str(r["label"]).upper()
        label = LABEL_ALIASES.get(label, label)
        if label not in CLASSES:
            raise ValueError(f"Unknown label {r['label']!r} for claim {r['claim']!r}")
        out.append({**r, "label": label})
    return out


def verify(url: str, claim: str, provider: str):
    req = urllib.request.Request(
        f"{url.rstrip('/')}/api/verify",
        data=json.dumps({"claim": claim, "llm_provider": provider}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def report(rows):
    """Accuracy, per-class precision/recall/F1, confusion matrix (rows = gold, cols = predicted)."""
    scored = [r for r in rows if r["predicted"] in CLASSES]
    matrix = {g: {p: 0 for p in CLASSES} for g in CLASSES}
    for r in scored:
        matrix[r["label"]][r["predicted"]] += 1
    correct = sum(matrix[c][c] for c in CLASSES)
    per_class = {}
    for c in CLASSES:
        tp = matrix[c][c]
        pred = sum(matrix[g][c] for g in CLASSES)
        gold = sum(matrix[c].values())
        p = tp / pred if pred else 0.0
        rcl = tp / gold if gold else 0.0
        per_class[c] = {"precision": round(p, 3), "recall": round(rcl, 3),
                        "f1": round(2 * p * rcl / (p + rcl), 3) if p + rcl else 0.0, "support": gold}
    latencies = [r["latency_s"] for r in scored]
    return {
        "n": len(rows), "errors": len(rows) - len(scored),
        "accuracy": round(correct / len(scored), 4) if scored else 0.0,
        "macro_f1": round(sum(v["f1"] for v in per_class.values()) / len(CLASSES), 4),
        "per_class": per_class, "confusion_matrix": matrix,
        "mean_latency_s": round(sum(latencies) / len(latencies), 2) if latencies else None,
    }


def print_report(m, judge, dataset):
    print(f"\n=== {dataset} | judge: {judge} | n={m['n']} (errors: {m['errors']}) ===")
    print(f"Accuracy: {m['accuracy'] * 100:.1f}%   Macro-F1: {m['macro_f1']:.3f}   Mean latency: {m['mean_latency_s']}s")
    print(f"{'class':6} {'prec':>6} {'recall':>7} {'f1':>6} {'support':>8}")
    for c, v in m["per_class"].items():
        print(f"{c:6} {v['precision']:6.3f} {v['recall']:7.3f} {v['f1']:6.3f} {v['support']:8}")
    print("Confusion matrix (rows = gold, cols = predicted):")
    print(f"{'':8}" + "".join(f"{c:>7}" for c in CLASSES))
    for g in CLASSES:
        print(f"{g:8}" + "".join(f"{m['confusion_matrix'][g][p]:7}" for p in CLASSES))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8077")
    ap.add_argument("--dataset", default=str(HERE / "datasets" / "fever_dev_sample.jsonl"))
    ap.add_argument("--limit", type=int, help="evaluate a seeded random subset of this size")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--provider", default="offline")
    args = ap.parse_args()

    dataset = Path(args.dataset)
    rows = load_dataset(dataset)
    if args.limit and args.limit < len(rows):
        rows = random.Random(args.seed).sample(rows, args.limit)

    results, judges = [], Counter()
    started = time.time()
    for i, row in enumerate(rows, 1):
        t = time.time()
        try:
            d = verify(args.url, row["claim"], args.provider)
            verdict, judge = d["verdict"], d.get("llm_provider_used", "?")
            predicted = VERDICT_TO_CLASS.get(verdict, "ERROR")
            judges[judge] += 1
        except Exception as e:
            verdict, judge, predicted = f"ERROR: {e}", None, "ERROR"
        latency = round(time.time() - t, 2)
        mark = "OK " if predicted == row["label"] else "-- "
        print(f"[{i:3}/{len(rows)}] {mark}gold={row['label']:5} pred={predicted:5} ({verdict}) {latency:5.1f}s  {row['claim'][:90]}")
        results.append({"claim": row["claim"], "label": row["label"], "verdict": verdict,
                        "predicted": predicted, "judge": judge, "latency_s": latency})

    metrics = report(results)
    judge = judges.most_common(1)[0][0] if judges else "none"
    print_report(metrics, judge, dataset.name)

    # Say loudly when the requested judge is not the one that answered (e.g. cloud quota exhausted -> offline)
    # ("None (no evidence)" is not a judge: nothing was retrieved, so no judge ran)
    real_judges = {j: n for j, n in judges.items() if not j.startswith("None")}
    if len(real_judges) > 1 or (args.provider not in ("auto", "offline") and args.provider not in judge.lower()):
        print(f"\nWARNING: requested provider '{args.provider}' but answers came from: {dict(judges)}")

    slug = re.sub(r"[^a-z0-9]+", "-", judge.lower()).strip("-")[:40]
    # Timestamp + requested provider in the name so concurrent or repeated runs never overwrite each other
    out = HERE / "results" / f"{datetime.now(timezone.utc):%Y-%m-%dT%H%M%S}-{args.provider}-{slug}-{dataset.stem}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "dataset": str(dataset.relative_to(HERE.parent.parent)) if dataset.is_relative_to(HERE.parent.parent) else str(dataset),
        "limit": args.limit, "seed": args.seed, "provider_requested": args.provider, "judge": judge,
        "judges_used": dict(judges),
        "server": args.url, "run_at": datetime.now(timezone.utc).isoformat(),
        "wall_time_s": round(time.time() - started, 1), "metrics": metrics, "predictions": results,
    }, indent=2, ensure_ascii=False))
    print(f"\nSaved {out}")
    return 0 if metrics["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
