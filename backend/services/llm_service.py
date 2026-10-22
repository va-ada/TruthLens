import json
import re
import time
import threading
import datetime
import requests
from typing import List, Dict, Any, Optional
from backend.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_FALLBACK_MODELS,
    GROQ_API_KEY,
    GROQ_MODEL,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    DEFAULT_LLM_PROVIDER,
    LLM_TIMEOUT_S
)
from backend import config as app_config
from backend.database.db import llm_budget_try_consume, llm_budget_used
from backend.models.schemas import Verdict, normalize_verdict, normalize_credibility
from backend.services.nlp.nli_evaluator import nli_evaluator, content_words, STANCE_THRESHOLD
from backend.services.orchestration import verdict_aggregator

SYSTEM_PROMPT = """You are an evidence-based fact verification system.
Decide whether the claim is true using ONLY the retrieved evidence below. Do not use outside knowledge.
Do not invent sources or facts. If the evidence does not settle the claim, say so.

TIME: Compare against the CURRENT REFERENCE DATE. A claim about the present ("X is the CEO", "the current PM")
is only SUPPORTED by evidence showing it is still true. If evidence shows it was true but no longer is, it is OUTDATED.
A claim explicitly about the past ("In 2018, X was ...") is judged against historical evidence.

EVIDENCE RELEVANCE: Judge the claim's literal factual content. A theory or model being "superseded" or refined
does not refute facts the newer understanding still includes. If the evidence is only tangential, answer
INSUFFICIENT_EVIDENCE rather than REFUTED. Only REFUTE when the evidence states something incompatible with the claim.

ENTITIES: Person, role and country/organisation must all match. A matching name with a different role or country
does not support the claim.

Verdicts:
- SUPPORTED: evidence confirms the claim is true now.
- SUPPORTED_HISTORICALLY: the claim is about the past and evidence confirms it.
- OUTDATED: the claim states a present fact that evidence shows only held in the past.
- REFUTED: evidence contradicts the claim.
- CONFLICTING: credible evidence points both ways.
- INSUFFICIENT_EVIDENCE: the evidence does not settle the claim.

Return ONLY a JSON object:
{
  "verdict": "SUPPORTED" | "SUPPORTED_HISTORICALLY" | "OUTDATED" | "REFUTED" | "CONFLICTING" | "INSUFFICIENT_EVIDENCE",
  "explanation": "<2-4 sentences: what the evidence says, past vs current, entity/country match>",
  "key_reasoning": "<short bullet points>",
  "entity_match": "Match" | "Mismatch" | "Unverified",
  "country_match": "Match" | "Mismatch" | "Not Applicable",
  "role_match": "Match" | "Mismatch" | "Not Applicable",
  "temporal_match": "Match" | "Mismatch" | "Unverified" | "Outdated",
  "chunk_classifications": [
    {"chunk_id": "<id>", "stance": "SUPPORTING" | "CONTRADICTING" | "NEUTRAL",
     "score": <0.0-1.0, how strongly this chunk takes that stance>,
     "rationale": "<one sentence>"}
  ]
}
"""

BUDGET_NOTE = "Daily cloud-judge budget reached"

PRESENT_TO_PAST = [(r"\bis\b", "was"), (r"\bare\b", "were"), (r"\bhas\b", "had"), (r"\bhave\b", "had")]
NOW_WORDS = re.compile(r"\b(the\s+)?(current(ly)?|now|today|presently|incumbent)\b\s*", re.IGNORECASE)


def to_past_tense(claim: str) -> str:
    """'Shinzo Abe is the current PM of Japan' -> 'Shinzo Abe was the PM of Japan' (for the OUTDATED check)."""
    text = NOW_WORDS.sub(lambda m: m.group(1) or "", claim)  # keep "The"/"the" as written
    for pattern, past in PRESENT_TO_PAST:
        new = re.sub(pattern, past, text, count=1, flags=re.IGNORECASE)
        if new != text:
            return re.sub(r"\s+", " ", new).strip()
    return re.sub(r"\s+", " ", text).strip()


class LLMService:
    def verify_with_llm(
        self,
        claim: str,
        evidence_chunks: List[Dict[str, Any]],
        provider: str = "auto",
        custom_api_key: Optional[str] = None,
        historical: bool = False,
        changes_over_time: bool = False
    ) -> Dict[str, Any]:
        """
        Judges the claim against the evidence. Tries the requested/configured cloud LLM(s) in order,
        then falls back to the offline NLI judge. Every result carries per-chunk stances.
        """
        if not evidence_chunks:
            return self._insufficient_evidence_response(
                claim, reason="No relevant documents or evidence chunks could be found."
            )

        requested = (provider or "auto").lower()
        if requested == "auto":
            requested = (DEFAULT_LLM_PROVIDER or "auto").lower()

        attempts = []
        if custom_api_key:
            if custom_api_key.startswith("gsk_"):
                attempts.append(("groq", custom_api_key))
            elif custom_api_key.startswith("sk-"):
                attempts.append(("openai", custom_api_key))
            else:
                attempts.append(("gemini", custom_api_key))
        if requested in ("auto", "gemini") and GEMINI_API_KEY:
            attempts.append(("gemini", GEMINI_API_KEY))
        if requested in ("auto", "groq") and GROQ_API_KEY:
            attempts.append(("groq", GROQ_API_KEY))
        if requested in ("auto", "openai") and OPENAI_API_KEY:
            attempts.append(("openai", OPENAI_API_KEY))
        if requested == "ollama":
            attempts.append(("ollama", None))

        callers = {"gemini": self._call_gemini, "groq": self._call_groq, "openai": self._call_openai}
        labels = {"gemini": f"Google Gemini ({GEMINI_MODEL})", "groq": f"Groq ({GROQ_MODEL})",
                  "openai": f"OpenAI ({OPENAI_MODEL})", "ollama": f"Ollama ({OLLAMA_MODEL})"}
        errors: List[str] = []
        # Process-wide daily cap on cloud calls (cost / free-tier protection); local Ollama is not counted
        cloud = [a for a in attempts if a[0] != "ollama"]
        if cloud and self._budget_exhausted():
            attempts = [a for a in attempts if a[0] == "ollama"]
            errors.append(BUDGET_NOTE)
        for name, key in attempts:
            res = self._call_ollama(claim, evidence_chunks) if name == "ollama" else callers[name](claim, evidence_chunks, key, errors)
            if res:
                res.setdefault("llm_provider_used", labels[name])
                return res

        res = self._offline_verify(claim, evidence_chunks, historical=historical, changes_over_time=changes_over_time)
        if BUDGET_NOTE in errors:
            res["judge_notes"] = [f"{BUDGET_NOTE}; used the offline judge."]
        elif attempts:
            # Say so when a configured cloud judge was skipped, instead of silently changing judges
            res["judge_notes"] = [f"Cloud judge unavailable ({'; '.join(dict.fromkeys(errors)) or 'no response'}); used the offline judge instead."]
        return res

    @staticmethod
    def _budget_exhausted() -> bool:
        limit = int(app_config.LLM_DAILY_BUDGET)
        return limit > 0 and llm_budget_used() >= limit

    # ------------------------------------------------------------------ cloud / local LLM calls

    # Transient server errors are retried once; 429 (rate limit) is not - waiting seconds rarely clears a
    # per-minute quota, so moving straight to the next model is faster
    RETRYABLE = {500, 502, 503, 504}

    # A model that answers 429 (quota or rate limit) is skipped for a while instead of being tried first on
    # every request: with a 20-requests/day free tier, each later claim otherwise paid an extra failing call.
    RATE_LIMIT_COOLDOWN_S = 600.0
    _cooldown_until: Dict[str, float] = {}
    _cooldown_lock = threading.Lock()

    def _cooling_down(self, name: str) -> bool:
        with self._cooldown_lock:
            return time.monotonic() < self._cooldown_until.get(name, 0.0)

    def _start_cooldown(self, name: str) -> None:
        with self._cooldown_lock:
            self._cooldown_until[name] = time.monotonic() + self.RATE_LIMIT_COOLDOWN_S

    def _post_with_retry(self, url: str, headers: dict, payload: dict, name: str, errors: list):
        """POST with one retry on transient server errors (2s backoff). Returns the response or None."""
        if self._cooling_down(name):
            errors.append(f"{name}: skipped (rate-limited recently)")
            return None
        for delay in (0, 2.0):
            if delay:
                time.sleep(delay)
            if not llm_budget_try_consume(int(app_config.LLM_DAILY_BUDGET)):
                errors.append(BUDGET_NOTE)
                return None
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=LLM_TIMEOUT_S)
            except Exception as e:
                errors.append(f"{name}: {type(e).__name__}")
                continue
            if resp.status_code == 200:
                return resp
            errors.append(f"{name}: HTTP {resp.status_code}")
            print(f"[LLMService] {name} returned HTTP {resp.status_code}: {resp.text[:160]}")
            if resp.status_code == 429:
                self._start_cooldown(name)
            if resp.status_code not in self.RETRYABLE:
                return None
        return None

    def _call_gemini(self, claim: str, chunks: List[Dict[str, Any]], api_key: str, errors: Optional[list] = None) -> Optional[Dict[str, Any]]:
        errors = errors if errors is not None else []
        headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
        payload = {
            "contents": [{"role": "user", "parts": [{"text": f"{SYSTEM_PROMPT}\n\n{self._build_prompt(claim, chunks)}"}]}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"}
        }
        # Primary model, then fallbacks (Gemini models get overloaded or retired)
        for model in [GEMINI_MODEL] + [m for m in GEMINI_FALLBACK_MODELS if m != GEMINI_MODEL]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            resp = self._post_with_retry(url, headers, payload, f"Gemini {model}", errors)
            if resp is None:
                continue
            try:
                text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError, ValueError):
                errors.append(f"Gemini {model}: empty/blocked response")
                continue
            result = self._parse_json_response(text, chunks)
            if result:
                result["llm_provider_used"] = f"Google Gemini ({model})"
                return result
            errors.append(f"Gemini {model}: unparseable JSON")
        return None

    def _call_openai_compatible(self, url: str, model: str, api_key: str, claim: str, chunks: List[Dict[str, Any]], name: str, errors: Optional[list] = None) -> Optional[Dict[str, Any]]:
        errors = errors if errors is not None else []
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": self._build_prompt(claim, chunks)}
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }
        resp = self._post_with_retry(url, headers, payload, name, errors)
        if resp is None:
            return None
        try:
            return self._parse_json_response(resp.json()["choices"][0]["message"]["content"], chunks)
        except (KeyError, IndexError, ValueError):
            errors.append(f"{name}: malformed response")
            return None

    def _call_groq(self, claim, chunks, api_key, errors=None):
        return self._call_openai_compatible("https://api.groq.com/openai/v1/chat/completions", GROQ_MODEL, api_key, claim, chunks, "Groq", errors)

    def _call_openai(self, claim, chunks, api_key, errors=None):
        return self._call_openai_compatible("https://api.openai.com/v1/chat/completions", OPENAI_MODEL, api_key, claim, chunks, "OpenAI", errors)

    def _call_ollama(self, claim: str, chunks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        try:
            payload = {
                "model": OLLAMA_MODEL,
                "prompt": f"{SYSTEM_PROMPT}\n\n{self._build_prompt(claim, chunks)}",
                "stream": False,
                "format": "json"
            }
            resp = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=60)
            if resp.status_code == 200:
                return self._parse_json_response(resp.json().get("response", ""), chunks)
        except Exception as e:
            print(f"[LLMService] Ollama call failed: {e}")
        return None

    def _build_prompt(self, claim: str, chunks: List[Dict[str, Any]]) -> str:
        current_time = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        prompt = f"CURRENT REFERENCE DATE: {current_time}\n\nCLAIM TO VERIFY:\n\"{claim}\"\n\nRETRIEVED EVIDENCE CHUNKS:\n"
        for i, c in enumerate(chunks, 1):
            prompt += f"\n--- Evidence Chunk {i} [ID: {c.get('chunk_id', 'unknown')}] ---\n"
            prompt += f"Source: {c.get('source', 'Unknown')}\n"
            if c.get("publication_date"):
                prompt += f"Publication Date: {c['publication_date']}\n"
            if c.get("retrieval_date"):
                prompt += f"Retrieval Date: {c['retrieval_date']}\n"
            prompt += f"Text:\n{c.get('text', '')}\n"
        return prompt

    def _parse_json_response(self, text: str, chunks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Parses an LLM JSON verdict. Returns None (so the next judge is tried) if it is unusable."""
        try:
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\n", "", cleaned)
                cleaned = re.sub(r"\n```$", "", cleaned)
            data = json.loads(cleaned)
        except Exception as e:
            print(f"[LLMService] Failed to parse JSON response ({e}): {text[:200]}")
            return None

        known_ids = {str(c.get("chunk_id")) for c in chunks}
        classifications = []
        for cls in data.get("chunk_classifications", []) or []:
            if str(cls.get("chunk_id")) not in known_ids:
                continue  # ignore chunk ids the model invented
            stance = str(cls.get("stance", "NEUTRAL")).upper()
            stance = stance if stance in ("SUPPORTING", "CONTRADICTING") else "NEUTRAL"
            try:
                score = max(0.0, min(1.0, float(cls.get("score", 0.75))))
            except (TypeError, ValueError):
                score = 0.75
            classifications.append({
                "chunk_id": str(cls.get("chunk_id")),
                "stance": stance,
                "score": score,
                "rationale": cls.get("rationale", "")
            })

        return {
            "verdict": normalize_verdict(data.get("verdict")),
            "explanation": data.get("explanation", ""),
            "key_reasoning": data.get("key_reasoning", ""),
            "entity_match": data.get("entity_match", "Unverified"),
            "country_match": data.get("country_match", "Not Applicable"),
            "role_match": data.get("role_match", "Not Applicable"),
            "temporal_match": data.get("temporal_match", "Unverified"),
            "chunk_classifications": classifications
        }

    # ------------------------------------------------------------------ offline judge

    def _offline_verify(self, claim: str, chunks: List[Dict[str, Any]], historical: bool = False,
                        changes_over_time: bool = False) -> Dict[str, Any]:
        """
        Offline judge: DeBERTa-v3 NLI per chunk (keyword rules only if the model cannot load),
        then the evidence-only aggregation in verdict_aggregator, then an OUTDATED check.
        """
        texts = [c.get("text", "") for c in chunks]
        try:
            stances = nli_evaluator.classify_chunks(claim, texts)
            engine = "Offline NLI (DeBERTa-v3 cross-encoder)"
        except RuntimeError:
            stances = [self._keyword_stance(claim, t) for t in texts]
            engine = "Offline keyword rules (NLI model unavailable - low accuracy)"

        classified = []
        for chunk, st in zip(chunks, stances):
            classified.append({
                "chunk_id": str(chunk.get("chunk_id", "")),
                "source": chunk.get("source") or chunk.get("document_name"),
                "credibility_score": normalize_credibility(chunk.get("credibility_score")),
                "stance": st["stance"],
                "score": st["score"],
                "rationale": st["rationale"]
            })

        verdict = verdict_aggregator.decide(classified, historical=historical)
        temporal_match = "Unverified"

        # A present-tense claim that is refuted but whose past-tense form is entailed is OUTDATED
        # (e.g. "Shinzo Abe is the current PM of Japan").
        # Only for facts that change over time (who holds a role, explicitly "current" claims); otherwise
        # "the Moon was made of cheese" style past-tense matches would turn myths into OUTDATED.
        if (verdict == Verdict.REFUTED.value and not historical and changes_over_time
                and engine.startswith("Offline NLI")):
            past = to_past_tense(claim)
            if past.lower() != claim.lower().strip() and nli_evaluator.entailed_with_end_signal(past, texts) >= STANCE_THRESHOLD:
                verdict = Verdict.OUTDATED.value
                temporal_match = "Outdated"

        entity_match = self._entity_match(claim, texts)
        sup = [c for c in classified if c["stance"] == "SUPPORTING"]
        con = [c for c in classified if c["stance"] == "CONTRADICTING"]
        return {
            "verdict": verdict,
            "explanation": self._offline_explanation(verdict, sup, con, len(classified)),
            "key_reasoning": " | ".join(c["rationale"] for c in (sup + con)[:3]) or "No retrieved passage entailed or contradicted the claim.",
            "entity_match": entity_match,
            "country_match": "Not Applicable",
            "role_match": "Not Applicable",
            "temporal_match": temporal_match,
            "chunk_classifications": classified,
            "llm_provider_used": engine
        }

    @staticmethod
    def _offline_explanation(verdict: str, sup: list, con: list, total: int) -> str:
        n_sup = len({c["source"] for c in sup})
        n_con = len({c["source"] for c in con})
        counts = f"{n_sup} source(s) support the claim and {n_con} contradict it, out of {total} passage(s) retrieved."
        text = {
            Verdict.SUPPORTED.value: "The retrieved evidence supports this claim.",
            Verdict.SUPPORTED_HISTORICALLY.value: "The retrieved evidence supports this claim about the past.",
            Verdict.REFUTED.value: "The retrieved evidence contradicts this claim.",
            Verdict.OUTDATED.value: "The evidence shows this was true in the past but is no longer the case.",
            Verdict.CONFLICTING.value: "The retrieved sources disagree about this claim.",
            Verdict.INSUFFICIENT_EVIDENCE.value: "The retrieved evidence neither confirms nor contradicts this claim.",
        }[verdict]
        return f"{text} {counts}"

    @staticmethod
    def _entity_match(claim: str, texts: List[str]) -> str:
        """Match if some passage names the claim's subject, Mismatch if none mention it at all."""
        m = re.split(r"\b(?:is|are|was|were|became|has|have|had|can|cannot)\b", claim.lower(), maxsplit=1)
        subject = content_words(m[0]) if len(m) == 2 else set()
        if not subject:
            return "Unverified"
        overlaps = [len(subject & content_words(t)) / len(subject) for t in texts]
        if any(o >= 0.7 for o in overlaps):
            return "Match"
        if all(o == 0 for o in overlaps):
            return "Mismatch"
        return "Unverified"

    @staticmethod
    def _keyword_stance(claim: str, text: str) -> Dict[str, Any]:
        """
        Last-resort stance when the NLI model is unavailable: content-word overlap plus explicit
        refutation phrases. Deliberately conservative - it rarely supports, and says it is a heuristic.
        """
        claim_words = content_words(claim)
        text_lower = (text or "").lower()
        overlap = len(claim_words & content_words(text_lower)) / max(1, len(claim_words))
        refutations = ("cannot cure", "cannot treat", "ineffective", "not effective", "no biological activity",
                       "zero biological activity", "debunked", "myth", "hoax", "false", "has not", "not overtaken")
        if overlap >= 0.35 and any(p in text_lower for p in refutations):
            return {"stance": "CONTRADICTING", "score": 0.6, "rationale": f"Keyword heuristic: refutation phrase with {overlap:.0%} term overlap."}
        if overlap >= 0.8:
            return {"stance": "SUPPORTING", "score": 0.6, "rationale": f"Keyword heuristic: {overlap:.0%} of claim terms present."}
        return {"stance": "NEUTRAL", "score": 0.0, "rationale": f"Keyword heuristic: {overlap:.0%} term overlap, no decisive wording."}

    def _insufficient_evidence_response(self, claim: str, reason: str) -> Dict[str, Any]:
        return {
            "verdict": Verdict.INSUFFICIENT_EVIDENCE.value,
            "explanation": f"Unable to verify the claim. {reason}",
            "key_reasoning": "No evidence was retrieved for this claim.",
            "entity_match": "Unverified",
            "country_match": "Not Applicable",
            "role_match": "Not Applicable",
            "temporal_match": "Unverified",
            "chunk_classifications": [],
            "llm_provider_used": "None (no evidence)"
        }


llm_service = LLMService()
