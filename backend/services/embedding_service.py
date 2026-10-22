import hashlib
import numpy as np
from typing import List, Union
from backend.config import EMBEDDING_MODEL_NAME
from backend.services.ml_runtime import MODEL_LOCK

class EmbeddingService:
    _instance = None
    _model = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EmbeddingService, cls).__new__(cls)
        return cls._instance

    def _load_model(self):
        with MODEL_LOCK:
            self._load_model_locked()

    def _load_model_locked(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                print(f"[EmbeddingService] Loading neural embedding model: {EMBEDDING_MODEL_NAME}...")
                try:
                    # Prefer locally cached weights first for instant, offline loading
                    self._model = SentenceTransformer(EMBEDDING_MODEL_NAME, local_files_only=True)
                except Exception:
                    self._model = SentenceTransformer(EMBEDDING_MODEL_NAME)
                print("[EmbeddingService] Neural embedding model loaded successfully.")
            except Exception as e:
                print(f"[EmbeddingService] Warning: Could not load sentence-transformers ({e}). Using robust fallback embedder.")
                self._model = "fallback"

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Converts a list of texts into vector embeddings."""
        if not texts:
            return []
            
        self._load_model()

        if self._model != "fallback":
            try:
                with MODEL_LOCK:
                    embeddings = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
                return embeddings.tolist()
            except Exception as e:
                print(f"[EmbeddingService] SentenceTransformer encode failed: {e}. Falling back.")

        # Robust Fallback Embedder using normalized character-n-gram/token hashing
        return [self._fallback_embed(t) for t in texts]

    def embed_query(self, query: str) -> List[float]:
        """Converts a single query string into an embedding vector."""
        return self.embed_texts([query])[0]

    def _fallback_embed(self, text: str, dim: int = 384) -> List[float]:
        """Deterministic 384-dimensional feature hash for testing or fallback."""
        vec = np.zeros(dim, dtype=np.float32)
        tokens = text.lower().split()
        for i, token in enumerate(tokens):
            # hashlib, not hash(): Python's hash() is randomised per process, so the same text got a
            # different vector in every worker and stored vectors never matched new queries
            idx = int.from_bytes(hashlib.md5(token.encode("utf-8")).digest()[:4], "little") % dim
            vec[idx] += 1.0 / (1.0 + (i * 0.05))
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    @staticmethod
    def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        """Calculates cosine similarity between two unit-normalized vectors."""
        v1 = np.array(vec1, dtype=np.float32)
        v2 = np.array(vec2, dtype=np.float32)
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(v1, v2) / (norm1 * norm2))

embedding_service = EmbeddingService()
