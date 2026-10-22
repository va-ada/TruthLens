from typing import List, Dict, Any
import numpy as np
from backend.services.ml_runtime import MODEL_LOCK

class LocalReranker:
    _instance = None
    _model = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LocalReranker, cls).__new__(cls)
        return cls._instance

    def _load_model(self):
        with MODEL_LOCK:
            self._load_model_locked()

    def _load_model_locked(self):
        if self._model is None:
            import time
            
            for attempt in range(3):
                try:
                    from sentence_transformers.cross_encoder import CrossEncoder
                    print(f"[LocalReranker] Loading Re-ranker (Attempt {attempt+1}/3)...")
                    try:
                        self._model = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2', local_files_only=True)
                    except Exception:
                        self._model = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
                    print("[LocalReranker] Re-ranker loaded successfully.")
                    return
                except ImportError:
                    print("[LocalReranker] sentence_transformers not installed. Falling back.")
                    break
                except Exception as e:
                    print(f"[LocalReranker] Error loading re-ranker model: {e}")
                    time.sleep(1)
            
            print("[LocalReranker] Failed to load Re-ranker. Using fallback.")
            self._model = "fallback"

    def rerank(self, query: str, chunks: List[Dict[str, Any]], top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Re-ranks a list of chunks based on cross-encoder similarity with the query.
        """
        if not chunks:
            return []
            
        self._load_model()
        
        if self._model == "fallback":
            # Fallback to existing sort order or BM25
            return sorted(chunks, key=lambda x: x.get('relevance_score', 0), reverse=True)[:top_k]
            
        try:
            pairs = [[query, c.get("text", "")] for c in chunks]
            with MODEL_LOCK:
                scores = self._model.predict(pairs, show_progress_bar=False)
            
            for i, chunk in enumerate(chunks):
                chunk["relevance_score"] = float(scores[i])
                # Optionally normalize scores to 0-1 range
                # However ms-marco raw logits are fine for sorting
                
            sorted_chunks = sorted(chunks, key=lambda x: x.get("relevance_score", -999.0), reverse=True)
            return sorted_chunks[:top_k]
            
        except Exception as e:
            print(f"[LocalReranker] Re-ranking failed: {e}")
            return chunks[:top_k]

local_reranker = LocalReranker()
