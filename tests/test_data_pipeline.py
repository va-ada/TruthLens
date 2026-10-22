"""Phase 5: sourced dossiers, metadata through the loader, news normalisation, RSS parsing, dataset endpoint."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.services.news_sync_service as news_mod
from backend.config import TRUSTED_DOCS_DIR
from backend.main import app
from backend.services.document_processor import (
    process_document, parse_source_sections, detect_source_type, credibility_for
)
from backend.services.news_sync_service import parse_rss_xml

DOSSIERS = sorted(TRUSTED_DOCS_DIR.glob("*.txt"))


def test_dossiers_exist():
    assert len(DOSSIERS) >= 5


@pytest.mark.parametrize("path", DOSSIERS, ids=lambda p: p.name)
def test_every_dossier_section_is_sourced(path):
    sections = parse_source_sections(path.read_text(encoding="utf-8"))
    assert sections, "no sections parsed"
    for sec in sections:
        assert sec["source"], f"section without Source: {sec['text'][:60]}"
        assert re.match(r"^https://[a-z0-9.-]+\.[a-z]{2,}/", sec["url"]), sec["url"]
        assert sec["retrieval_date"] == "2026-10-05"
        assert sec["publication_date"] == "" or re.match(r"^\d{4}(-\d{2}-\d{2})?$", sec["publication_date"])


@pytest.mark.parametrize("path", DOSSIERS, ids=lambda p: p.name)
def test_no_invented_report_ids(path):
    # The old dossiers cited made-up references like "IEEE-CS-AI-771" / "GOV-INT-2025-LEADERSHIP"
    assert not re.search(r"Report Reference|Document Reference|\b[A-Z]{2,}-[A-Z]{2,}-\d{2,}", path.read_text(encoding="utf-8"))


def test_process_document_carries_section_metadata(tmp_path):
    doc = tmp_path / "sample.txt"
    doc.write_text(
        "Source: Example Agency - Fact page\n"
        "URL: https://www.example.gov/facts\n"
        "Published: 2026-01-02\n"
        "Retrieved: 2026-10-05\n"
        "Type: Government official\n\n"
        "The first sourced fact is long enough to become a chunk of evidence text.\n"
        "---\n"
        "Source: Example News - Report\n"
        "URL: https://news.example.com/report\n"
        "Published: not stated\n"
        "Retrieved: 2026-10-05\n\n"
        "The second sourced fact is also long enough to become its own evidence chunk.\n",
        encoding="utf-8",
    )
    chunks = process_document(doc, source_name="Fallback Name")
    assert len(chunks) == 2
    first, second = chunks
    assert first["source"] == "Example Agency - Fact page"
    assert first["url"] == "https://www.example.gov/facts"
    assert first["publication_date"] == "2026-01-02" and first["retrieval_date"] == "2026-10-05"
    assert first["credibility_score"] == pytest.approx(0.95)
    assert "Source:" not in first["text"] and "URL:" not in first["text"]
    assert second["source"] == "Example News - Report" and second["publication_date"] == ""
    assert second["source_type"] == "Established News"


def test_plain_upload_without_headers_unchanged(tmp_path):
    doc = tmp_path / "notes.txt"
    doc.write_text("Just some plain uploaded notes without any source header lines at all.", encoding="utf-8")
    chunks = process_document(doc, source_name="My Notes")
    assert len(chunks) == 1 and chunks[0]["source"] == "My Notes" and chunks[0]["url"] == ""


@pytest.mark.parametrize("name,expected", [
    ("fund_report.txt", "General Report"),          # "un" inside "fund" used to mean Government
    ("whole_story.txt", "General Report"),          # "who" inside "whole"
    ("who_fact_sheet.txt", "Government / Official"),
    ("reuters_article.txt", "Established News"),
])
def test_detect_source_type_whole_words(name, expected):
    assert detect_source_type(name) == expected


def test_credibility_for():
    assert credibility_for("Government / Official") == pytest.approx(0.95)
    assert credibility_for("personal blog") == pytest.approx(0.70)


def test_news_chunks_normalised(monkeypatch):
    captured = []
    monkeypatch.setattr(news_mod, "TRUSTED_RSS_FEEDS", [{"name": "Feed", "url": "https://x", "category": "C", "credibility": 98.0}])
    monkeypatch.setattr(news_mod.NewsSyncService, "fetch_rss_feed", lambda self, feed, max_items=15: [{
        "title": "Headline about something", "description": "A description long enough to index.",
        "full_content": "Headline about something. A description long enough to index.",
        "url": "https://news.example.com/a", "pub_date": "Mon, 05 Oct 2026 10:00:00 GMT",
        "source_name": "Feed", "category": "C", "credibility": 98.0}])
    monkeypatch.setattr(news_mod, "is_news_url_indexed", lambda url: False)
    monkeypatch.setattr(news_mod, "save_news_article", lambda **kw: "id")
    monkeypatch.setattr(news_mod.retrieval_service, "add_chunks", lambda chunks: captured.extend(chunks) or len(chunks))
    res = news_mod.news_sync_service.sync_live_news(max_per_feed=1)
    assert res["status"] == "success" and captured
    c = captured[0]
    assert c["credibility_score"] == pytest.approx(0.98)
    assert c["publication_date"] == "Mon, 05 Oct 2026 10:00:00 GMT" and "published_date" not in c
    assert c["retrieval_date"].startswith("20")


@pytest.mark.parametrize("prefix", [b"", b"\n\n\n", b"\xef\xbb\xbf", b"\xef\xbb\xbf  \r\n"])
def test_rss_parse_tolerates_leading_whitespace_and_bom(prefix):
    xml = prefix + b'<?xml version="1.0" encoding="UTF-8"?>\n<rss><channel><item><title>T</title></item></channel></rss>'
    root = parse_rss_xml(xml)
    assert root.find(".//item/title").text == "T"


def test_train_dataset_404_when_files_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(news_mod, "DATA_DIR", tmp_path)
    registered = []
    monkeypatch.setattr(news_mod, "save_document", lambda **kw: registered.append(kw))
    r = TestClient(app).post("/api/news/train-dataset")
    assert r.status_code == 404
    assert "True.csv" in r.json()["detail"]
    assert registered == []  # no fake 0-chunk "document"


def test_news_status_has_no_fake_counts(monkeypatch):
    monkeypatch.setattr(news_mod, "get_news_stats", lambda: {"total_articles": 0, "total_news_chunks": 0, "last_sync": "Never"})
    status = news_mod.news_sync_service.get_status()
    assert status["total_live_articles"] == 0 and status["total_news_chunks"] == 0
