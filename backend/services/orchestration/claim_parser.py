import re
from datetime import datetime
from backend.models.schemas import StructuredClaim

# Word-boundary patterns: plain substring checks matched "now" in "known", "cure" in "secure",
# "current" in "currency", which silently flipped claim types and temporal requirements.
ROLE_PATTERN = re.compile(
    r"\b(prime\s+minister|pm|president|vice\s+president|chancellor|governor|minister|ceo|cfo|cto|"
    r"chairman|chairperson|director|king|queen|monarch|founder|co-founder|head\s+of\s+state|"
    r"head\s+of\s+government|mayor|speaker|chief\s+justice|captain|coach)\b", re.IGNORECASE)
LOCATION_PATTERN = re.compile(
    r"\b(located\s+in|headquartered|headquarters|based\s+in|capital\s+of|situated\s+in)\b", re.IGNORECASE)
STATISTIC_PATTERN = re.compile(
    r"(\d+(\.\d+)?\s*%|\bpercent\b|\bmillion\b|\bbillion\b|\btrillion\b|\bgdp\b|\blargest\b|"
    r"\bsmallest\b|\bhighest\b|\blowest\b|\branked?\b|\beconomy\b)", re.IGNORECASE)
SCIENCE_PATTERN = re.compile(
    r"\b(cure[sd]?|curing|disease|vaccines?|virus(es)?|viral|infections?|cancer|dna|antibiotics?|"
    r"bacteria|medicine|drug|treatment|symptoms?)\b", re.IGNORECASE)
CURRENT_PATTERN = re.compile(r"\b(current(ly)?|now|today|presently|at\s+present|as\s+of\s+now|incumbent)\b", re.IGNORECASE)
PAST_PATTERN = re.compile(r"\b(was|were|had|did|became|used\s+to|former(ly)?|previously|once)\b", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")
SUBJECT_PATTERN = re.compile(r"^(.*?)\s+(is|are|was|were|became|has|have|had|can|cannot|will)\s+", re.IGNORECASE)
QUESTION_PREFIX = re.compile(r"^(is|are|was|were|did|does|do|can|has|have)\s+", re.IGNORECASE)


class ClaimParser:
    def parse(self, text: str) -> StructuredClaim:
        text = text.strip()

        # Determine claim type (most specific first)
        if ROLE_PATTERN.search(text):
            claim_type = "PERSON_ROLE"
        elif LOCATION_PATTERN.search(text):
            claim_type = "LOCATION"
        elif SCIENCE_PATTERN.search(text):
            claim_type = "SCIENTIFIC"
        elif STATISTIC_PATTERN.search(text):
            claim_type = "STATISTICAL"
        else:
            claim_type = "AMBIGUOUS"

        # Temporal scope: an explicit past year or past-tense verb makes it a historical claim;
        # explicit "current/now/today" (or present tense about a role) requires fresh evidence.
        time_expression = None
        historical = bool(PAST_PATTERN.search(text))
        year_match = YEAR_PATTERN.search(text)
        if year_match:
            time_expression = year_match.group(0)
            if int(time_expression) < datetime.now().year:
                historical = True

        currentness_required = bool(CURRENT_PATTERN.search(text)) and not historical
        if currentness_required and time_expression is None:
            time_expression = "present"

        if historical and claim_type == "AMBIGUOUS":
            claim_type = "HISTORICAL_FACT"

        # Subject: words before the main verb ("X is ...", or question form "Is X ...")
        if QUESTION_PREFIX.match(text):
            # "Is Narendra Modi PM of India" -> leading Title-case name (all-caps like "PM" excluded)
            words = QUESTION_PREFIX.sub("", text).split()
            name = []
            for w in words:
                if w[:1].isupper() and not w.isupper():
                    name.append(w)
                else:
                    break
            subject = " ".join(name) or None
        else:
            subject_match = SUBJECT_PATTERN.search(text)
            subject = subject_match.group(1).strip() if subject_match else None
        role_match = ROLE_PATTERN.search(text)

        return StructuredClaim(
            original_claim=text,
            subject=subject,
            role=role_match.group(0) if role_match else None,
            claim_type=claim_type,
            time_expression=time_expression,
            currentness_required=currentness_required,
            historical=historical
        )


claim_parser = ClaimParser()
