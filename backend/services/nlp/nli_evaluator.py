import os
import re
from typing import Any, Dict, List, Optional, Set

import numpy as np

from backend.services.ml_runtime import MODEL_LOCK

# Base is more accurate; small is ~2x faster on CPU-only servers (see deploy/DEPLOY.md, "Capacity")
NLI_MODEL_NAME = os.getenv("NLI_MODEL", "cross-encoder/nli-deberta-v3-base")
STANCE_THRESHOLD = 0.60      # minimum class probability to call a chunk SUPPORTING / CONTRADICTING
MAX_WINDOWS_PER_CHUNK = 12
MIN_CONTRADICTION_COVERAGE = 0.5  # share of the claim's key terms a sentence must contain to count as contradicting

# NLI scores "X is a myth that the Moon is cheese" as ENTAILING "the Moon is cheese" because the claim is
# quoted inside. Framing words tell us the sentence reports the claim rather than asserting it.
DEBUNK_CUES = re.compile(
    r"\b(myths?|misconceptions?|hoax(es)?|fanciful|debunked|falsely|false|conspiracy\s+theor(y|ies)|folklore|"
    r"urban\s+legends?|pseudo-?scien\w*|satir\w*|fictional|unfounded|disproven|disproved|no\s+evidence)\b", re.IGNORECASE)
REPORT_CUES = re.compile(
    r"\b(claimed|claims\s+that|alleged(ly)?|rumou?rs?|purported(ly)?|belief\s+that|believed\s+that|it\s+is\s+said)\b", re.IGNORECASE)

_STOPWORDS = {
    "the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "is", "are", "was", "were", "of",
    "with", "by", "that", "this", "it", "as", "from", "be", "has", "have", "had", "its", "will",
    "been", "can", "not", "current", "currently", "now", "today", "like"
}


def content_words(text: str) -> Set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", text.lower()) if w not in _STOPWORDS}


def framing(window: str) -> Optional[str]:
    """'debunk' if the sentence frames something as false, 'report' if it only reports a claim, else None."""
    if DEBUNK_CUES.search(window):
        return "debunk"
    if REPORT_CUES.search(window):
        return "report"
    return None


def coverage(claim_words: Set[str], window: str) -> float:
    return len(claim_words & content_words(window)) / max(1, len(claim_words))


# Periods that do not end a sentence ("Biden Jr. is", "Dr. Smith", "U.S. Army", "J. R. R. Tolkien")
_ABBREVIATION_END = re.compile(r"(?:\b(?:Jr|Sr|Dr|Mr|Mrs|Ms|Prof|St|Mt|Gen|Col|Lt|Sgt|Rev|Hon|No|vs|etc|Inc|Ltd|Co|Corp|approx)|\b[A-Z])\.$")


def split_sentences(text: str) -> List[str]:
    sentences: List[str] = []
    for line in re.split(r"\n+", text):
        current = ""
        for piece in re.split(r"(?<=[.!?])\s+", line):
            current = f"{current} {piece}".strip() if current else piece
            if not _ABBREVIATION_END.search(current):
                sentences.append(current)
                current = ""
        if current:
            sentences.append(current)
    return sentences


def sentence_windows(text: str) -> List[str]:
    """Single sentences plus adjacent pairs, so a fact split across two sentences still entails."""
    sentences = [s.strip() for s in split_sentences(text) if len(s.strip()) > 15]
    windows = list(sentences)
    windows += [f"{a} {b}" for a, b in zip(sentences, sentences[1:])]
    if not windows and text.strip():
        windows = [text.strip()]
    return windows[:MAX_WINDOWS_PER_CHUNK]


# --- Year-in-range reasoning ---------------------------------------------------------------
# NLI models cannot do date arithmetic: "Biden was President in 2023" vs "served from 2021 to 2025"
# comes out as a 0.99 CONTRADICTION. For windows that state a year RANGE, we instead check whether the
# claim minus its year is entailed, then whether the claimed year falls inside the stated range.
YEAR = r"(1[5-9]\d{2}|20\d{2})"
CLAIM_YEAR_PHRASE = re.compile(rf"\s*,?\s*\b(in|during|as\s+of|by)\s+{YEAR}\b\s*,?", re.IGNORECASE)
EXPLICIT_RANGE = re.compile(rf"\b{YEAR}\s*(?:–|—|-|to|until|till|through)\s*({YEAR[1:-1]}|present|now)\b", re.IGNORECASE)
SINCE_YEAR = re.compile(rf"\bsince\s+(?:[A-Za-z]+\s+){{0,2}}(?:\d{{1,2}},?\s+)?{YEAR}\b", re.IGNORECASE)
ENDED_SIGNAL = re.compile(r"\b(former(ly)?|until|succeeded\s+by|was\s+replaced|resigned|stepped\s+down|left\s+office|"
                          r"term\s+ended|ex-|died|assassinated|retired|no\s+longer)\b", re.IGNORECASE)
TENURE_WORDS = re.compile(r"\b(office|term|served|serving|tenure|ended|until|left|resigned|succeeded)\b", re.IGNORECASE)


def split_claim_year(hypothesis: str):
    """('Joe Biden was the President of the United States in 2023') -> (2023, 'Joe Biden was the President of the United States')."""
    years = set(re.findall(rf"\b{YEAR}\b", hypothesis))
    if len(years) != 1:
        return None, hypothesis
    yearless = CLAIM_YEAR_PHRASE.sub(" ", hypothesis).strip(" ,.")
    if yearless == hypothesis.strip(" ,."):
        return None, hypothesis
    return int(years.pop()), re.sub(r"\s+", " ", yearless)


def year_ranges(window: str, now_year: int):
    ranges = []
    for a, b in EXPLICIT_RANGE.findall(window):
        ranges.append((int(a), now_year if b.lower() in ("present", "now") else int(b)))
    for a in SINCE_YEAR.findall(window):
        ranges.append((int(a), now_year))
    if not ranges:
        years = sorted({int(y) for y in re.findall(rf"\b{YEAR}\b", window)})
        if len(years) == 2 and TENURE_WORDS.search(window):
            ranges.append((years[0], years[1]))
    return [(a, b) for a, b in ranges if a <= b]


class NLIEvaluator:
    """
    Zero-shot Natural Language Inference with a DeBERTa-v3 cross-encoder
    (He et al., 2021; checkpoint trained on SNLI + MultiNLI by sentence-transformers).
    Premise = evidence sentence(s), hypothesis = the claim stated as an assertion.
    """
    _instance = None
    _model = None
    _labels: Dict[str, int] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(NLIEvaluator, cls).__new__(cls)
        return cls._instance

    def _load_model(self):
        with MODEL_LOCK:
            self._load_model_locked()

    def _load_model_locked(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers.cross_encoder import CrossEncoder
            print(f"[NLIEvaluator] Loading NLI model {NLI_MODEL_NAME}...")
            try:
                self._model = CrossEncoder(NLI_MODEL_NAME, local_files_only=True)
            except Exception:
                self._model = CrossEncoder(NLI_MODEL_NAME)
            # Evidence windows are 1-2 sentences; 256 tokens never truncates them and is ~15% faster than 512
            self._model.max_length = 256
            # Read the label order from the checkpoint instead of hard-coding it
            id2label = self._model.model.config.id2label
            self._labels = {str(name).lower(): int(idx) for idx, name in id2label.items()}
            print(f"[NLIEvaluator] NLI model loaded. Labels: {self._labels}")
        except Exception as e:
            print(f"[NLIEvaluator] NLI model unavailable ({e}). Offline judge will use keyword rules.")
            self._model = "fallback"

    def available(self) -> bool:
        self._load_model()
        return self._model != "fallback"

    def _normalize_claim(self, claim: str) -> str:
        """
        Converts question-form claims into declarative assertions so the NLI model
        evaluates entailment instead of treating a question as neutral.
        'Is Narendra Modi PM of India' -> 'Narendra Modi is PM of India'
        """
        c = claim.strip().rstrip("?.! ")
        words = c.split()
        if len(words) >= 3 and words[0].lower() in {"is", "was", "are", "were"}:
            verb, rest = words[0].lower(), words[1:]
            # Put the verb back after the subject: 'the X' / 'a X', else the leading Title-case
            # name ('Narendra Modi', 'India'); all-caps tokens like 'PM' are not part of a name
            if rest[0].lower() in {"the", "a", "an"}:
                split = 2
            else:
                split = 0
                while split < len(rest) - 1 and rest[split][:1].isupper() and not rest[split].isupper():
                    split += 1
                split = max(split, 1)
            return f"{' '.join(rest[:split])} {verb} {' '.join(rest[split:])}".strip()
        return c

    def _probabilities(self, pairs: List[List[str]]) -> np.ndarray:
        # Batch similar lengths together (less padding), then restore the caller's order
        order = sorted(range(len(pairs)), key=lambda i: len(pairs[i][0]) + len(pairs[i][1]))
        with MODEL_LOCK:
            sorted_logits = np.asarray(self._model.predict([pairs[i] for i in order], batch_size=16, show_progress_bar=False))
        if sorted_logits.ndim == 1:
            sorted_logits = sorted_logits.reshape(1, -1)
        logits = np.empty_like(sorted_logits)
        logits[order] = sorted_logits
        exp = np.exp(logits - logits.max(axis=1, keepdims=True))
        return exp / exp.sum(axis=1, keepdims=True)

    def classify_chunks(self, claim: str, texts: List[str]) -> List[Dict[str, Any]]:
        """
        Stance of each evidence text toward the claim. Each text is split into sentence windows;
        the strongest entailing / contradicting window decides. A contradiction only counts if the window
        covers at least half the claim's key terms; myth/hoax framing turns entailment into contradiction;
        sentences that merely report a claim ("it was claimed that ...") are ignored for support.
        """
        if not texts:
            return []
        self._load_model()
        if self._model == "fallback":
            raise RuntimeError("NLI model unavailable")

        hypothesis = self._normalize_claim(claim)
        claim_words = content_words(hypothesis)
        pairs, owners, windows = [], [], []
        for i, text in enumerate(texts):
            for w in sentence_windows(text or ""):
                pairs.append([w, hypothesis])
                owners.append(i)
                windows.append(w)

        results = [{"stance": "NEUTRAL", "score": 0.0, "rationale": "No readable evidence text.", "best_sentence": ""} for _ in texts]
        if not pairs:
            return results

        probs = self._probabilities(pairs)
        ent_i, con_i, neu_i = self._labels["entailment"], self._labels["contradiction"], self._labels["neutral"]

        # Year-in-range override for windows that state a date range (see split_claim_year)
        date_override: Dict[int, tuple] = {}
        claim_year, yearless = split_claim_year(hypothesis)
        if claim_year:
            from datetime import datetime
            now_year = datetime.now().year
            # Windows with a stated range, plus undated windows that "contradict" the dated claim
            # (an undated sentence can only contradict it if it contradicts the claim minus its year)
            checks = []
            for k, w in enumerate(windows):
                ranges = year_ranges(w, now_year)
                undated = not re.search(rf"\b{YEAR}\b", w)
                if ranges or (undated and float(probs[k][con_i]) >= STANCE_THRESHOLD):
                    checks.append((k, ranges))
            if checks:
                yl_probs = self._probabilities([[windows[k], yearless] for k, _ in checks])
                for (k, ranges), row in zip(checks, yl_probs):
                    p_ent = float(row[ent_i])
                    if p_ent < STANCE_THRESHOLD:
                        continue
                    if ranges:
                        inside = any(a <= claim_year <= b for a, b in ranges)
                        span = ", ".join(f"{a}-{b}" for a, b in ranges)
                        date_override[k] = (inside, p_ent, span)
                    else:
                        date_override[k] = (None, p_ent, "")  # agrees apart from the year: neutral on time

        best: Dict[int, Dict[str, Any]] = {}
        for k, (row, owner, window) in enumerate(zip(probs, owners, windows)):
            b = best.setdefault(owner, {"ent": 0.0, "ent_s": "", "con": 0.0, "con_s": "", "con_why": "", "neu": 0.0})
            ent, con = float(row[ent_i]), float(row[con_i])
            if k in date_override:
                inside, p_ent, span = date_override[k]
                if inside is None:
                    pass  # undated window that matches everything except the year: no stance on the claim
                elif inside and p_ent > b["ent"]:
                    b["ent"], b["ent_s"] = p_ent, f"{window} [claimed year {claim_year} is within {span}]"
                elif not inside and p_ent > b["con"]:
                    b["con"], b["con_s"], b["con_why"] = p_ent, window, f"dates this to {span}, not {claim_year}; it"
                b["neu"] = max(b["neu"], float(row[neu_i]))
                continue
            frame = framing(window)
            if frame == "debunk" and ent >= STANCE_THRESHOLD:
                # "It is a myth that <claim>": the sentence entails the quoted claim but asserts it is false
                if ent > b["con"]:
                    b["con"], b["con_s"], b["con_why"] = ent, window, "frames the claim as false/myth"
            elif frame != "report" and ent > b["ent"]:
                b["ent"], b["ent_s"] = ent, window
            # A contradiction only counts if the sentence is about the claim; NLI otherwise labels
            # unrelated sentences ("The President of India is Droupadi Murmu") as contradicting
            # (Requiring shared predicate words as well was tried to filter namesakes, but it dropped real
            # contradictions like "Santana is a comedian" vs "...is a guitarist": FEVER 56.7% -> 53.3%.)
            if con > b["con"] and coverage(claim_words, window) >= MIN_CONTRADICTION_COVERAGE:
                b["con"], b["con_s"], b["con_why"] = con, window, "contradicts the claim"
            b["neu"] = max(b["neu"], float(row[neu_i]))

        for owner, b in best.items():
            if b["ent"] >= STANCE_THRESHOLD and b["ent"] >= b["con"]:
                results[owner] = {"stance": "SUPPORTING", "score": round(b["ent"], 4), "best_sentence": b["ent_s"],
                                  "rationale": f"Entails the claim (NLI p={b['ent']:.2f}): \"{b['ent_s'][:160]}\""}
            elif b["con"] >= STANCE_THRESHOLD:
                results[owner] = {"stance": "CONTRADICTING", "score": round(b["con"], 4), "best_sentence": b["con_s"],
                                  "rationale": f"{(b['con_why'][:1].upper() + b['con_why'][1:])} (NLI p={b['con']:.2f}): \"{b['con_s'][:160]}\""}
            else:
                results[owner] = {"stance": "NEUTRAL", "score": round(b["neu"], 4), "best_sentence": "",
                                  "rationale": f"Related context, but neither entails nor contradicts the claim "
                                               f"(max entail {b['ent']:.2f}, max contradict {b['con']:.2f})."}
        return results

    def entailed_with_end_signal(self, hypothesis: str, texts: List[str]) -> float:
        """
        Max entailment of a past-tense hypothesis, counting only windows that also say the state ENDED
        (a date range ending before this year, "former", "until", "succeeded by", ...). "X was a director"
        alone does not mean X stopped being one.
        """
        from datetime import datetime
        now_year = datetime.now().year
        windows = [w for t in texts for w in sentence_windows(t or "") if framing(w) is None and
                   (ENDED_SIGNAL.search(w) or any(b < now_year for _, b in year_ranges(w, now_year)))]
        if not windows:
            return 0.0
        self._load_model()
        if self._model == "fallback":
            return 0.0
        probs = self._probabilities([[w, hypothesis] for w in windows])
        return float(probs[:, self._labels["entailment"]].max())

    def max_entailment(self, hypothesis: str, texts: List[str]) -> float:
        """Highest entailment probability of hypothesis over all windows of all texts."""
        self._load_model()
        if self._model == "fallback" or not texts:
            return 0.0
        pairs = [[w, hypothesis] for t in texts for w in sentence_windows(t or "") if framing(w) is None]
        if not pairs:
            return 0.0
        probs = self._probabilities(pairs)
        return float(probs[:, self._labels["entailment"]].max())

    def evaluate_stance(self, claim: str, evidence_text: str) -> Dict[str, Any]:
        """Single-text convenience wrapper (kept for backwards compatibility)."""
        try:
            return self.classify_chunks(claim, [evidence_text])[0]
        except RuntimeError:
            return {"stance": "NEUTRAL", "score": 0.0, "rationale": "Fallback mode active."}


nli_evaluator = NLIEvaluator()
