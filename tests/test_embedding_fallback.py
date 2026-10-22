import subprocess
import sys
from pathlib import Path

from backend.services.embedding_service import embedding_service

ROOT = Path(__file__).resolve().parent.parent


def test_fallback_embedding_is_stable_across_processes():
    code = ("from backend.services.embedding_service import embedding_service as e;"
            "print(round(sum(v*(i+1) for i, v in enumerate(e._fallback_embed('antibiotics cure flu'))), 6))")
    runs = {subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True).stdout.strip().splitlines()[-1]
            for _ in range(2)}
    assert len(runs) == 1


def test_fallback_embedding_is_unit_length():
    v = embedding_service._fallback_embed("the moon is made of cheese")
    assert abs(sum(x * x for x in v) - 1.0) < 1e-5 and len(v) == 384
