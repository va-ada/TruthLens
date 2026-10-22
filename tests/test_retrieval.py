"""Live Wikipedia retrieval: title candidates, passages, request budget, metadata. HTTP is mocked."""
import importlib
from urllib.parse import parse_qs, urlparse

import pytest

LS = importlib.import_module("backend.services.live_search_service")
svc = LS.live_search_service

ARTICLE = (
    "Lee Louis Daniels (born December 24, 1959) is an American filmmaker. He made his directorial debut with Shadowboxer.\n\n"
    "Early life\n"
    "Daniels was born in West Philadelphia. He attended Lindenwood University.\n\n"
    "Career\n"
    "Daniels directed Precious, a film based on the novel Push by Sapphire. Precious premiered in 2009. "
    "It won two Academy Awards. Mo'Nique won Best Supporting Actress for the film.\n\n"
    "Personal life\n"
    "Daniels lives in New York City with his family. He has two children.\n"
)


@pytest.mark.parametrize("claim,expected_first", [
    ("Brick (film) had 2005 viewers.", "Brick (film)"),
    ('Lee Daniels directed a film based on the novel "Push."', "Lee Daniels"),
    ("The Church of Jesus Christ of Latter-day Saints has a law of marriage.", "Church of Jesus Christ of Latter-day Saints"),
    ("Is Narendra Modi PM of India", "Narendra Modi"),
])
def test_title_candidates(claim, expected_first):
    cands = svc.title_candidates(claim)
    assert cands[0] == expected_first and len(cands) <= LS.MAX_TITLE_CANDIDATES


def test_split_passages_skips_headings_and_groups_sentences():
    passages = svc.split_passages(ARTICLE)
    assert all(p not in ("Early life", "Career", "Personal life") for p in passages)
    assert passages[0].startswith("Lee Louis Daniels (born December 24, 1959)")  # 'Jr.'-style abbreviations aside, lead intact
    assert all(len(LS.re.findall(r"[.!?](\s|$)", p)) <= LS.PASSAGE_SENTENCES for p in passages)


def test_select_passages_keeps_lead_and_most_relevant():
    picked = svc.select_passages('Lee Daniels directed a film based on the novel "Push."', ARTICLE)
    idx = [i for i, _ in picked]
    texts = [t for _, t in picked]
    assert idx[0] == 0 and len(picked) <= LS.PASSAGES_PER_PAGE
    assert any("novel Push" in t for t in texts)
    assert not any("two children" in t for t in texts)


def test_passage_id_is_stable():
    assert svc.passage_id("Lee Daniels", 2) == svc.passage_id("Lee Daniels", 2) != svc.passage_id("Lee Daniels", 3)


class FakeWiki:
    """Answers the three request kinds by inspecting query params; records every call."""
    def __init__(self):
        self.calls = []

    def __call__(self, params):
        self.calls.append(params)
        if params.get("list") == "search":
            q = params["srsearch"]
            return {"query": {"search": [{"title": f"{q} page {i}"} for i in range(3)]}}
        if params.get("prop") == "pageprops":
            titles = params["titles"].split("|")
            return {"query": {"pages": [{"title": titles[0]}] + [{"title": t, "missing": True} for t in titles[1:]]}}
        title = params["titles"]
        return {"query": {"pages": [{"title": title, "touched": "2026-10-01T00:00:00Z",
                                     "extract": ARTICLE.replace("Lee Louis Daniels", title)}]}}


def test_request_budget_and_metadata(monkeypatch):
    fake = FakeWiki()
    monkeypatch.setattr(svc, "_get_json", fake)
    queries = [(f"query {i}", "Potential Contradiction" if i == 5 else None) for i in range(8)]
    chunks = svc.fetch_for_queries("Lee Daniels directed a film based on Push.", queries)
    searches = [c for c in fake.calls if c.get("list") == "search"]
    extracts = [c for c in fake.calls if c.get("prop") == "extracts|info"]
    assert len(searches) <= LS.MAX_SEARCHES and len(extracts) <= LS.MAX_PAGES
    assert len(fake.calls) <= 1 + LS.MAX_SEARCHES + LS.MAX_PAGES
    titles = [c["document_name"] for c in chunks]
    assert titles[0] == "Wikipedia: Lee Daniels"  # exact title match ranked first
    c = chunks[0]
    assert c["url"] == "https://en.wikipedia.org/wiki/Lee_Daniels"
    assert c["publication_date"] == "2026-10-01T00:00:00Z" and c["retrieval_date"].endswith("Z")
    assert c["credibility_score"] == 0.80 and c["source_type"] == "Encyclopedia (Wikipedia)"
    assert len({x["chunk_id"] for x in chunks}) == len(chunks)


def test_duplicate_queries_and_titles_are_deduped(monkeypatch):
    fake = FakeWiki()
    monkeypatch.setattr(svc, "_get_json", fake)
    svc.fetch_for_queries("x y z", [("same", None), ("Same ", None), ("same", "Potential Contradiction")])
    assert len([c for c in fake.calls if c.get("list") == "search"]) == 1
    fetched = [c["titles"] for c in fake.calls if c.get("prop") == "extracts|info"]
    assert len(fetched) == len(set(fetched))


def test_contradiction_tag_carried(monkeypatch):
    fake = FakeWiki()
    monkeypatch.setattr(svc, "_get_json", fake)
    monkeypatch.setattr(svc, "title_candidates", lambda claim: [])
    chunks = svc.fetch_for_queries("a b c", [("former role", "Potential Contradiction")])
    assert chunks and all(c.get("support_type") == "Potential Contradiction" for c in chunks)


def test_network_failure_falls_back_quietly(monkeypatch):
    def boom(params):
        raise OSError("offline")
    monkeypatch.setattr(svc, "_get_json", boom)
    monkeypatch.setattr(svc, "_duckduckgo", lambda claim, ts: [])
    assert svc.fetch_for_queries("Lee Daniels directed Precious", [("Lee Daniels", None)]) == []


# --- Resilience: one retry, then failures are counted and surfaced (not silently "no evidence") ---

import io
import importlib
import urllib.error

LS = importlib.import_module("backend.services.live_search_service")


class _Resp(io.BytesIO):
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_get_json_retries_once_on_timeout(monkeypatch):
    calls = []

    def flaky(req, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("read timed out")
        return _Resp(b'{"query": {"search": []}}')
    monkeypatch.setattr(LS.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(LS.time, "sleep", lambda s: None)
    assert LS.live_search_service._get_json({"action": "query"}) == {"query": {"search": []}}
    assert len(calls) == 2


def test_get_json_gives_up_after_second_failure(monkeypatch):
    def down(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 503, "busy", {"Retry-After": "1"}, None)
    monkeypatch.setattr(LS.urllib.request, "urlopen", down)
    monkeypatch.setattr(LS.time, "sleep", lambda s: None)
    with pytest.raises(urllib.error.HTTPError):
        LS.live_search_service._get_json({"action": "query"})


def test_failures_are_reported_to_caller(monkeypatch):
    def boom(params):
        raise TimeoutError("timed out")
    monkeypatch.setattr(LS.live_search_service, "_get_json", boom)
    monkeypatch.setattr(LS.live_search_service, "_duckduckgo", lambda claim, at: [])
    failures = []
    out = LS.live_search_service.fetch_for_queries("Zac Efron was born in 1987.", [("Zac Efron", None)], failures=failures)
    assert out == [] and failures and set(failures) == {"TimeoutError"}


def test_wikipedia_responses_are_cached(monkeypatch):
    calls = []

    def once(req, timeout=None):
        calls.append(req.full_url)
        return _Resp(b'{"query": {"search": [{"title": "X"}]}}')
    monkeypatch.setattr(LS, "WIKI_CACHE_TTL_S", 60.0)
    LS._wiki_cache.clear()
    monkeypatch.setattr(LS.urllib.request, "urlopen", once)
    a = LS.live_search_service._get_json({"action": "query", "srsearch": "cache test"})
    b = LS.live_search_service._get_json({"action": "query", "srsearch": "cache test"})
    assert a == b and len(calls) == 1
    LS._wiki_cache.clear()


def test_inflight_requests_are_capped(monkeypatch):
    import threading as th
    import time as tm
    active, peak, lock = [0], [0], th.Lock()

    def slow(req, timeout=None):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        tm.sleep(0.05)
        with lock:
            active[0] -= 1
        return _Resp(b'{"query": {}}')
    monkeypatch.setattr(LS.urllib.request, "urlopen", slow)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(lambda i: LS.live_search_service._get_json({"q": i}), range(24)))
    assert peak[0] <= LS.WIKI_MAX_INFLIGHT
