"""Static checks on the UI source (frontend/src): no fabricated numbers/claims, one canonical verdict vocabulary, AI label."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# The UI source lives in frontend/src (built to static/ by `npm run build`); index.html is only a shell
HTML = "\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "frontend" / "src").glob("*.js*")))

FABRICATED = [
    r"\|\|\s*1210", r"\|\|\s*218", r"\|\|\s*849", r"\|\|\s*95\b", r"\|\|\s*100\b",
    r"\|\|\s*5\s*\}",               # fake "5 feeds" fallback
    r"'Recently'",                   # fake "last synced" fallback
    r"DeBERTa V3", r"DEBERTA V3", r"ONLINE \(",  # model claimed online regardless of what ran
    r"1,200\+", r"112\+", r"Zero hallucinations", r"session memory",
    r"setProgressStep", r"Router Agent:", r"Judge Agent:",  # fake timed pipeline steps
]


@pytest.mark.parametrize("pattern", FABRICATED)
def test_no_fabricated_literals(pattern):
    assert not re.search(pattern, HTML), f"fabricated content still present: {pattern}"


def test_verdict_helper_has_all_canonical_verdicts():
    block = HTML[HTML.index("const VERDICT_STYLES"):HTML.index("const LEGACY_VERDICTS")]
    for v in ["SUPPORTED", "SUPPORTED_HISTORICALLY", "OUTDATED", "REFUTED", "CONFLICTING", "INSUFFICIENT_EVIDENCE"]:
        assert re.search(rf"\b{v}:", block), v


def test_legacy_verdicts_are_mapped():
    block = HTML[HTML.index("const LEGACY_VERDICTS"):HTML.index("const canonicalVerdict")]
    for legacy in ["SUPPORTED_CURRENT", "VERIFIED", "CONTRADICTED", "INSUFFICIENT EVIDENCE", "AMBIGUOUS_TIME_CONTEXT", "MISLEADING"]:
        assert f"'{legacy}'" in block, legacy


def test_ai_assisted_label_and_report_button():
    assert "AI-assisted verdict — check the sources below before sharing." in HTML
    assert "Report wrong verdict" in HTML


def test_explainability_fields_rendered():
    for field in ["rationale", "stance_score", "verification_strength", "agreement_analysis", "entity_analysis",
                  "temporal_analysis", "verification_recommendation", "limitations", "similar_claim_found",
                  "llm_provider_used"]:
        assert field in HTML, field


def test_history_and_analytics_tabs_in_nav():
    assert "{ id: 'history', label: 'History'" in HTML
    assert "{ id: 'analytics', label: 'Analytics'" in HTML


def test_inputs_have_accessible_names():
    for label in ['aria-label="Claim to verify"', 'aria-label="News article URL"',
                  'aria-label="Forwarded message text"', 'aria-label="Filter news"',
                  'aria-label="Upload reference document"']:
        assert label in HTML, label


def test_privacy_note_and_history_controls():
    assert "Your checks are stored for 30 days, visible only in this browser. Don't paste personal information." in HTML
    assert "Clear my history" in HTML and "method: 'DELETE'" in HTML


def test_every_api_call_goes_through_the_client_id_helper():
    app = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
    assert "fetch(" not in app, "App.jsx must use api()/postJson()/adminFetch() so X-Client-Id is always sent"
    helper = (ROOT / "frontend" / "src" / "api.js").read_text(encoding="utf-8")
    assert "'X-Client-Id'" in helper and "tl_client_id" in helper and "randomUUID" in helper


def test_feedback_form_posts_to_backend():
    assert "postJson('/api/feedback'" in HTML
    for field in ["verification_id", "suggested_verdict", "comment"]:
        assert field in HTML
    assert "Thanks — report received" in HTML
    assert "clipboard" not in HTML


def test_cached_badge():
    assert "currentResult.cached" in HTML and "Cached result" in HTML
