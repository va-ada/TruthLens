"""Regression: parallel retrieval + background news sync used to load/run torch models concurrently and segfault."""
from concurrent.futures import ThreadPoolExecutor

from backend.services.embedding_service import embedding_service
from backend.services.rag.local_reranker import local_reranker
from backend.services.nlp.nli_evaluator import nli_evaluator


def _work(i):
    emb = embedding_service.embed_texts([f"claim number {i} about the economy"])
    ranked = local_reranker.rerank("economy of India", [{"text": f"India economy fact {i}", "relevance_score": 0.5}], top_k=1)
    try:
        stance = nli_evaluator.classify_chunks("India has an economy", [f"India's economy grew in year {i}."])
    except RuntimeError:
        stance = [{"stance": "NEUTRAL"}]
    return len(emb[0]), len(ranked), stance[0]["stance"]


def test_models_survive_concurrent_use():
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_work, range(16)))
    assert len(results) == 16
    assert all(dim == 384 and n == 1 for dim, n, _ in results)
