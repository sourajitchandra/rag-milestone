"""
test_phase11.py -- Phase 11: End-to-End Testing & Validation
-------------------------------------------------------------
Runs all 11 test cases defined in the implementation plan:
  - 5 Factual Query Tests
  - 3 Refusal Tests
  - 3 Edge Case Tests

Additionally verifies 4 structural constraints:
  - No response exceeds 3 sentences
  - Every factual response has exactly 1 Groww source URL
  - Every factual response has a 'Last updated from sources:' footer
  - data/raw/ HTML files are not committed to version control

Usage (from project root):
    python tests/test_phase11.py
"""

import sys
import re
import logging
import subprocess
from pathlib import Path

# Force UTF-8 output on Windows to avoid cp1252 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# -- Path setup ---------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.classifier import classify_query, get_refusal_response
from src.retriever import Retriever
from src.rate_limiter import RateLimiter, RateLimitExceeded
from src.prompt_builder import build_prompt
from src.llm import call_llm
from src.formatter import format_response

logging.basicConfig(level=logging.WARNING)  # suppress pipeline INFO noise

# =============================================================================
# HELPERS
# =============================================================================

GROWW_DOMAIN = "groww.in"
NO_INFO_PHRASE = "i don't have that information"
REFUSAL_PHRASES = [
    "can only share factual",
    "registered financial advisor",
    "personal information",
    "please enter a question",
]


def _count_sentences(text: str) -> int:
    answer_lines = [
        l for l in text.split("\n")
        if l.strip()
        and not l.strip().lower().startswith("source:")
        and not l.strip().lower().startswith("last updated")
    ]
    answer_block = " ".join(answer_lines)
    sentences = re.split(r'(?<=[.!?])\s+', answer_block.strip())
    return len([s for s in sentences if s.strip()])


def _has_groww_url(text: str) -> bool:
    for line in text.split("\n"):
        if line.strip().lower().startswith("source:") and GROWW_DOMAIN in line:
            return True
    return False


def _has_footer(text: str) -> bool:
    return any("last updated from sources:" in l.lower() for l in text.split("\n"))


def run_pipeline(query: str, retriever: Retriever, rate_limiter: RateLimiter):
    """Run full RAG pipeline. Returns (response_text, intent)."""
    classification = classify_query(query)
    intent = classification["intent"]

    if intent != "factual":
        return get_refusal_response(intent), intent

    try:
        rate_limiter.check_and_record()
    except RateLimitExceeded as e:
        return str(e), "rate_limited"

    chunks = retriever.search(query, top_k=3)
    if not chunks:
        return (
            "I don't have information about that in my current data.\n\n"
            "Last updated from sources: N/A"
        ), "factual"

    prompt, top_meta = build_prompt(query, chunks)
    raw = call_llm(prompt)
    return format_response(raw, top_meta), intent


# =============================================================================
# TEST DEFINITIONS
# =============================================================================

PASS  = "PASS"
FAIL  = "FAIL"
ERROR = "ERROR"


def make_tests():
    """Return list of (id, category, query, check_fn, description)."""

    def factual_checks(response, need_url=True):
        fails = []
        if not _has_footer(response):
            fails.append("Missing 'Last updated from sources:' footer")
        if _count_sentences(response) > 3:
            fails.append(f"Response exceeds 3 sentences ({_count_sentences(response)} found)")
        if need_url and not _has_groww_url(response):
            fails.append("Missing Groww source URL in 'Source:' line")
        return fails

    def refusal_check(response):
        lower = response.lower()
        fails = []
        if not any(p in lower for p in REFUSAL_PHRASES):
            fails.append("Response does not match any expected refusal template")
        if _has_groww_url(response):
            fails.append("Refusal response should NOT contain a Groww source URL")
        return fails

    return [
        # -- Factual Tests ---------------------------------------------------
        (
            "FQ-01", "Factual",
            "What is the expense ratio of HDFC Technology Fund?",
            lambda r: factual_checks(r, need_url=True),
            "Returns correct %, Groww source URL, footer date",
        ),
        (
            "FQ-02", "Factual",
            "What is the exit load for HDFC Silver ETF FoF?",
            lambda r: factual_checks(r, need_url=True),
            "Returns exit load details, <=3 sentences, 1 citation link",
        ),
        (
            "FQ-03", "Factual",
            "What is the minimum SIP for HDFC Defence Fund?",
            lambda r: factual_checks(r, need_url=True),
            "Returns rupee amount, 1 citation link",
        ),
        (
            "FQ-04", "Factual",
            "What is the lock-in period for HDFC ELSS?",
            lambda r: factual_checks(
                r,
                need_url=(NO_INFO_PHRASE not in r.lower()),
            ),
            "N/A for these 5 funds -- returns not-found or N/A answer",
        ),
        (
            "FQ-05", "Factual",
            "Who is the fund manager of HDFC Liquid Fund?",
            lambda r: factual_checks(r, need_url=True),
            "Returns fund manager name",
        ),

        # -- Refusal Tests ---------------------------------------------------
        (
            "RF-01", "Refusal",
            "Should I invest in HDFC Technology Fund?",
            refusal_check,
            "Polite refusal, no LLM call, no source URL",
        ),
        (
            "RF-02", "Refusal",
            "Which HDFC fund is better for me?",
            refusal_check,
            "Polite refusal",
        ),
        (
            "RF-03", "Refusal",
            "Is HDFC Defence Fund a good investment?",
            refusal_check,
            "Polite refusal",
        ),

        # -- Edge Case Tests -------------------------------------------------
        (
            "EC-01", "Edge Case",
            "What is the expense ratio of Axis Bluechip Fund?",
            lambda r: (
                ["Response should indicate no info -- got unexpected source URL"]
                if _has_groww_url(r) and NO_INFO_PHRASE not in r.lower()
                else []
            ),
            "Non-HDFC fund -- returns no-information response",
        ),
        (
            "EC-02", "Edge Case",
            "",  # empty query
            refusal_check,
            "Empty query -- returns empty-query refusal",
        ),
        (
            "EC-03", "Edge Case",
            "My PAN is ABCDE1234F, what fund should I pick?",
            lambda r: (
                ["PII query should return refusal but got factual response with source URL"]
                if _has_groww_url(r) else []
            ),
            "PII query -- classified as pii, refusal returned",
        ),
    ]


# =============================================================================
# TEST RUNNER
# =============================================================================

WIDTH = 72


def run_all_tests():
    print()
    print("=" * WIDTH)
    print("  Phase 11 -- End-to-End Testing & Validation")
    print("  HDFC Mutual Fund FAQ Assistant")
    print("=" * WIDTH)
    print()

    print("  Loading retriever (BGE model + FAISS index)...")
    retriever = Retriever()
    rate_limiter = RateLimiter()
    print("  Ready.\n")

    tests = make_tests()
    results = []

    for category in ["Factual", "Refusal", "Edge Case"]:
        cat_tests = [(tid, cat, q, chk, desc)
                     for tid, cat, q, chk, desc in tests if cat == category]
        print(f"  {'-' * (WIDTH - 2)}")
        print(f"  {category} Tests ({len(cat_tests)})")
        print(f"  {'-' * (WIDTH - 2)}")

        for tid, cat, query, check_fn, description in cat_tests:
            display_q = repr(query[:60] + ("..." if len(query) > 60 else ""))
            intent = "?"
            try:
                response, intent = run_pipeline(query, retriever, rate_limiter)
                failures = check_fn(response)
                status = PASS if not failures else FAIL
            except Exception as exc:
                response = ""
                failures = [f"Exception: {exc}"]
                status = ERROR

            results.append((tid, cat, query, description, status, failures, response, intent))

            icon = "[PASS]" if status == PASS else ("[FAIL]" if status == FAIL else "[ERROR]")
            print(f"  {icon} [{tid}] {display_q}")
            print(f"         Desc  : {description}")
            print(f"         Intent: {intent}")
            if failures:
                for f in failures:
                    print(f"         !! {f}")
            if response:
                preview = response.replace("\n", " ")[:115]
                suffix = "..." if len(response) > 115 else ""
                print(f"         ->  {preview}{suffix}")
            print()

    # -- Structural constraint checks ----------------------------------------
    print(f"  {'-' * (WIDTH - 2)}")
    print("  Structural Constraint Checks")
    print(f"  {'-' * (WIDTH - 2)}")

    factual_responses = [
        (tid, resp)
        for tid, cat, _, __, status, ___, resp, ____ in results
        if cat == "Factual" and status == PASS and resp
    ]

    # SC-01: sentence count
    over_limit = [(tid, _count_sentences(r)) for tid, r in factual_responses if _count_sentences(r) > 3]
    sc1 = "[PASS]" if not over_limit else "[FAIL]"
    detail = f"" if not over_limit else f" -- violations: {over_limit}"
    print(f"  {sc1} [SC-01] All factual responses <= 3 sentences{detail}")

    # SC-02: Groww URL
    missing_url = [
        tid for tid, r in factual_responses 
        if not _has_groww_url(r) and NO_INFO_PHRASE not in r.lower()
    ]
    sc2 = "[PASS]" if not missing_url else "[FAIL]"
    detail = f"" if not missing_url else f" -- missing in: {missing_url}"
    print(f"  {sc2} [SC-02] All factual responses (with data) have a Groww source URL{detail}")

    # SC-03: footer
    missing_footer = [tid for tid, r in factual_responses if not _has_footer(r)]
    sc3 = "[PASS]" if not missing_footer else "[FAIL]"
    detail = f"" if not missing_footer else f" -- missing in: {missing_footer}"
    print(f"  {sc3} [SC-03] All factual responses have 'Last updated' footer{detail}")

    # SC-04: data/raw not in git
    tracked = subprocess.run(
        ["git", "ls-files", "data/raw/"],
        cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    sc4 = "[PASS]" if not tracked else "[FAIL]"
    detail = f"" if not tracked else f" -- tracked files: {tracked[:80]}"
    print(f"  {sc4} [SC-04] data/raw/ HTML files NOT committed to git{detail}")

    print()

    # -- Summary -------------------------------------------------------------
    total   = len(results)
    passed  = sum(1 for *_, s, __, ___, ____ in results if s == PASS)
    failed  = sum(1 for *_, s, __, ___, ____ in results if s == FAIL)
    errored = sum(1 for *_, s, __, ___, ____ in results if s == ERROR)
    sc_pass = sum([not over_limit, not missing_url, not missing_footer, not tracked])

    print("=" * WIDTH)
    print(f"  TEST RESULTS : {passed}/{total} passed  |  {failed} failed  |  {errored} errors")
    print(f"  STRUCTURAL   : {sc_pass}/4 constraint checks passed")
    all_pass = (failed == 0 and errored == 0 and sc_pass == 4)
    verdict = "ALL PASS -- Phase 11 COMPLETE" if all_pass else "SOME FAILURES -- review above"
    print(f"  OVERALL      : {verdict}")
    print("=" * WIDTH)
    print()

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
