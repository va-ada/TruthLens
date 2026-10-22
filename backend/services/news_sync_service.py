import asyncio
import csv
import logging
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

from backend.config import DATA_DIR
from backend.database.db import (
    save_news_article,
    is_news_url_indexed,
    get_recent_news_articles,
    get_news_stats,
    save_document
)
from backend.services.document_processor import document_processor
from backend.services.retrieval_service import retrieval_service
from backend.security import fetch_public_url
from backend.models.schemas import normalize_credibility

logger = logging.getLogger("truthlens.news_sync")

# Trusted Global News & Fact-Checking RSS Feeds
TRUSTED_RSS_FEEDS = [
    {
        "name": "Reuters World News",
        "url": "https://news.google.com/rss/search?q=when:24h+allinurl:reuters.com&ceid=US:en&hl=en-US&gl=US",
        "category": "WORLD_NEWS",
        "credibility": 98.0
    },
    {
        "name": "BBC News Top Stories",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "category": "GLOBAL_AFFAIRS",
        "credibility": 96.0
    },
    {
        "name": "Associated Press News",
        "url": "https://news.google.com/rss/search?q=when:24h+allinurl:apnews.com&ceid=US:en&hl=en-US&gl=US",
        "category": "BREAKING_NEWS",
        "credibility": 97.0
    },
    {
        "name": "PolitiFact Verified Fact-Checks",
        "url": "https://www.politifact.com/rss/factchecks/",
        "category": "FACT_CHECK",
        "credibility": 99.0
    },
    {
        "name": "Google News International",
        "url": "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
        "category": "GENERAL_NEWS",
        "credibility": 90.0
    }
]

def parse_rss_xml(xml_data: bytes) -> ET.Element:
    """
    Parses an RSS document. Some feeds (PolitiFact) send blank lines or a BOM before the
    <?xml ...?> declaration, which ElementTree rejects ("XML or text declaration not at start of entity").
    """
    return ET.fromstring(xml_data.lstrip(b"\xef\xbb\xbf").lstrip())


# Note: Google News feed items link to news.google.com/rss/articles/... redirect pages. Resolving those to
# the publisher URL requires executing Google's JavaScript, so these links are stored as-is (they still open
# the original article in a browser).

class NewsSyncService:
    def __init__(self):
        self.is_running = False
        self.last_sync_time: Optional[str] = None
        self.next_sync_time: Optional[str] = None
        self.sync_interval_hours = 24
        self.background_task: Optional[asyncio.Task] = None
        self.is_syncing = False

    def clean_html(self, raw_html: str) -> str:
        """Strip HTML tags, entities, and excessive whitespace."""
        if not raw_html:
            return ""
        clean = re.sub(r'<[^>]+>', ' ', raw_html)
        clean = re.sub(r'&[a-zA-Z0-9#]+;', ' ', clean)
        # Remove common news domain artifacts (e.g. yahoo.com, apnews.com)
        clean = re.sub(r'\b[a-zA-Z0-9-]+\.(com|org|net|co\.uk|news)\b', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean

    def fetch_rss_feed(self, feed_cfg: Dict[str, Any], max_items: int = 15) -> List[Dict[str, Any]]:
        """
        Fetch and parse articles from a trusted RSS feed.
        """
        articles = []
        url = feed_cfg["url"]
        source_name = feed_cfg["name"]
        category = feed_cfg.get("category", "NEWS")

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "TruthLens-FactVerification/2.0 (Academic/Research RAG System)"}
            )
            with urllib.request.urlopen(req, timeout=12) as response:
                xml_data = response.read()

            root = parse_rss_xml(xml_data)
            items = root.findall(".//item")

            for item in items[:max_items]:
                title_elem = item.find("title")
                desc_elem = item.find("description")
                link_elem = item.find("link")
                pub_date_elem = item.find("pubDate")

                title = self.clean_html(title_elem.text if title_elem is not None else "")
                desc = self.clean_html(desc_elem.text if desc_elem is not None else "")
                link = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
                pub_date = pub_date_elem.text.strip() if pub_date_elem is not None and pub_date_elem.text else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                if not title:
                    continue

                full_content = f"{title}. {desc}"

                articles.append({
                    "title": title,
                    "description": desc,
                    "full_content": full_content,
                    "url": link,
                    "pub_date": pub_date,
                    "source_name": source_name,
                    "category": category,
                    "credibility": feed_cfg.get("credibility", 95.0)
                })

        except Exception as e:
            logger.warning(f"[NewsSyncService] Failed to fetch feed {source_name}: {e}")

        return articles

    def sync_live_news(self, max_per_feed: int = 10) -> Dict[str, Any]:
        """
        Execute an on-demand live news sync across all trusted feeds.
        Chunks articles and indexes them into ChromaDB vector database.
        """
        if self.is_syncing:
            return {"status": "in_progress", "message": "A news synchronization is already running."}

        self.is_syncing = True
        new_articles_count = 0
        total_chunks_indexed = 0
        ingested_items = []

        try:
            for feed in TRUSTED_RSS_FEEDS:
                articles = self.fetch_rss_feed(feed, max_items=max_per_feed)
                for art in articles:
                    url = art.get("url", "")
                    title = art["title"]

                    # Skip already indexed articles
                    if url and is_news_url_indexed(url):
                        continue

                    # Chunk the news content
                    content = art["full_content"]
                    chunks = document_processor.chunk_text(
                        text=content,
                        chunk_size=400,
                        overlap=60,
                        source_name=art["source_name"],
                        file_type="LIVE_RSS",
                        source_type="LIVE_NEWS_FEED",
                        extra_metadata={
                            "url": url,
                            "publication_date": art["pub_date"],
                            "retrieval_date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "category": art["category"],
                            "credibility_score": normalize_credibility(art["credibility"])
                        }
                    )

                    if not chunks:
                        continue

                    # Index into ChromaDB
                    retrieval_service.add_chunks(chunks)

                    # Record in SQLite database
                    save_news_article(
                        title=title,
                        source_name=art["source_name"],
                        url=url,
                        content_snippet=art["description"][:300] if art["description"] else title,
                        published_date=art["pub_date"],
                        chunks_indexed=len(chunks),
                        category=art["category"]
                    )

                    new_articles_count += 1
                    total_chunks_indexed += len(chunks)
                    ingested_items.append({
                        "title": title,
                        "source": art["source_name"],
                        "chunks": len(chunks)
                    })

            self.last_sync_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            next_time = datetime.now() + timedelta(hours=self.sync_interval_hours)
            self.next_sync_time = next_time.strftime("%Y-%m-%d %H:%M:%S")

            logger.info(f"[NewsSyncService] Synced {new_articles_count} new articles ({total_chunks_indexed} chunks).")

            return {
                "status": "success",
                "message": f"Successfully synced {new_articles_count} new live articles ({total_chunks_indexed} vector chunks).",
                "new_articles_count": new_articles_count,
                "total_chunks_indexed": total_chunks_indexed,
                "last_sync_time": self.last_sync_time,
                "next_sync_time": self.next_sync_time,
                "ingested_items": ingested_items[:15]
            }

        except Exception as e:
            logger.error(f"[NewsSyncService] Sync failed: {e}")
            return {"status": "error", "message": f"Sync failed: {str(e)}"}
        finally:
            self.is_syncing = False

    def train_on_existing_news_dataset(self, max_articles: int = 100) -> Dict[str, Any]:
        """
        Index historical news datasets into the vector store
        (ISOT Reuters True News & PolitiFact LIAR dataset). Raises FileNotFoundError if neither is present.
        """
        indexed_count = 0
        total_chunks = 0

        true_csv_path = DATA_DIR / "raw" / "isot" / "True.csv"
        liar_csv_path = DATA_DIR / "raw" / "liar" / "liar_all.csv"
        if not true_csv_path.exists() and not liar_csv_path.exists():
            raise FileNotFoundError(
                f"No dataset files found. Place the ISOT Fake News dataset's True.csv at {true_csv_path} "
                f"(University of Victoria ISOT lab: https://onlineacademiccommunity.uvic.ca/isot/datasets/) and/or "
                f"the LIAR dataset as a CSV at {liar_csv_path} (Wang 2017, https://www.cs.ucsb.edu/~william/data/liar_dataset.zip; "
                f"convert the TSV splits to one CSV with columns statement,label,speaker,subject,context)."
            )

        # 1. Ingest from data/raw/isot/True.csv
        if true_csv_path.exists():
            try:
                with open(true_csv_path, "r", encoding="utf-8", errors="ignore") as f:
                    reader = csv.DictReader(f)
                    for idx, row in enumerate(reader):
                        if idx >= max_articles:
                            break
                        
                        title = row.get("title", "").strip()
                        text = row.get("text", "").strip()
                        date_str = row.get("date", "").strip()
                        subject = row.get("subject", "politicsNews").strip()

                        if not title or not text or len(text) < 80:
                            continue

                        content = f"ARCHIVED REUTERS VERIFIED NEWS\nTITLE: {title}\nDATE: {date_str}\nSUBJECT: {subject}\n\n{text[:2000]}"
                        
                        chunks = document_processor.chunk_text(
                            text=content,
                            chunk_size=450,
                            overlap=80,
                            source_name="ISOT Reuters Verified Archive",
                            file_type="CSV_DATASET",
                            source_type="VERIFIED_NEWS_ARCHIVE",
                            extra_metadata={
                                "publication_date": date_str,
                                "category": subject,
                                "credibility_score": 0.96
                            }
                        )

                        if chunks:
                            retrieval_service.add_chunks(chunks)
                            save_news_article(
                                title=title,
                                source_name="Reuters Verified Archive",
                                url=f"isot://true/{idx}",
                                content_snippet=text[:250],
                                published_date=date_str,
                                chunks_indexed=len(chunks),
                                category=subject
                            )
                            indexed_count += 1
                            total_chunks += len(chunks)
            except Exception as e:
                logger.warning(f"[NewsSyncService] Failed loading True.csv: {e}")

        # 2. Ingest from data/raw/liar/liar_all.csv
        if liar_csv_path.exists():
            try:
                with open(liar_csv_path, "r", encoding="utf-8", errors="ignore") as f:
                    reader = csv.DictReader(f)
                    for idx, row in enumerate(reader):
                        if idx >= (max_articles // 2):
                            break
                        
                        statement = row.get("statement", "").strip()
                        label = row.get("label", "").strip()
                        speaker = row.get("speaker", "").strip()
                        subject = row.get("subject", "").strip()
                        context = row.get("context", "").strip()

                        if not statement:
                            continue

                        content = f"POLITIFACT FACT CHECK REPORT\nCLAIM: \"{statement}\"\nVERDICT: {label.upper()}\nSPEAKER: {speaker}\nCONTEXT: {context}\nSUBJECT: {subject}"
                        
                        chunks = document_processor.chunk_text(
                            text=content,
                            chunk_size=350,
                            overlap=50,
                            source_name="PolitiFact LIAR Ground Truth Archive",
                            file_type="CSV_DATASET",
                            source_type="FACT_CHECK_ARCHIVE",
                            extra_metadata={
                                "category": subject,
                                "speaker": speaker,
                                "credibility_score": 0.98
                            }
                        )

                        if chunks:
                            retrieval_service.add_chunks(chunks)
                            save_news_article(
                                title=f"Fact Check: {statement[:80]}...",
                                source_name="PolitiFact Archive",
                                url=f"liar://factcheck/{idx}",
                                content_snippet=f"Speaker: {speaker} | Truth Label: {label} | Statement: {statement}",
                                published_date="Historical",
                                chunks_indexed=len(chunks),
                                category=subject
                            )
                            indexed_count += 1
                            total_chunks += len(chunks)
            except Exception as e:
                logger.warning(f"[NewsSyncService] Failed loading liar_all.csv: {e}")

        if total_chunks == 0:
            return {
                "status": "error",
                "message": "Dataset files were found but no rows could be indexed (check the CSV columns).",
                "articles_indexed": 0,
                "total_chunks_indexed": 0
            }

        save_document(
            filename="Historical News & Fact-Checking Dataset Training",
            source="ISOT Reuters & PolitiFact Dataset",
            source_type="VERIFIED_ARCHIVE",
            file_type="CSV",
            number_of_chunks=total_chunks
        )

        return {
            "status": "success",
            "message": f"Indexed existing news datasets into the vector store: {indexed_count} historical news articles & fact-checks ({total_chunks} vector chunks).",
            "articles_indexed": indexed_count,
            "total_chunks_indexed": total_chunks
        }

    async def start_daily_scheduler(self):
        """
        Background scheduler that runs every 24 hours to pull new updates.
        """
        self.is_running = True
        logger.info("[NewsSyncService] Background Daily News Scheduler started.")

        # Initial sync on startup
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.sync_live_news, 8)
        except Exception as e:
            logger.warning(f"[NewsSyncService] Initial startup sync error: {e}")

        while self.is_running:
            try:
                # Sleep for 24 hours (86400 seconds)
                await asyncio.sleep(self.sync_interval_hours * 3600)
                logger.info("[NewsSyncService] Executing scheduled daily news ingestion...")
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.sync_live_news, 12)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[NewsSyncService] Error in daily scheduler loop: {e}")
                await asyncio.sleep(300)

    def clean_viral_message(self, raw_text: str) -> str:
        """
        Cleans common social media/WhatsApp forward headers, boilerplate, and clickbait phrases.
        """
        if not raw_text:
            return ""

        text = raw_text.strip()
        patterns = [
            r"^(forwarded\b(\s+(as\s+received|message|many\s+times)\b)?[:\s\-!]*)",
            r"^(fwd[:\s\-]*)",
            r"^(breaking\b(\s+(news|alert)\b)?[:\s\-\!]*)",
            r"^(urgent\b(\s+(alert|notice|update|news)\b)?[:\s\-\!]*)",
            r"^(viral\b(\s+(video|audio|claim|news|message)\b)?[:\s\-\!]*)",
            r"^(shocking\s+news[:\s\-\!]*)",
            r"^(alert[:\s\-\!]*)",
            r"^(flash\s+news[:\s\-\!]*)",
            r"^(important\s+message[:\s\-\!]*)",
            r"^(please\s+share\s+to\s+(everyone|all|groups)?[:\s\-\!]*)",
            r"^(share\s+to\s+\d+\s+(people|groups)?[:\s\-\!]*)",
            r"^(read\s+before\s+it\s+gets\s+deleted[:\s\-\!]*)"
        ]

        # Iteratively strip prefixes until no more match
        changed = True
        iterations = 0
        while changed and iterations < 10:
            iterations += 1
            old_text = text
            for pat in patterns:
                text = re.sub(pat, "", text, flags=re.IGNORECASE).strip()
            # Strip leading/trailing punctuation and symbols
            text = re.sub(r"^[\s:!?,.\-–—|~*#]+", "", text).strip()
            if text == old_text:
                changed = False

        # Remove trailing share/forward requests
        text = re.sub(r"(please\s+)?(forward|share)\s+(this|to\s+all|to\s+\d+|with\s+everyone|with\s+all|in\s+every\s+group).*", "", text, flags=re.IGNORECASE).strip()
        # Clean trailing punctuation
        text = re.sub(r"[\s\-–—|~*#]+$", "", text).strip()

        # Clean multiple spaces and newlines
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def extract_claim_from_url(self, url: str) -> Dict[str, Any]:
        """
        Fetches web page content from a news link and extracts the core headline/claim.
        """
        url = url.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url

        try:
            raw_html = fetch_public_url(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
                }
            )

            # Extract title
            title_match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
            og_title_match = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\'](.*?)["\']', raw_html, re.IGNORECASE)
            og_desc_match = re.search(r'<meta\s+property=["\']og:description["\']\s+content=["\'](.*?)["\']', raw_html, re.IGNORECASE)
            h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", raw_html, re.IGNORECASE | re.DOTALL)

            title = og_title_match.group(1) if og_title_match else (title_match.group(1) if title_match else (h1_match.group(1) if h1_match else ""))
            description = og_desc_match.group(1) if og_desc_match else ""

            # Clean extracted text
            title = self.clean_html(title)
            # Remove site name suffix e.g. "Headline - Reuters" or "Headline | BBC News"
            title = re.sub(r"\s*[-|–—]\s*(reuters|bbc|ap|cnn|fox|the hindu|times of india|nytimes|the guardian|bloomberg|wikipedia).*$", "", title, flags=re.IGNORECASE).strip()
            description = self.clean_html(description)

            claim_text = title if title else (description[:160] if description else "Online news report")

            return {
                "status": "success",
                "extracted_claim": claim_text,
                "title": title,
                "description": description[:300],
                "url": url
            }

        except ValueError:
            # Blocked by the SSRF guard: let the API layer turn this into a 400
            raise
        except Exception as e:
            logger.warning(f"[NewsSyncService] Failed to extract from URL {url}: {e}")
            return {
                "status": "error",
                "message": f"Failed to fetch content from URL: {str(e)}",
                "extracted_claim": "",
                "url": url
            }

    def get_trending_daily_claims(self) -> List[Dict[str, Any]]:
        """
        Returns today's active news stories & viral claims for 1-click verification.
        Combines live RSS news with categorized daily trending topics.
        """
        curated_trending = [
            {
                "claim": "Narendra Modi is the Prime Minister of India.",
                "category": "WORLD LEADERS",
                "source_hint": "Official Government / UN Records",
                "viral_level": "High Daily Query",
                "badge": "POLITICS"
            },
            {
                "claim": "Renewable energy accounts for over 30 percent of global electricity.",
                "category": "CLIMATE & ENERGY",
                "source_hint": "IEA & Global Electricity Review 2024",
                "viral_level": "Trending",
                "badge": "ENERGY"
            },
            {
                "claim": "India is the third largest economy in the world.",
                "category": "ECONOMY & MARKETS",
                "source_hint": "IMF World Economic Outlook / World Bank",
                "viral_level": "Viral Claim",
                "badge": "ECONOMY"
            },
            {
                "claim": "Antibiotics can cure viral infections like the flu.",
                "category": "HEALTH & MEDICAL",
                "source_hint": "World Health Organization & CDC",
                "viral_level": "Common Myth",
                "badge": "HEALTH"
            },
            {
                "claim": "Frontier AI training compute has doubled roughly every 5-6 months since 2010.",
                "category": "TECH & AI",
                "source_hint": "Stanford AI Index & Epoch AI",
                "viral_level": "Industry Fact",
                "badge": "TECHNOLOGY"
            },
            {
                "claim": "COVID-19 mRNA vaccines alter human DNA.",
                "category": "HEALTH & SCIENCE",
                "source_hint": "WHO & Peer-Reviewed Medical Literature",
                "viral_level": "Viral Rumor",
                "badge": "HEALTH"
            },
            {
                "claim": "Flying saucers were discovered in the lost city of Atlantis.",
                "category": "VIRAL CONSPIRACY",
                "source_hint": "Archaeological & Historical Archives",
                "viral_level": "Myth",
                "badge": "MYTH"
            },
            {
                "claim": "US GDP exceeds 28 trillion dollars in 2025.",
                "category": "GLOBAL FINANCE",
                "source_hint": "IMF & US Bureau of Economic Analysis",
                "viral_level": "Fact Check",
                "badge": "FINANCE"
            }
        ]

        # Prepend latest live RSS headlines if available
        recent = get_recent_news_articles(limit=5)
        live_items = []
        for art in recent:
            live_items.append({
                "claim": art["title"],
                "category": art.get("category", "BREAKING NEWS"),
                "source_hint": art.get("source_name", "Global News Wire"),
                "viral_level": "Today's News",
                "badge": "LIVE NEWS"
            })

        return live_items + curated_trending

    def get_status(self) -> Dict[str, Any]:
        """Return real-time scheduler health and stats."""
        stats = get_news_stats()
        recent = get_recent_news_articles(limit=50)
        
        if not recent:
            # Fallback for Vercel Serverless where /tmp SQLite DB starts empty
            from datetime import datetime
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            trending = self.get_trending_daily_claims()
            for t in trending:
                recent.append({
                    "title": t.get("claim", "News Story"),
                    "source_name": t.get("source_hint", "Global News"),
                    "category": t.get("category", "NEWS"),
                    "ingested_at": now_str
                })
        
        return {
            "is_scheduler_running": self.is_running,
            "is_currently_syncing": self.is_syncing,
            "sync_interval_hours": self.sync_interval_hours,
            "last_sync_time": self.last_sync_time or stats.get("last_sync", "Never"),
            "next_sync_time": self.next_sync_time or "Within 24 hours",
            "total_live_articles": stats.get("total_articles", 0),
            "total_news_chunks": stats.get("total_news_chunks", 0),
            "active_feeds": [f["name"] for f in TRUSTED_RSS_FEEDS],
            "recent_articles": recent
        }

# Global Singleton Instance
news_sync_service = NewsSyncService()

