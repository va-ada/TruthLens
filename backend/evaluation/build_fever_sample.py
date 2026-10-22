"""
Builds backend/evaluation/datasets/fever_dev_sample.jsonl: a seeded, label-stratified random sample of
the official FEVER 1.0 shared-task dev set (Thorne et al., 2018, "FEVER: a large-scale dataset for
Fact Extraction and VERification", NAACL). Source: https://fever.ai/download/fever/shared_task_dev.jsonl
License: CC BY-SA 3.0 (claims derived from Wikipedia).

Usage: python backend/evaluation/build_fever_sample.py [--per-label 50] [--seed 42] [--source FILE]
"""
import argparse
import json
import random
import urllib.request
from collections import defaultdict
from pathlib import Path

URL = "https://fever.ai/download/fever/shared_task_dev.jsonl"
LABEL_MAP = {"SUPPORTS": "TRUE", "REFUTES": "FALSE", "NOT ENOUGH INFO": "NEI"}
OUT = Path(__file__).resolve().parent / "datasets" / "fever_dev_sample.jsonl"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-label", type=int, default=50)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--source", help="local copy of shared_task_dev.jsonl (otherwise downloaded)")
    args = ap.parse_args()

    if args.source:
        lines = Path(args.source).read_text(encoding="utf-8").splitlines()
    else:
        with urllib.request.urlopen(URL, timeout=120) as r:
            lines = r.read().decode("utf-8").splitlines()

    by_label = defaultdict(list)
    for line in lines:
        row = json.loads(line)
        by_label[row["label"]].append(row)
    print({k: len(v) for k, v in by_label.items()}, "rows in source")

    rng = random.Random(args.seed)
    sample = []
    for label in sorted(by_label):
        for row in rng.sample(by_label[label], args.per_label):
            pages = sorted({ev[2] for group in row["evidence"] for ev in group if ev[2]})
            sample.append({"id": row["id"], "claim": row["claim"], "label": LABEL_MAP[label],
                           "fever_label": label, "wiki_pages": pages, "source": "FEVER 1.0 shared_task_dev"})
    rng.shuffle(sample)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for row in sample:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(sample)} claims to {OUT}")


if __name__ == "__main__":
    main()
