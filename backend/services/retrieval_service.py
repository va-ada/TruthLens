import os
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from backend.config import (
    CHROMA_PERSIST_DIR, 
    CHROMA_COLLECTION_NAME, 
    RETRIEVAL_TOP_K, 
    SIMILARITY_THRESHOLD, 
    SOURCE_CREDIBILITY_WEIGHTS
)
from backend.services.embedding_service import embedding_service
from backend.models.schemas import normalize_credibility


def get_cred_score(source_type: str) -> float:
    """Credibility weight (0-1) for a source type when a chunk carries no explicit score."""
    st_lower = (source_type or "").lower()
    for key, weight in SOURCE_CREDIBILITY_WEIGHTS.items():
        if key in st_lower:
            return weight
    return 0.70

class RetrievalService:
    _instance = None
    _chroma_client = None
    _collection = None
    _memory_chunks = []  # Fallback in-memory index

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RetrievalService, cls).__new__(cls)
            cls._instance._init_chroma()
        return cls._instance

    def _init_chroma(self):
        try:
            import chromadb
            from chromadb.config import Settings
            
            CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
            self._chroma_client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
            self._collection = self._chroma_client.get_or_create_collection(
                name=CHROMA_COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"}
            )
            print(f"[RetrievalService] ChromaDB collection '{CHROMA_COLLECTION_NAME}' loaded. Items: {self._collection.count()}")
        except Exception as e:
            print(f"[RetrievalService] Warning: Could not initialize ChromaDB client ({e}). Using in-memory fallback store.")
            self._chroma_client = None
            self._collection = None

    def add_chunks(self, chunks: List[Dict[str, Any]]) -> int:
        """Embeds and indexes document chunks into the vector store."""
        if not chunks:
            return 0

        texts = [c["text"] for c in chunks]
        embeddings = embedding_service.embed_texts(texts)
        ids = [c["chunk_id"] for c in chunks]
        metadatas = [{
            "chunk_id": c["chunk_id"],
            "document_name": c["document_name"],
            "source": c["source"],
            "source_type": c.get("source_type", "General"),
            "page_number": int(c.get("page_number", 1)),
            # Chroma metadata cannot hold None; credibility is always stored on the 0-1 scale
            "url": c.get("url") or "",
            "publication_date": c.get("publication_date") or "",
            "retrieval_date": c.get("retrieval_date") or "",
            "credibility_score": normalize_credibility(c.get("credibility_score"), get_cred_score(c.get("source_type", "General")))
        } for c in chunks]

        # Try ChromaDB first
        if self._collection is not None:
            try:
                # Add in batches of 100 for stability
                batch_size = 100
                for i in range(0, len(ids), batch_size):
                    end = i + batch_size
                    self._collection.upsert(
                        ids=ids[i:end],
                        embeddings=embeddings[i:end],
                        documents=texts[i:end],
                        metadatas=metadatas[i:end]
                    )
                return len(chunks)
            except Exception as e:
                print(f"[RetrievalService] ChromaDB upsert failed: {e}. Indexing to in-memory store.")

        # Fallback to in-memory
        for i in range(len(chunks)):
            self._memory_chunks.append({
                "chunk_id": ids[i],
                "text": texts[i],
                "embedding": embeddings[i],
                "metadata": metadatas[i]
            })
        return len(chunks)

    def delete_document_chunks(self, document_name: str) -> int:
        """Deletes all chunks belonging to a specific document."""
        deleted_count = 0
        if self._collection is not None:
            try:
                results = self._collection.get(where={"document_name": document_name})
                if results and results["ids"]:
                    deleted_count = len(results["ids"])
                    self._collection.delete(ids=results["ids"])
            except Exception as e:
                print(f"[RetrievalService] ChromaDB delete error: {e}")

        # In-memory cleanup
        initial_len = len(self._memory_chunks)
        self._memory_chunks = [c for c in self._memory_chunks if c["metadata"]["document_name"] != document_name]
        deleted_count = max(deleted_count, initial_len - len(self._memory_chunks))
        return deleted_count

    def retrieve(self, query: str, top_k: int = RETRIEVAL_TOP_K) -> List[Dict[str, Any]]:
        """
        Retrieves top_k most semantically relevant chunks for a claim.
        Returns list of dicts with text, metadata, and relevance_score.
        """
        if not query or not query.strip():
            return []

        query_embedding = embedding_service.embed_query(query)

        # Query ChromaDB if active
        if self._collection is not None and self._collection.count() > 0:
            try:
                results = self._collection.query(
                    query_embeddings=[query_embedding],
                    n_results=min(top_k, self._collection.count()),
                    include=["documents", "metadatas", "distances"]
                )

                retrieved = []
                if results and results["ids"] and len(results["ids"][0]) > 0:
                    for idx in range(len(results["ids"][0])):
                        dist = results["distances"][0][idx] if "distances" in results else 0.5
                        # Cosine distance to similarity: sim = 1.0 - (dist / 2) or max(0, 1.0 - dist)
                        similarity = max(0.0, min(1.0, 1.0 - float(dist)))
                        
                        if similarity < SIMILARITY_THRESHOLD:
                            continue

                        meta = results["metadatas"][0][idx]
                        doc_text = results["documents"][0][idx]
                        
                        source_type = meta.get("source_type", "General")
                        cred_score = normalize_credibility(meta.get("credibility_score"), get_cred_score(source_type))

                        retrieved.append({
                            "chunk_id": meta.get("chunk_id", ""),
                            "document_name": meta.get("document_name", "Unknown"),
                            "source": meta.get("source", "Unknown"),
                            "source_type": source_type,
                            "page_number": int(meta.get("page_number", 1)),
                            "url": meta.get("url", ""),
                            "publication_date": meta.get("publication_date", ""),
                            "retrieval_date": meta.get("retrieval_date", ""),
                            "credibility_score": cred_score,
                            "text": doc_text,
                            "relevance_score": round(similarity, 4)
                        })
                
                retrieved.sort(key=lambda x: x["relevance_score"], reverse=True)
                return retrieved[:top_k]
            except Exception as e:
                print(f"[RetrievalService] ChromaDB query error: {e}. Trying in-memory store.")

        # Fallback query on in-memory store
        scored = []
        for item in self._memory_chunks:
            sim = embedding_service.cosine_similarity(query_embedding, item["embedding"])
            if sim < SIMILARITY_THRESHOLD:
                continue
                
            meta = item["metadata"]
            source_type = meta.get("source_type", "General")
            cred_score = normalize_credibility(meta.get("credibility_score"), get_cred_score(source_type))
            
            scored.append({
                "chunk_id": meta.get("chunk_id", ""),
                "document_name": meta.get("document_name", "Unknown"),
                "source": meta.get("source", "Unknown"),
                "source_type": source_type,
                "page_number": int(meta.get("page_number", 1)),
                "url": meta.get("url", ""),
                "publication_date": meta.get("publication_date", ""),
                "retrieval_date": meta.get("retrieval_date", ""),
                "credibility_score": cred_score,
                "text": item["text"],
                "relevance_score": round(sim, 4)
            })

        # Fallback to SQLite news & trusted corpus if in-memory and ChromaDB have no items
        if not scored:
            try:
                from backend.database.db import get_recent_news_articles
                news_items = get_recent_news_articles(limit=60)
                for item in news_items:
                    headline = item.get("title", "")
                    body = item.get("summary") or item.get("content") or ""
                    full_text = f"{headline}. {body}".strip()
                    if not full_text:
                        continue
                    item_emb = embedding_service.embed_query(full_text)
                    sim = embedding_service.cosine_similarity(query_embedding, item_emb)
                    if sim < SIMILARITY_THRESHOLD:
                        continue
                        
                    source_type = item.get("category", "Live News")
                    cred_score = normalize_credibility(item.get("credibility"), get_cred_score(source_type))
                    
                    scored.append({
                        "chunk_id": f"news_{item.get('id', '')}",
                        "document_name": item.get("source", "Trusted News"),
                        "source": item.get("source", "Trusted News Feed"),
                        "source_type": source_type,
                        "page_number": 1,
                        "url": item.get("url", ""),
                        "publication_date": item.get("published_at", ""),
                        "retrieval_date": item.get("fetched_at", ""),
                        "credibility_score": cred_score,
                        "text": full_text,
                        "relevance_score": round(sim, 4)
                    })
            except Exception as e:
                print(f"[RetrievalService] SQLite news fallback retrieval error: {e}")

        scored.sort(key=lambda x: x["relevance_score"], reverse=True)
        return scored[:top_k]

    def count(self) -> int:
        """Returns total number of chunks indexed across vector store and database."""
        if self._collection is not None:
            try:
                cnt = self._collection.count()
                if cnt > 0:
                    return cnt
            except Exception:
                pass
        if self._memory_chunks:
            return len(self._memory_chunks)
        try:
            from backend.database.db import get_news_stats
            stats = get_news_stats()
            total = stats.get("total_news_chunks", 0) or stats.get("total_articles", 0)
            if total > 0:
                return total
        except Exception:
            pass
        return len(self._memory_chunks)

retrieval_service = RetrievalService()
