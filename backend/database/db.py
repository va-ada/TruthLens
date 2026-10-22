import sqlite3
import json
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import shutil
from backend.config import DB_PATH, IS_VERCEL, BASE_DIR
from backend.models.schemas import Verdict, normalize_verdict

def utc_now() -> str:
    """All stored timestamps are UTC ISO-8601 so they sort correctly and convert cleanly in the UI."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_db_ready():
    if IS_VERCEL:
        bundled = BASE_DIR / "backend" / "database" / "truthlens.db"
        if bundled.exists():
            should_copy = False
            if not DB_PATH.exists() or DB_PATH.stat().st_size < 100000:
                should_copy = True
            else:
                try:
                    c = sqlite3.connect(str(DB_PATH))
                    cnt = c.cursor().execute("SELECT count(*) FROM daily_news_articles").fetchone()[0]
                    c.close()
                    if cnt == 0:
                        should_copy = True
                except Exception:
                    should_copy = True
            if should_copy:
                try:
                    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(bundled, DB_PATH)
                    print(f"[TruthLens] Seeded {DB_PATH} from bundled repository database.")
                except Exception as e:
                    print(f"[TruthLens] DB seed notice: {e}")

def get_connection():
    ensure_db_ready()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    ensure_db_ready()
    conn = get_connection()
    cursor = conn.cursor()
    
    # Documents table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            source TEXT NOT NULL,
            source_type TEXT NOT NULL,
            file_type TEXT NOT NULL,
            file_hash TEXT,
            upload_date TEXT NOT NULL,
            number_of_chunks INTEGER DEFAULT 0,
            processing_status TEXT DEFAULT 'COMPLETED'
        )
    """)
    
    # Verification history table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS verification_history (
            id TEXT PRIMARY KEY,
            claim TEXT NOT NULL,
            verdict TEXT NOT NULL,
            confidence_score REAL NOT NULL,
            explanation TEXT NOT NULL,
            key_reasoning TEXT,
            source_credibility_score REAL DEFAULT 0.0,
            evidence_agreement_score REAL DEFAULT 0.0,
            agreement_analysis TEXT,
            raw_response TEXT,
            timestamp TEXT NOT NULL
        )
    """)
    
    # Daily news articles table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_news_articles (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            source_name TEXT NOT NULL,
            url TEXT UNIQUE,
            content_snippet TEXT,
            published_date TEXT,
            ingested_at TEXT NOT NULL,
            chunks_indexed INTEGER DEFAULT 0,
            category TEXT DEFAULT 'WORLD'
        )
    """)
    
    # Per-browser ownership of history rows (sha256 of the anonymous client id). Rows from before this
    # column existed have NULL and are never returned to anyone.
    cols = {r["name"] for r in cursor.execute("PRAGMA table_info(verification_history)").fetchall()}
    if "client_hash" not in cols:
        cursor.execute("ALTER TABLE verification_history ADD COLUMN client_hash TEXT")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_client ON verification_history (client_hash, timestamp)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id TEXT PRIMARY KEY,
            verification_id TEXT NOT NULL,
            claim TEXT NOT NULL,
            verdict TEXT NOT NULL,
            suggested_verdict TEXT,
            comment TEXT,
            client_hash TEXT,
            created_at TEXT NOT NULL
        )
    """)

    # Cloud-LLM calls per UTC day, persisted so a restart does not reset the budget
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS llm_budget (
            day TEXT PRIMARY KEY,
            used INTEGER NOT NULL DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()

# Initialize tables immediately
init_db()

def save_document(
    filename: str,
    source: str,
    source_type: str,
    file_type: str,
    number_of_chunks: int,
    file_hash: str = "",
    doc_id: Optional[str] = None
) -> str:
    doc_id = doc_id or str(uuid.uuid4())
    upload_date = utc_now()
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO documents 
        (id, filename, source, source_type, file_type, file_hash, upload_date, number_of_chunks, processing_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'COMPLETED')
    """, (doc_id, filename, source, source_type, file_type, file_hash, upload_date, number_of_chunks))
    conn.commit()
    conn.close()
    return doc_id

def get_all_documents() -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM documents ORDER BY upload_date DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_document_by_id(doc_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def delete_document_by_id(doc_id: str) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def save_verification(data: Dict[str, Any], client_hash: Optional[str] = None) -> str:
    v_id = data.get("id") or str(uuid.uuid4())
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO verification_history 
        (id, claim, verdict, confidence_score, explanation, key_reasoning, source_credibility_score, evidence_agreement_score, agreement_analysis, raw_response, timestamp, client_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        v_id,
        data["claim"],
        data["verdict"],
        data["confidence_score"],
        data["explanation"],
        data.get("key_reasoning", ""),
        data.get("source_credibility_score", 0.0),
        data.get("evidence_agreement_score", 0.0),
        data.get("agreement_analysis", ""),
        json.dumps(data),
        data.get("timestamp") or utc_now(),
        client_hash
    ))
    conn.commit()
    conn.close()
    return v_id

def get_verification_history(client_hash: Optional[str], limit: int = 50) -> List[Dict[str, Any]]:
    """The caller's own verifications, newest first. No client id -> nothing."""
    if not client_hash:
        return []
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, claim, verdict, confidence_score, explanation, timestamp, raw_response
        FROM verification_history
        WHERE client_hash = ?
        ORDER BY timestamp DESC LIMIT ?
    """, (client_hash, limit))
    rows = cursor.fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        raw = d.pop("raw_response", None)
        if raw:
            try:
                results.append(json.loads(raw))
                continue
            except Exception:
                pass
        results.append(d)
    return results

def get_verification_by_id(v_id: str, client_hash: Optional[str]) -> Optional[Dict[str, Any]]:
    if not client_hash:
        return None
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT raw_response FROM verification_history WHERE id = ? AND client_hash = ?", (v_id, client_hash))
    row = cursor.fetchone()
    conn.close()
    if row and row["raw_response"]:
        try:
            return json.loads(row["raw_response"])
        except Exception:
            return None
    return None

def delete_verification_history(client_hash: Optional[str]) -> int:
    if not client_hash:
        return 0
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM verification_history WHERE client_hash = ?", (client_hash,))
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count

def find_most_similar_claim(claim_text: str, client_hash: Optional[str]) -> Optional[Dict[str, Any]]:
    """Token-overlap match against the caller's OWN history only (other people's claims stay private)."""
    if not client_hash:
        return None
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, claim, verdict, confidence_score, timestamp FROM verification_history WHERE client_hash = ?",
                   (client_hash,))
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return None
        
    def clean(s):
        return set(s.lower().replace("?", "").replace(".", "").replace(",", "").split())
        
    c_tokens = clean(claim_text)
    if not c_tokens:
        return None
        
    best_match = None
    best_jaccard = 0.0
    
    for r in rows:
        r_tokens = clean(r["claim"])
        if not r_tokens:
            continue
        intersection = c_tokens.intersection(r_tokens)
        union = c_tokens.union(r_tokens)
        jaccard = len(intersection) / len(union) if union else 0.0
        
        # High similarity match
        if jaccard > best_jaccard and jaccard >= 0.65:
            best_jaccard = jaccard
            best_match = {
                "id": r["id"],
                "claim": r["claim"],
                "verdict": r["verdict"],
                "confidence_score": r["confidence_score"],
                "timestamp": r["timestamp"],
                "similarity_score": round(jaccard * 100, 1)
            }
            
    return best_match

def get_analytics(client_hash: Optional[str]):
    """Verdict stats over the caller's own history; document/chunk stats are global (no claim text)."""
    conn = get_connection()
    cursor = conn.cursor()
    owner = client_hash or "\x00no-client"  # matches no row

    cursor.execute("SELECT COUNT(*) as total FROM verification_history WHERE client_hash = ?", (owner,))
    total_claims = cursor.fetchone()["total"]

    # Older rows used other verdict spellings; normalise so every row lands in a canonical bucket
    verdicts = {v.value: 0 for v in Verdict}
    cursor.execute("SELECT verdict, COUNT(*) as cnt FROM verification_history WHERE client_hash = ? GROUP BY verdict", (owner,))
    for r in cursor.fetchall():
        verdicts[normalize_verdict(r["verdict"])] += r["cnt"]

    cursor.execute("SELECT AVG(confidence_score) as avg_conf, AVG(source_credibility_score) as avg_cred "
                   "FROM verification_history WHERE client_hash = ?", (owner,))
    avg_row = cursor.fetchone()
    avg_conf = round(avg_row["avg_conf"] or 0.0, 1)
    avg_cred = round(avg_row["avg_cred"] or 0.0, 1)
    
    # Total documents & chunks
    cursor.execute("SELECT COUNT(*) as total_docs, SUM(number_of_chunks) as total_chunks FROM documents")
    doc_row = cursor.fetchone()
    total_docs = doc_row["total_docs"] or 0
    total_chunks = doc_row["total_chunks"] or 0
    
    # Top sources
    cursor.execute("SELECT source, source_type, COUNT(*) as doc_count FROM documents GROUP BY source ORDER BY doc_count DESC LIMIT 5")
    top_sources = [dict(r) for r in cursor.fetchall()]
    
    conn.close()
    return {
        "total_claims_verified": total_claims,
        "verdict_counts": verdicts,
        "average_confidence": avg_conf,
        "average_source_credibility": avg_cred,
        "total_documents": total_docs,
        "total_chunks": total_chunks,
        "top_sources": top_sources
    }

def save_news_article(
    title: str,
    source_name: str,
    url: str,
    content_snippet: str,
    published_date: str,
    chunks_indexed: int = 1,
    category: str = "WORLD",
    article_id: Optional[str] = None
) -> str:
    article_id = article_id or str(uuid.uuid4())
    ingested_at = utc_now()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO daily_news_articles
        (id, title, source_name, url, content_snippet, published_date, ingested_at, chunks_indexed, category)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (article_id, title, source_name, url, content_snippet, published_date, ingested_at, chunks_indexed, category))
    conn.commit()
    conn.close()
    return article_id

def is_news_url_indexed(url: str) -> bool:
    if not url:
        return False
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM daily_news_articles WHERE url = ?", (url,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def get_recent_news_articles(limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM daily_news_articles ORDER BY ingested_at DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_news_stats() -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as total_articles, SUM(chunks_indexed) as total_news_chunks FROM daily_news_articles")
    row = cursor.fetchone()
    total_articles = row["total_articles"] or 0
    total_chunks = row["total_news_chunks"] or 0
    
    cursor.execute("SELECT ingested_at FROM daily_news_articles ORDER BY ingested_at DESC LIMIT 1")
    last_row = cursor.fetchone()
    last_sync = last_row["ingested_at"] if last_row else "Never"
    
    conn.close()
    return {
        "total_articles": total_articles,
        "total_news_chunks": total_chunks,
        "last_sync": last_sync
    }



# ---------------------------------------------------------------- feedback

def save_feedback(verification_id: str, claim: str, verdict: str, suggested_verdict: Optional[str],
                  comment: Optional[str], client_hash: Optional[str]) -> str:
    fb_id = str(uuid.uuid4())
    conn = get_connection()
    conn.execute("""
        INSERT INTO feedback (id, verification_id, claim, verdict, suggested_verdict, comment, client_hash, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (fb_id, verification_id, claim, verdict, suggested_verdict, comment, client_hash, utc_now()))
    conn.commit()
    conn.close()
    return fb_id

def get_feedback(limit: int = 200) -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, verification_id, claim, verdict, suggested_verdict, comment, created_at
        FROM feedback ORDER BY created_at DESC, rowid DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ---------------------------------------------------------------- cloud LLM daily budget

def _utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def llm_budget_used(day: Optional[str] = None) -> int:
    conn = get_connection()
    row = conn.execute("SELECT used FROM llm_budget WHERE day = ?", (day or _utc_day(),)).fetchone()
    conn.close()
    return int(row["used"]) if row else 0

def llm_budget_try_consume(limit: int, day: Optional[str] = None) -> bool:
    """Atomically counts one cloud call if under the limit (limit <= 0 means unlimited)."""
    day = day or _utc_day()
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT OR IGNORE INTO llm_budget (day, used) VALUES (?, 0)", (day,))
        if limit > 0:
            cur = conn.execute("UPDATE llm_budget SET used = used + 1 WHERE day = ? AND used < ?", (day, limit))
        else:
            cur = conn.execute("UPDATE llm_budget SET used = used + 1 WHERE day = ?", (day,))
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()

# ---------------------------------------------------------------- retention

def purge_old_records(history_days: int, feedback_days: int) -> Dict[str, int]:
    """Deletes verification history / feedback older than the retention windows. Timestamps are UTC ISO."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    conn = get_connection()
    h = conn.execute("DELETE FROM verification_history WHERE timestamp < ?",
                     ((now - timedelta(days=history_days)).isoformat(timespec="seconds"),)).rowcount
    f = conn.execute("DELETE FROM feedback WHERE created_at < ?",
                     ((now - timedelta(days=feedback_days)).isoformat(timespec="seconds"),)).rowcount
    conn.execute("DELETE FROM llm_budget WHERE day < ?", ((now - timedelta(days=7)).strftime("%Y-%m-%d"),))
    conn.commit()
    conn.close()
    return {"history": h, "feedback": f}
