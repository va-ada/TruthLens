from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any

from backend.services.retrieval_service import retrieval_service
from backend.services.live_search_service import live_search_service
from backend.services.nlp.nli_evaluator import content_words
from backend.config import RETRIEVAL_TOP_K

MAX_LIVE_QUERIES = 4          # claim + planned queries, each a Wikipedia search
IRRELEVANT_LOGIT = -8.0       # MS-MARCO logit below which a chunk is noise, unless it shares claim terms


class EvidenceRetriever:
    def retrieve(self, claim: str, strategy: dict, top_k: int = 8) -> List[Dict[str, Any]]:
        """
        Multi-query retrieval: the claim itself, the source planner's primary queries (support) and
        its contradiction queries, from the local vector store and live Wikipedia, in parallel.
        """
        support_queries = self._dedupe([claim] + strategy.get("primary_queries", []))
        contra_queries = self._dedupe(strategy.get("contradiction_queries", []))

        jobs = []
        with ThreadPoolExecutor(max_workers=6) as pool:
            if strategy.get("search_local"):
                for q in support_queries[:2]:
                    jobs.append(pool.submit(retrieval_service.retrieve, q, RETRIEVAL_TOP_K))
            if strategy.get("search_live"):
                live = support_queries[:MAX_LIVE_QUERIES - min(1, len(contra_queries))]
                live += contra_queries[:MAX_LIVE_QUERIES - len(live)]
                tagged = [(q, "Potential Contradiction" if q in contra_queries else None) for q in live]
                # One bounded batch for all live queries (<= 11 Wikipedia requests per claim)
                live_failures: list = []
                jobs.append(pool.submit(live_search_service.fetch_for_queries, claim, tagged, failures=live_failures))
            evidence_chunks = []
            for job in jobs:
                try:
                    evidence_chunks.extend(job.result())
                except Exception as e:
                    print(f"[EvidenceRetriever] Retrieval job failed: {e}")

        if strategy.get("search_live") and live_failures:
            strategy.setdefault("retrieval_notes", []).append(
                f"Live Wikipedia search partly failed ({len(live_failures)} request(s) after retry); evidence may be incomplete.")

        # Deduplicate on normalised text (the same passage often comes back from several queries)
        seen, unique_chunks = set(), []
        for c in evidence_chunks:
            key = " ".join((c.get("text") or "").lower().split())
            if key and key not in seen:
                seen.add(key)
                unique_chunks.append(c)

        from backend.services.rag.local_reranker import local_reranker
        top_chunks = local_reranker.rerank(claim, unique_chunks, top_k=top_k)

        # Drop only clear noise: very low cross-encoder score AND no shared vocabulary with the claim.
        # (A flat "> -2" cut-off threw away every passage for simple claims like "the Earth orbits the Sun".)
        claim_terms = content_words(claim)
        return [c for c in top_chunks
                if c.get("relevance_score", 0.0) > IRRELEVANT_LOGIT or (claim_terms & content_words(c.get("text", "")))]

    @staticmethod
    def _dedupe(queries: List[str]) -> List[str]:
        out, seen = [], set()
        for q in queries:
            k = (q or "").strip().lower()
            if k and k not in seen:
                seen.add(k)
                out.append(q.strip())
        return out


evidence_retriever = EvidenceRetriever()
