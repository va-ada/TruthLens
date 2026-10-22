import threading
import os
import shutil
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Query

from backend.models.schemas import (
    ClaimVerificationRequest,
    VerificationResponse,
    DocumentItem,
    AnalyticsData,
    FeedbackRequest
)
from backend.services.verification_service import verification_service
from backend.services.document_processor import process_document, detect_source_type
from backend.services.retrieval_service import retrieval_service
from backend.database.db import (
    save_document,
    get_all_documents,
    get_document_by_id,
    delete_document_by_id,
    get_verification_history,
    get_verification_by_id,
    delete_verification_history,
    get_analytics,
    save_feedback,
    get_feedback,
    llm_budget_used
)
from backend import config as app_config
from backend.rate_limit import rate_limit
from backend.config import UPLOADS_DIR, TRUSTED_DOCS_DIR
from backend.services.news_sync_service import news_sync_service
from backend.security import (
    require_admin,
    client_hash,
    safe_upload_name,
    resolve_inside,
    MAX_UPLOAD_BYTES
)

router = APIRouter(prefix="/api")

_verify_slots = threading.BoundedSemaphore(app_config.MAX_CONCURRENT_VERIFICATIONS)

@router.get("/health")
def api_health_check():
    """Returns the real-time health and count of indexed evidence chunks."""
    from backend.services.retrieval_service import retrieval_service
    return {
        "status": "healthy",
        "service": "TruthLens Fact Verification Engine",
        "indexed_chunks": retrieval_service.count(),
        "llm_budget": llm_budget_status()
    }


def llm_budget_status() -> dict:
    return {"used": llm_budget_used(), "limit": int(app_config.LLM_DAILY_BUDGET)}


@router.post("/verify", response_model=VerificationResponse,
             dependencies=[Depends(rate_limit("verify", "VERIFY_RATE_PER_MIN"))])
def verify_claim(request: ClaimVerificationRequest, owner: str = Depends(client_hash)):
    """
    Core fact-verification endpoint.
    Retrieves evidence from ChromaDB, reranks chunks, and provides explainable verdict.
    Unexpected errors surface as a generic 500 (see main.py); exception text is never returned.
    Load shedding: beyond MAX_CONCURRENT_VERIFICATIONS in flight, answer 503 at once instead of queueing
    (the offline judge is CPU-bound and serialised; a queue of 10 meant ~90 s waits in the load test).
    """
    if not _verify_slots.acquire(blocking=False):
        raise HTTPException(status_code=503, headers={"Retry-After": "30"},
                            detail="TruthLens is busy checking other claims. Please try again in about 30 seconds.")
    try:
        return verification_service.verify(request, owner)
    finally:
        _verify_slots.release()

@router.post("/upload", dependencies=[Depends(require_admin), Depends(rate_limit("upload", "UPLOAD_RATE_PER_MIN"))])
async def upload_document(
    file: UploadFile = File(...),
    source_name: Optional[str] = Form(None),
    source_type: Optional[str] = Form(None)
):
    """
    Accepts PDF, TXT, MD documents, extracts text, generates chunks and vector embeddings.
    """
    original_name = Path((file.filename or "").replace("\\", "/")).name
    filename = safe_upload_name(file.filename)
    ext = Path(filename).suffix.lower()

    # Save file to uploads directory, streaming with a hard size cap
    target_path = resolve_inside(UPLOADS_DIR, filename)
    written = 0
    try:
        with open(target_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="File too large. Maximum size is 10 MB.")
                buffer.write(chunk)
    except HTTPException:
        target_path.unlink(missing_ok=True)
        raise
    except Exception as e:
        target_path.unlink(missing_ok=True)
        print(f"[Routes] Upload save failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to save the uploaded file.")

    # Process and chunk document
    inferred_source = source_name or original_name
    inferred_type = source_type or detect_source_type(original_name, inferred_source)
    chunks = process_document(target_path, source_name=inferred_source, source_type=inferred_type)

    if not chunks:
        target_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="No readable text could be extracted from the document.")

    # Index into ChromaDB vector database
    indexed_count = retrieval_service.add_chunks(chunks)

    # Save to SQLite document registry
    doc_id = save_document(
        filename=filename,
        source=inferred_source,
        source_type=inferred_type,
        file_type=ext.replace(".", "").upper(),
        number_of_chunks=indexed_count
    )

    return {
        "status": "success",
        "document_id": doc_id,
        "filename": filename,
        "source": inferred_source,
        "source_type": inferred_type,
        "chunks_indexed": indexed_count
    }

@router.get("/documents", response_model=List[DocumentItem])
def list_documents():
    """Returns all documents registered in the knowledge base."""
    docs = get_all_documents()
    return [
        DocumentItem(
            id=d["id"],
            filename=d["filename"],
            source=d["source"],
            source_type=d["source_type"],
            file_type=d["file_type"],
            upload_date=d["upload_date"],
            number_of_chunks=d["number_of_chunks"],
            processing_status=d["processing_status"]
        ) for d in docs
    ]

@router.delete("/documents/{doc_id}", dependencies=[Depends(require_admin)])
def delete_document(doc_id: str):
    """Deletes a document and its corresponding vector chunks."""
    doc = get_document_by_id(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Remove chunks from vector store
    retrieval_service.delete_document_chunks(doc["filename"])

    # Remove physical upload if present
    try:
        file_path = resolve_inside(UPLOADS_DIR, doc["filename"])
        if file_path.exists():
            file_path.unlink()
    except Exception:
        pass

    # Delete from DB
    delete_document_by_id(doc_id)
    return {"status": "success", "message": f"Document {doc['filename']} deleted successfully."}

@router.get("/history")
def list_history(limit: int = Query(50, ge=1, le=100), owner: str = Depends(client_hash)):
    """The caller's own verification history (identified by the X-Client-Id header), newest first."""
    return get_verification_history(owner, limit=limit)

@router.delete("/history")
def clear_history(owner: str = Depends(client_hash)):
    """Deletes all of the caller's stored verifications."""
    return {"status": "deleted", "count": delete_verification_history(owner)}

@router.get("/history/{v_id}")
def get_history_detail(v_id: str, owner: str = Depends(client_hash)):
    """Full details of one of the caller's past verifications."""
    item = get_verification_by_id(v_id, owner)
    if not item:
        raise HTTPException(status_code=404, detail="Verification record not found.")
    return item

@router.get("/analytics", response_model=AnalyticsData)
def analytics_dashboard(owner: str = Depends(client_hash)):
    """Verdict breakdown of the caller's own checks; knowledge-base totals are global."""
    return AnalyticsData(**get_analytics(owner))

@router.post("/feedback", status_code=201, dependencies=[Depends(rate_limit("feedback", "FEEDBACK_RATE_PER_MIN"))])
def submit_feedback(payload: FeedbackRequest, owner: str = Depends(client_hash)):
    """Records a user's report that a verdict looks wrong."""
    fb_id = save_feedback(payload.verification_id, payload.claim.strip(), payload.verdict,
                          payload.suggested_verdict, (payload.comment or "").strip() or None, owner)
    return {"status": "received", "id": fb_id}

@router.get("/feedback", dependencies=[Depends(require_admin)])
def list_feedback():
    """Newest 200 verdict reports (admin only)."""
    return get_feedback(200)

@router.post("/seed", dependencies=[Depends(require_admin)])
def seed_trusted_knowledge_base():
    """
    Ingests and indexes the preloaded trusted fact dossiers
    (Economy/GDP, Climate/Renewables, Medical/Vaccines, AI Benchmarks).
    """
    seeded_docs = []
    total_chunks = 0

    if not TRUSTED_DOCS_DIR.exists():
        raise HTTPException(status_code=404, detail="Trusted docs directory not found.")

    for doc_file in TRUSTED_DOCS_DIR.glob("*.txt"):
        filename = doc_file.name
        source_type = detect_source_type(filename)
        chunks = process_document(doc_file, source_name=filename.replace(".txt", "").replace("_", " ").title(), source_type=source_type)
        if chunks:
            # First remove any prior chunks with this filename to prevent duplicate index entries
            retrieval_service.delete_document_chunks(filename)
            indexed_cnt = retrieval_service.add_chunks(chunks)
            doc_id = save_document(
                filename=filename,
                source=filename.replace(".txt", "").replace("_", " ").title(),
                source_type=source_type,
                file_type="TXT",
                number_of_chunks=indexed_cnt
            )
            seeded_docs.append({
                "id": doc_id,
                "filename": filename,
                "chunks": indexed_cnt
            })
            total_chunks += indexed_cnt

    return {
        "status": "success",
        "message": f"Successfully indexed {len(seeded_docs)} curated dossiers ({total_chunks} total evidence chunks).",
        "seeded_documents": seeded_docs,
        "total_chunks_indexed": total_chunks
    }

@router.get("/news/status")
def get_news_status():
    """
    Returns the real-time health and synchronization stats of the daily news engine,
    including total ingested articles, active RSS feeds, and recent headlines.
    """
    return news_sync_service.get_status()

@router.post("/news/sync", dependencies=[Depends(require_admin)])
def sync_daily_news(max_per_feed: int = 10):
    """
    Manually triggers an immediate pull and indexing of the latest 24h news 
    from trusted sources (Reuters, BBC World, AP, PolitiFact, Google News).
    """
    result = news_sync_service.sync_live_news(max_per_feed=max_per_feed)
    return result

@router.post("/news/train-dataset", dependencies=[Depends(require_admin)])
def train_on_existing_news_dataset(max_articles: int = 100):
    """
    Ingests and vector-indexes historical news articles and PolitiFact ground-truth
    records from existing datasets (ISOT Reuters & LIAR).
    """
    try:
        return news_sync_service.train_on_existing_news_dataset(max_articles=max_articles)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/news/trending")
def get_daily_trending_claims():
    """
    Returns today's active news stories and viral claims for 1-click verification.
    """
    return news_sync_service.get_trending_daily_claims()

@router.post("/news/extract-url", dependencies=[Depends(rate_limit("extract", "URL_EXTRACT_RATE_PER_MIN"))])
def extract_claim_from_news_url(payload: dict):
    """
    Extracts the main headline and core claim from an online news link.
    """
    url = payload.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Please provide a valid URL.")
    try:
        return news_sync_service.extract_claim_from_url(url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/news/clean-forward")
def clean_social_forward_message(payload: dict):
    """
    Cleans viral WhatsApp forward boilerplate and extracts the verifiable factual claim.
    """
    text = payload.get("text", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Please provide message text.")
    cleaned = news_sync_service.clean_viral_message(text)
    return {"cleaned_claim": cleaned, "original_length": len(text), "cleaned_length": len(cleaned)}


