"""
classifier.py — Phase 6A + Phase 8B: Query Classification & Refusal
---------------------------------------------------------------------
Classifies incoming user queries as 'factual' or 'advisory'.
Also provides the refusal handler for advisory queries.

Classification:
  - Keyword-based: trigger phrases → advisory
  - PII detection: PAN/phone/account number regex → pii
  - Empty query detection

Refusal handler:
  - Returns a fixed polite refusal template (no LLM call)

Returns: {"intent": "factual" | "advisory" | "pii" | "empty"}

Usage:
    from classifier import classify_query, get_refusal_response
"""

import re
import logging

log = logging.getLogger(__name__)

# ── Advisory trigger phrases ──────────────────────────────────────────────────
# Checked case-insensitively against the user query
ADVISORY_PHRASES = [
    r"\bshould i\b",
    r"\bis it good\b",
    r"\bis it worth\b",
    r"\bwhich is better\b",
    r"\brecommend\b",
    r"\bworth investing\b",
    r"\bopinion\b",
    r"\bbest fund\b",
    r"\bgood investment\b",
    r"\badvise\b",
    r"\badvice\b",
    r"\bsuitable\b",
    r"\bshould invest\b",
    r"\bbetter for me\b",
    r"\bsafe to invest\b",
    r"\bprefer\b",
    r"\bsuggest\b",
]

# ── PII patterns ──────────────────────────────────────────────────────────────
PII_PATTERNS = [
    r"\b[A-Z]{5}\d{4}[A-Z]\b",        # PAN card (e.g., ABCDE1234F)
    r"\b\d{10,12}\b",                   # phone / account number (10-12 digits)
    r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", # Aadhaar-like pattern
]

# ── Refusal templates ─────────────────────────────────────────────────────────
ADVISORY_REFUSAL = (
    "I can only share factual information about mutual fund schemes.\n"
    "Please consult a registered financial advisor for personalised guidance.\n\n"
    "Facts-only. No investment advice."
)

PII_REFUSAL = (
    "I noticed your query may contain personal information (PAN, phone, or account number). "
    "For your safety, I don't process or store such data.\n\n"
    "Please rephrase your question without personal details."
)

EMPTY_REFUSAL = "Please enter a question about HDFC mutual fund schemes."


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def classify_query(query: str) -> dict:
    """
    Classify a user query into an intent category.

    Returns:
        {"intent": "factual" | "advisory" | "pii" | "empty",
         "matched": <trigger phrase or pattern that matched, if any>}
    """
    # ── Empty check ───────────────────────────────────────────────────────────
    if not query or not query.strip():
        return {"intent": "empty", "matched": None}

    q = query.strip()

    # ── PII check (before advisory — safety first) ────────────────────────────
    for pat in PII_PATTERNS:
        m = re.search(pat, q)
        if m:
            log.info("  PII detected: %s", pat)
            return {"intent": "pii", "matched": m.group()}

    # ── Advisory check ────────────────────────────────────────────────────────
    for phrase in ADVISORY_PHRASES:
        if re.search(phrase, q, re.IGNORECASE):
            log.info("  Advisory trigger: %s", phrase)
            return {"intent": "advisory", "matched": phrase}

    # ── Default: factual ──────────────────────────────────────────────────────
    return {"intent": "factual", "matched": None}


def get_refusal_response(intent: str) -> str:
    """
    Return the appropriate refusal message for a non-factual intent.
    """
    if intent == "advisory":
        return ADVISORY_REFUSAL
    elif intent == "pii":
        return PII_REFUSAL
    elif intent == "empty":
        return EMPTY_REFUSAL
    else:
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# SELF-TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    tests = [
        # (query, expected_intent)
        ("What is the expense ratio of HDFC Technology Fund?", "factual"),
        ("What is the NAV of HDFC Liquid Fund?", "factual"),
        ("Who manages HDFC Defence Fund?", "factual"),
        ("Should I invest in HDFC Technology Fund?", "advisory"),
        ("Which HDFC fund is better for me?", "advisory"),
        ("Is HDFC Defence Fund a good investment?", "advisory"),
        ("Recommend a good fund", "advisory"),
        ("My PAN is ABCDE1234F and I want to invest", "pii"),
        ("", "empty"),
        ("   ", "empty"),
    ]

    print("CLASSIFIER UNIT TESTS")
    print("=" * 60)
    all_pass = True
    for query, expected in tests:
        result = classify_query(query)
        status = "PASS" if result["intent"] == expected else "FAIL"
        if status == "FAIL":
            all_pass = False
        print(f"  [{status}] [{result['intent']:8s}] {query!r:.50s}")

    print("-" * 60)
    print(f"  Result: {'ALL PASS' if all_pass else 'SOME FAILED'}")
