"""
End-to-end verdict tests with the real DeBERTa NLI judge and FIXED evidence (retrieval is stubbed),
so results are deterministic and need no network. These are the audit's failing cases.
"""
from datetime import datetime, timezone

import pytest

import backend.services.orchestration.verification_orchestrator as orch_mod
from backend.models.schemas import ClaimVerificationRequest
from backend.services.nlp.nli_evaluator import nli_evaluator

pytestmark = pytest.mark.skipif(not nli_evaluator.available(), reason="DeBERTa NLI model not available")

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

WHO = {"chunk_id": "who", "source": "WHO antibiotic resistance fact sheet", "credibility_score": 0.95,
       "text": "Antibiotics are medicines used to prevent and treat bacterial infections. "
               "Antibiotics do not work against viral infections such as colds and flu."}
INDIA_GOV = {"chunk_id": "india", "source": "Government of India portal", "credibility_score": 0.95, "retrieval_date": NOW,
             "text": "Narendra Modi is the Prime Minister of India. He has held office since May 2014."}
WIKI_MODI = {"chunk_id": "wiki-modi", "source": "Wikipedia: Narendra Modi", "credibility_score": 0.80, "retrieval_date": NOW,
             "text": "Narendra Damodardas Modi is an Indian politician who has served as the prime minister of India since 2014."}
WIKI_ABE = {"chunk_id": "wiki-abe", "source": "Wikipedia: Shinzo Abe", "credibility_score": 0.80, "retrieval_date": NOW,
            "text": "Shinzo Abe was a Japanese politician who served as Prime Minister of Japan from 2006 to 2007 "
                    "and again from 2012 to 2020. He was assassinated in 2022."}
IMF = {"chunk_id": "imf", "source": "IMF World Economic Outlook", "credibility_score": 0.95,
       "text": "India is the fifth-largest economy in the world by nominal GDP, behind the United States, China, Germany and Japan."}
COOKING = {"chunk_id": "cook", "source": "Recipe site", "credibility_score": 0.5,
           "text": "Preheat the oven to 180 degrees and bake the bread for forty minutes until golden."}


def run(monkeypatch, claim, chunks):
    monkeypatch.setattr(orch_mod.evidence_retriever, "retrieve", lambda *a, **k: [dict(c) for c in chunks])
    return orch_mod.verification_orchestrator.process(ClaimVerificationRequest(claim=claim, llm_provider="offline"))


def test_refutes_wrong_person_in_role(monkeypatch):
    r = run(monkeypatch, "Donald Trump is the Prime Minister of India.", [INDIA_GOV, WIKI_MODI])
    assert r.verdict == "REFUTED", (r.verdict, r.key_reasoning)
    assert r.contradicting_evidence and r.confidence_score > 50


def test_supports_true_role_claim(monkeypatch):
    r = run(monkeypatch, "Narendra Modi is the Prime Minister of India.", [INDIA_GOV, WIKI_MODI])
    assert r.verdict == "SUPPORTED", (r.verdict, r.key_reasoning)
    assert r.evidence_agreement_score == 100.0 and r.verification_strength == "Strong"


def test_question_form_is_normalised(monkeypatch):
    r = run(monkeypatch, "Is Narendra Modi PM of India", [INDIA_GOV, WIKI_MODI])
    assert r.verdict == "SUPPORTED", (r.verdict, r.key_reasoning)


def test_refutes_medical_myth(monkeypatch):
    r = run(monkeypatch, "Antibiotics can cure viral infections like the flu.", [WHO])
    assert r.verdict == "REFUTED", (r.verdict, r.key_reasoning)


def test_refutes_wrong_ranking(monkeypatch):
    r = run(monkeypatch, "India is the third largest economy in the world.", [IMF])
    assert r.verdict == "REFUTED", (r.verdict, r.key_reasoning)


def test_outdated_current_role(monkeypatch):
    r = run(monkeypatch, "Shinzo Abe is the current Prime Minister of Japan", [WIKI_ABE])
    assert r.verdict == "OUTDATED", (r.verdict, r.key_reasoning)
    assert r.temporal_match == "Outdated"


def test_historical_claim_supported(monkeypatch):
    r = run(monkeypatch, "Shinzo Abe was the Prime Minister of Japan.", [WIKI_ABE])
    assert r.verdict == "SUPPORTED_HISTORICALLY", (r.verdict, r.key_reasoning)


def test_unrelated_evidence_is_insufficient_with_zero_confidence(monkeypatch):
    r = run(monkeypatch, "Saturn has many rings.", [COOKING])
    assert r.verdict == "INSUFFICIENT_EVIDENCE"
    assert r.confidence_score == 0.0 and r.evidence_agreement_score == 0.0


def test_no_evidence(monkeypatch):
    r = run(monkeypatch, "The moon is made of green cheese.", [])
    assert r.verdict == "INSUFFICIENT_EVIDENCE" and r.confidence_score == 0.0
    assert any("No evidence" in l for l in r.limitations)


def test_duplicate_chunks_do_not_inflate_agreement(monkeypatch):
    dup = [dict(INDIA_GOV, chunk_id=f"india-{i}") for i in range(3)]
    r = run(monkeypatch, "Narendra Modi is the Prime Minister of India.", dup)
    assert r.verdict == "SUPPORTED"
    assert r.verification_strength != "Strong"  # one source, however many chunks
    assert any("one independent source" in l for l in r.limitations)


def test_evidence_carries_rationale_and_score(monkeypatch):
    r = run(monkeypatch, "Antibiotics can cure viral infections like the flu.", [WHO])
    ev = r.contradicting_evidence[0]
    assert 0.6 <= ev.stance_score <= 1.0 and "NLI" in ev.rationale


# --- Regressions from the live run (real Wikipedia sentences that fooled the NLI judge) ---

def _wiki(title, text):
    return {"chunk_id": f"w-{title}", "source": f"Wikipedia: {title}", "credibility_score": 0.80, "retrieval_date": NOW, "text": text}


def test_off_topic_sentences_do_not_contradict(monkeypatch):
    chunks = [INDIA_GOV,
              _wiki("President of India", "The President of India (Head of State) is Droupadi Murmu, who assumed office in July 2022."),
              _wiki("Canis Major", "The Canis Major Overdensity is a disputed dwarf irregular galaxy in the Local Group.")]
    r = run(monkeypatch, "Narendra Modi is the Prime Minister of India.", chunks)
    assert r.verdict == "SUPPORTED" and not r.contradicting_evidence, [e.rationale for e in r.contradicting_evidence]


def test_heliocentrism_supports_earth_orbiting_sun(monkeypatch):
    r = run(monkeypatch, "The earth revolves around the sun", [_wiki("Heliocentrism",
        "Heliocentrism is a superseded astronomical model in which the Earth and planets revolve around the Sun at the "
        "center of the universe. It superseded geocentrism, which placed the Earth at the center of the universe.")])
    assert r.verdict != "REFUTED", r.key_reasoning


def test_myth_framing_counts_against_claim(monkeypatch):
    r = run(monkeypatch, "The moon is made of green cheese.", [
        _wiki("The Moon is made of green cheese",
              '"The Moon is made of green cheese" is a statement referring to a fanciful belief that the Moon is composed of cheese.'),
        _wiki("Green cheese", "The Oxford English Dictionary gives a reference from the year 1542 of the four sorts of cheese.")])
    assert r.verdict == "REFUTED", (r.verdict, r.key_reasoning)
    assert "myth" in r.contradicting_evidence[0].rationale.lower()


def test_myth_is_not_outdated(monkeypatch):
    # Non-role claims never become OUTDATED even if a past-tense version is entailed somewhere
    r = run(monkeypatch, "India is the third largest economy in the world.", [IMF,
        {"chunk_id": "ppp", "source": "PPP note", "credibility_score": 0.9,
         "text": "In purchasing power parity terms, India was the third-largest economy in the world."}])
    assert r.verdict in ("REFUTED", "CONFLICTING"), (r.verdict, r.key_reasoning)


# --- Year-in-range claims (benchmark finding: NLI called "in 2023" vs "2021 to 2025" a contradiction) ---

BIDEN = _wiki("Joe Biden", "Joseph Robinette Biden Jr. is an American politician who was the 46th president of the United States. "
                           "He assumed office on January 20, 2021, and his term ended on January 20, 2025.")
OBAMA = _wiki("Barack Obama", "Barack Hussein Obama II is an American politician who was the 44th president of the United States from 2009 to 2017.")
COOK = _wiki("Tim Cook", "Timothy Donald Cook is an American business executive who has been the chief executive officer of Apple since 2011.")


@pytest.mark.parametrize("claim,chunks,expected", [
    ("Joe Biden was the President of the United States in 2023.", [BIDEN], "SUPPORTED_HISTORICALLY"),
    ("Barack Obama was the President of the United States in 2023.", [OBAMA], "REFUTED"),
    ("The CEO of Apple in 2021 was Tim Cook.", [COOK], "SUPPORTED_HISTORICALLY"),
    ("Barack Obama was the President of the United States in 2012.", [OBAMA], "SUPPORTED_HISTORICALLY"),
])
def test_year_in_range_claims(monkeypatch, claim, chunks, expected):
    r = run(monkeypatch, claim, chunks)
    assert r.verdict == expected, (r.verdict, r.key_reasoning)


# --- FEVER regressions: namesakes and "was a director" are not OUTDATED ---

def test_occupation_is_not_outdated(monkeypatch):
    chunks = [_wiki("Ian Brennan (writer)", "Ian Brennan is an American screenwriter, director and actor."),
              _wiki("Ian Brennan (producer)", "Ian Brennan, American music producer"),
              _wiki("Ian G. Brennan", "Ian G. Brennan is the official sculptor to the Most Noble Order of the Garter.")]
    r = run(monkeypatch, "Ian Brennan is a film director.", chunks)
    # Namesake pages can still count as contradictions (known limitation, see docs), but an occupation
    # stated in the past tense must never be reported as OUTDATED
    assert r.verdict != "OUTDATED", (r.verdict, r.key_reasoning)


def test_outdated_needs_an_ended_signal(monkeypatch):
    # Past-tense entailment without any sign the role ended must not produce OUTDATED
    chunk = _wiki("Tim Cook", "Tim Cook was named chief executive officer of Apple in 2011 and leads the company.")
    r = run(monkeypatch, "Tim Cook is the CEO of Apple.", [chunk])
    assert r.verdict != "OUTDATED", (r.verdict, r.key_reasoning)
