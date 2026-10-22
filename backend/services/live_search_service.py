import os
import re
import threading
from collections import OrderedDict
import gzip
import json
import hashlib
import time
import urllib.error
from backend.config import OPERATOR_CONTACT
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

WIKI_API = "https://en.wikipedia.org/w/api.php"
REQUEST_TIMEOUT_S = 5
MAX_CONCURRENT_REQUESTS = 4   # Wikimedia etiquette: keep parallelism low
MAX_SEARCHES = 4              # full-text searches per claim
MAX_PAGES = 6                 # article extracts per claim  (total requests <= 1 + 4 + 6 = 11)
MAX_TITLE_CANDIDATES = 4
SEARCH_LIMIT = 3
PAGE_CHARS = 6000             # plain-text characters fetched per article
PASSAGE_SENTENCES = 3
PASSAGES_PER_PAGE = 3

# Shared across all requests in this process (Wikipedia answered HTTP 429 when two benchmark processes
# each ran their own pool of 4): at most WIKI_MAX_INFLIGHT requests in flight, and identical API calls
# are served from a TTL cache (popular pages recur across claims).
WIKI_MAX_INFLIGHT = int(os.getenv("WIKI_MAX_INFLIGHT", "4"))
WIKI_CACHE_TTL_S = float(os.getenv("WIKI_CACHE_TTL_S", "21600"))
WIKI_CACHE_MAX = 2000
_WIKI_INFLIGHT = threading.BoundedSemaphore(WIKI_MAX_INFLIGHT)
_wiki_cache: "OrderedDict[str, Tuple[float, Any]]" = OrderedDict()
_wiki_cache_lock = threading.Lock()


def _wiki_cache_get(url: str):
    if WIKI_CACHE_TTL_S <= 0:
        return None
    with _wiki_cache_lock:
        hit = _wiki_cache.get(url)
        if hit and time.monotonic() - hit[0] < WIKI_CACHE_TTL_S:
            _wiki_cache.move_to_end(url)
            return hit[1]
        _wiki_cache.pop(url, None)
    return None


def _wiki_cache_put(url: str, data: Any) -> None:
    if WIKI_CACHE_TTL_S <= 0:
        return
    with _wiki_cache_lock:
        _wiki_cache[url] = (time.monotonic(), data)
        _wiki_cache.move_to_end(url)
        while len(_wiki_cache) > WIKI_CACHE_MAX:
            _wiki_cache.popitem(last=False)


class LiveSearchService:
    """
    Real-time Knowledge Grounding and Open Encyclopedia Evidence Retriever.
    Provides dynamic fallback and cross-verification for out-of-vault entities,
    institutions, breaking events, and general factual claims.
    """
    def __init__(self):
        self.headers = {
            # Wikimedia User-Agent policy: tool name/version + a way to contact the operator
            'User-Agent': f'TruthLens/2.1 (evidence-based fact checking; contact: {OPERATOR_CONTACT}) python-urllib'
        }
        self.common_typo_map = {
            r'\binsititue\b': 'institute',
            r'\binsitute\b': 'institute',
            r'\bcolledge\b': 'college',
            r'\buniveristy\b': 'university',
            r'\bprimeminister\b': 'prime minister',
            r'\bpersident\b': 'president',
            r'\bgoverment\b': 'government',
            r'\btechnolgy\b': 'technology'
        }

    def clean_and_correct_query(self, query: str) -> str:
        corrected = query.strip()
        for typo, fix in self.common_typo_map.items():
            corrected = re.sub(typo, fix, corrected, flags=re.IGNORECASE)
        return corrected

    def extract_search_phrases(self, query: str) -> List[str]:
        cleaned = self.clean_and_correct_query(query)
        
        # Remove question words at the start
        cleaned_no_q = re.sub(r'^(Is|Are|Was|Were|Did|Do|Does|Can|Could|Who|What|Where|When|Why|How)\b\s+', '', cleaned, flags=re.IGNORECASE)
        phrases = [cleaned_no_q]
        
        # Extract potential named entities (capitalized word sequences)
        entities = re.findall(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', cleaned)
        for ent in entities:
            if len(ent) > 3 and ent not in phrases:
                phrases.append(ent)

        # Fallback keyword extraction
        stopwords = {"is", "are", "was", "were", "in", "on", "at", "the", "a", "an", "of", "and", "or", "to", "for", "by", "with", "from", "that", "this"}
        tokens = [w for w in re.findall(r'\b[a-zA-Z0-9]{3,}\b', cleaned) if w.lower() not in stopwords]
        if tokens:
            kw_phrase = " ".join(tokens)
            if kw_phrase not in phrases:
                phrases.append(kw_phrase)

        return phrases

    # ------------------------------------------------------------------ Wikipedia passage retrieval

    def fetch_live_evidence(self, claim: str, max_results: int = 4) -> List[Dict[str, Any]]:
        """Single-query convenience wrapper around fetch_for_queries."""
        return self.fetch_for_queries(claim, [(claim, None)], max_pages=max_results)

    def fetch_for_queries(self, claim: str, queries: List[Tuple[str, Optional[str]]],
                          max_pages: int = MAX_PAGES, failures: Optional[list] = None) -> List[Dict[str, Any]]:
        """
        Retrieves Wikipedia evidence for a claim from several queries with a bounded request budget:
          1. one exact-title lookup for entity names in the claim ("Brick (film)", "Lee Daniels"),
          2. one full-text search per query (at most MAX_SEARCHES),
          3. one plain-text extract per selected page (at most max_pages, fetched in parallel),
        then splits each page into short passages and keeps those most relevant to the claim.
        The summary lead alone often lacks the supporting sentence (FEVER: 22/50 true claims came
        back NOT ENOUGH INFO), so passages come from deeper in the article as well.
        """
        retrieved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        searches = [(q, tag) for q, tag in self._dedupe_queries(queries)][:MAX_SEARCHES]

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as pool:
            exact_job = pool.submit(self._exact_titles, self.title_candidates(claim))
            search_jobs = [(tag, pool.submit(self._search_titles, q)) for q, tag in searches]
            exact = self._result(exact_job, [], failures)
            searched = [(tag, self._result(job, [], failures)) for tag, job in search_jobs]

        # Exact title matches first, then search results interleaved by rank across queries
        ordered: List[Tuple[str, Optional[str]]] = [(t, None) for t in exact]
        for rank in range(SEARCH_LIMIT):
            for tag, titles in searched:
                if rank < len(titles):
                    ordered.append((titles[rank], tag))
        pages, seen = [], set()
        for title, tag in ordered:
            key = title.lower()
            if key not in seen:
                seen.add(key)
                pages.append((title, tag))
            if len(pages) >= max_pages:
                break

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as pool:
            page_jobs = [(pt, pool.submit(self._fetch_page, pt[0])) for pt in pages]
            fetched = [(pt, self._result(job, None, failures)) for pt, job in page_jobs]

        chunks: List[Dict[str, Any]] = []
        for (title, tag), page in fetched:
            if not page:
                continue
            for idx, passage in self.select_passages(claim, page["text"]):
                chunk = {
                    "chunk_id": self.passage_id(page["title"], idx),
                    "document_name": f"Wikipedia: {page['title']}",
                    "source": f"Wikipedia Global Encyclopedia ({page['title']})",
                    "source_type": "Encyclopedia (Wikipedia)",
                    "page_number": idx + 1,
                    "text": passage,
                    "credibility_score": 0.80,
                    "url": page["url"],
                    "publication_date": page["touched"],
                    "retrieval_date": retrieved_at,
                    "is_live_retrieved": True
                }
                if tag:
                    chunk["support_type"] = tag
                chunks.append(chunk)

        if not chunks:
            chunks = self._duckduckgo(claim, retrieved_at)
        return chunks

    @staticmethod
    def passage_id(title: str, idx: int) -> str:
        """Stable id: same article passage -> same id across requests and processes."""
        return f"live-wiki-{hashlib.sha1(f'{title}#{idx}'.encode()).hexdigest()[:12]}"

    @staticmethod
    def _result(job, default, failures: Optional[list] = None):
        try:
            return job.result()
        except Exception as e:
            print(f"[LiveSearch] Wikipedia request failed after retry: {type(e).__name__}: {str(e)[:120]}")
            if failures is not None:
                failures.append(type(e).__name__)
            return default

    @staticmethod
    def _dedupe_queries(queries):
        seen, out = set(), []
        for q, tag in queries:
            k = (q or "").strip().lower()
            if k and k not in seen:
                seen.add(k)
                out.append((q.strip(), tag))
        return out

    def _get_json(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        GET the MediaWiki API with one retry on timeouts, connection errors, 429 and 5xx (honouring a short
        Retry-After). Under concurrent load single requests time out now and then; without the retry those
        claims silently came back NOT ENOUGH INFO (FEVER fell from 62.7% to 48.7% with two parallel runs).
        """
        url = f"{WIKI_API}?{urllib.parse.urlencode({**params, 'format': 'json', 'formatversion': 2})}"
        cached = _wiki_cache_get(url)
        if cached is not None:
            return cached
        req = urllib.request.Request(url, headers={**self.headers, "Accept-Encoding": "gzip"})
        for attempt in (1, 2):
            try:
                # Process-wide cap on in-flight Wikipedia requests, however many users verify at once
                with _WIKI_INFLIGHT:
                    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                        raw = resp.read()
                        if resp.headers.get("Content-Encoding") == "gzip":
                            raw = gzip.decompress(raw)
                data = json.loads(raw.decode("utf-8"))
                _wiki_cache_put(url, data)
                return data
            except urllib.error.HTTPError as e:
                if attempt == 2 or not (e.code == 429 or e.code >= 500):
                    raise
                try:
                    delay = min(5.0, float(e.headers.get("Retry-After") or 1.0))
                except ValueError:
                    delay = 1.0
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt == 2:
                    raise
                time.sleep(0.3)

    @staticmethod
    def title_candidates(claim: str) -> List[str]:
        """
        Likely page titles named in the claim: a leading 'Name (qualifier)' or the leading run of
        Title-case words ('Lee Daniels directed ...' -> 'Lee Daniels'), plus any other capitalised run.
        """
        text = re.sub(r'^(Is|Are|Was|Were|Did|Do|Does|Can|Could|The)\s+', '', claim.strip())
        cands = []
        paren = re.match(r"^([A-Z][^()]{1,60}?\s*\([^)]{2,40}\))", text)
        if paren:
            cands.append(paren.group(1).strip())
        for run in re.findall(r"((?:[A-Z][\w'.\-]*|of|the|and|de|von)(?:\s+(?:[A-Z][\w'.\-]*|of|the|and|de|von))*)", text):
            run = re.sub(r"\s+(of|the|and|de|von)$", "", run.strip())
            if len(run) > 2 and run.lower() not in {"the", "a", "an"}:
                # The bare name first ("Narendra Modi" from "Narendra Modi PM of India"), then the full run;
                # connectors are kept so "Church of Jesus Christ of ..." stays whole
                name = []
                for w in run.split():
                    if w.isupper() and len(w) > 1:  # acronym/title like "PM", "CEO" ends the name
                        break
                    name.append(w)
                if name and len(name) < len(run.split()):
                    cands.append(" ".join(name).rstrip("."))
                cands.append(run.rstrip("."))
        out, seen = [], set()
        for c in cands:
            if c.lower() not in seen:
                seen.add(c.lower())
                out.append(c)
        return out[:MAX_TITLE_CANDIDATES]

    def _exact_titles(self, candidates: List[str]) -> List[str]:
        """One request: which candidates are real pages (following redirects), skipping disambiguation pages."""
        if not candidates:
            return []
        data = self._get_json({"action": "query", "titles": "|".join(candidates), "redirects": 1,
                               "prop": "pageprops", "ppprop": "disambiguation"})
        pages = data.get("query", {}).get("pages", [])
        found = {p["title"] for p in pages if not p.get("missing") and not p.get("invalid")
                 and "disambiguation" not in (p.get("pageprops") or {})}
        # keep the claim's order: map candidates through normalisation/redirects
        mapping = {}
        for entry in data.get("query", {}).get("normalized", []) + data.get("query", {}).get("redirects", []):
            mapping[entry["from"]] = entry["to"]
        ordered = []
        for c in candidates:
            t = mapping.get(mapping.get(c, c), mapping.get(c, c))
            if t in found and t not in ordered:
                ordered.append(t)
        return ordered

    def _search_titles(self, query: str) -> List[str]:
        data = self._get_json({"action": "query", "list": "search", "srsearch": self.clean_and_correct_query(query),
                               "srlimit": SEARCH_LIMIT, "srprop": ""})
        return [r["title"] for r in data.get("query", {}).get("search", [])]

    def _fetch_page(self, title: str) -> Optional[Dict[str, str]]:
        # Network errors propagate to fetch_for_queries, which counts them as failures
        data = self._get_json({"action": "query", "prop": "extracts|info", "titles": title, "redirects": 1,
                               "explaintext": 1, "exsectionformat": "plain", "exchars": PAGE_CHARS})
        pages = data.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing"):
            return None
        page = pages[0]
        text = page.get("extract") or ""
        if len(text.strip()) < 30:
            return None
        real_title = page.get("title", title)
        return {"title": real_title, "text": text, "touched": page.get("touched", ""),
                "url": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(real_title.replace(' ', '_'))}"}

    @staticmethod
    def split_passages(text: str) -> List[str]:
        """Plain-text article -> passages of up to PASSAGE_SENTENCES sentences, never crossing paragraphs."""
        from backend.services.nlp.nli_evaluator import split_sentences
        passages = []
        for para in re.split(r"\n\s*\n|\n", text):
            para = para.strip()
            if len(para) < 40 or para.endswith(":"):
                continue  # headings, captions, list lead-ins
            sents = [s for s in split_sentences(para) if s.strip()]
            for i in range(0, len(sents), PASSAGE_SENTENCES):
                passage = " ".join(sents[i:i + PASSAGE_SENTENCES]).strip()
                if passage.endswith("...") or passage.endswith("…"):
                    passage = passage.rstrip(".… ")  # exchars truncation marker
                if len(passage) >= 40:
                    passages.append(passage)
        return passages

    @classmethod
    def select_passages(cls, claim: str, text: str) -> List[Tuple[int, str]]:
        """The lead passage plus the passages sharing the most vocabulary with the claim."""
        from backend.services.nlp.nli_evaluator import content_words
        passages = cls.split_passages(text)
        if not passages:
            return []
        claim_words = content_words(claim)
        scored = sorted(((len(claim_words & content_words(p)), -i, i) for i, p in enumerate(passages[1:], start=1)),
                        reverse=True)
        keep = [0] + [i for overlap, _, i in scored if overlap > 0][:PASSAGES_PER_PAGE - 1]
        return [(i, passages[i]) for i in sorted(set(keep))]

    def _duckduckgo(self, claim: str, retrieved_at: str) -> List[Dict[str, Any]]:
        """DuckDuckGo instant-answer fallback when Wikipedia returned nothing."""
        try:
            clean_q = self.clean_and_correct_query(claim)
            ddg_url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(clean_q)}&format=json&no_html=1&skip_disambig=1"
            req_ddg = urllib.request.Request(ddg_url, headers=self.headers)
            with urllib.request.urlopen(req_ddg, timeout=REQUEST_TIMEOUT_S) as resp:
                ddg_data = json.loads(resp.read().decode('utf-8'))
            abstract = ddg_data.get("AbstractText", "")
            heading = ddg_data.get("Heading", "Open Web Summary")
            if abstract:
                return [{
                    "chunk_id": f"live-ddg-{hashlib.sha1(heading.encode()).hexdigest()[:10]}",
                    "document_name": f"Web Knowledge Base: {heading}",
                    "source": f"Live Web Knowledge Base ({heading})",
                    "source_type": "Web Summary (DuckDuckGo)",
                    "page_number": 1,
                    "text": abstract,
                    "credibility_score": 0.70,
                    "url": ddg_data.get("AbstractURL", ""),
                    "publication_date": "",
                    "retrieval_date": retrieved_at,
                    "is_live_retrieved": True
                }]
        except Exception:
            pass
        return []


live_search_service = LiveSearchService()
