"""
formatter.py — Phase 8A: Response Formatter
----------------------------------------------
Post-processes the raw LLM output into a clean, compliant response.

Enforced output constraints:
  1. Answer text: ≤ 3 sentences (hard truncation if LLM ignores the prompt rule)
  2. Source citation: exactly 1 Groww URL — injected from retrieval metadata,
     never from LLM output (prevents URL hallucination)
  3. Footer: "Last updated from sources: YYYY-MM-DD"

Special cases:
  - "I don't have that information..." passthrough — returned as-is without
    truncation or a citation block, since there is no relevant chunk to cite.
  - Missing source_url — response still emitted without the Source line.
  - Malformed scraped_at timestamp — falls back to today's date (estimated).

Final output structure:
    <Answer in ≤ 3 sentences.>
    Source: <groww_url>

    Last updated from sources: YYYY-MM-DD

Usage:
    from formatter import format_response
    formatted = format_response(raw_llm_text, top_chunk_meta)
"""

import re
import logging
from datetime import date

log = logging.getLogger(__name__)

# ── "No information" trigger phrase ──────────────────────────────────────────
# When the LLM returns this phrase the formatter emits it as-is (no citation).
NO_INFO_PHRASE = "i don't have that information"


def _split_sentences(text: str) -> list[str]:
    """
    Split text into sentences on terminal punctuation (.!?).
    Handles common decimal numbers (e.g. "1.11%") by requiring a space or
    end-of-string after the punctuation, not just any character.
    """
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in sentences if s.strip()]


def _truncate_to_sentences(text: str, max_sentences: int = 3) -> str:
    """Return at most max_sentences sentences; append a period if truncated."""
    sentences = _split_sentences(text)
    if len(sentences) <= max_sentences:
        return text.strip()
    truncated = " ".join(sentences[:max_sentences])
    if not truncated.endswith(('.', '!', '?')):
        truncated += "."
    return truncated


def _extract_scraped_date(scraped_at: str) -> str:
    """
    Parse the ISO scraped_at timestamp to YYYY-MM-DD.
    Falls back to today's date with '(estimated)' label if parsing fails.
    """
    if not scraped_at or scraped_at == "unknown":
        return f"{date.today()} (estimated)"
    try:
        # e.g. "2026-06-30T16:40:43.903849+00:00"
        return scraped_at.split("T")[0]
    except Exception:
        return f"{date.today()} (estimated)"


def _strip_llm_injected_lines(raw_text: str) -> str:
    """
    Remove any Source: or Last updated lines the LLM may have added.
    The pipeline injects these from retrieval metadata; LLM-added ones are
    unreliable (potentially hallucinated) and must be stripped.
    """
    clean_lines = []
    for line in raw_text.strip().split("\n"):
        stripped = line.strip()
        if stripped.lower().startswith("source:"):
            continue
        if stripped.lower().startswith("last updated"):
            continue
        if stripped:
            clean_lines.append(stripped)
    return " ".join(clean_lines)


def format_response(raw_text: str, top_chunk_meta: dict) -> str:
    """
    Format the raw LLM response into the required output structure.

    Args:
        raw_text:        The raw text string returned by call_llm().
        top_chunk_meta:  Dict with keys source_url, scraped_at, scheme_name, field
                         from the top retrieved chunk (passed from build_prompt()).

    Returns:
        A formatted response string with answer, source citation, and footer.
    """
    source_url = top_chunk_meta.get("source_url", "")
    scraped_at = top_chunk_meta.get("scraped_at", "unknown")

    # ── Special case: LLM has no answer ───────────────────────────────────────
    # Return a clean "no information" message without a citation block.
    if NO_INFO_PHRASE in raw_text.strip().lower():
        date_str = _extract_scraped_date(scraped_at)
        no_info_msg = "I don't have that information in my current data."
        return f"{no_info_msg}\n\nLast updated from sources: {date_str}"

    # ── Step 1: Strip LLM-injected source/footer lines ────────────────────────
    answer_text = _strip_llm_injected_lines(raw_text)

    # ── Step 2: Truncate to ≤ 3 sentences ─────────────────────────────────────
    answer_text = _truncate_to_sentences(answer_text, max_sentences=3)

    # ── Step 3: Assemble output ────────────────────────────────────────────────
    date_str = _extract_scraped_date(scraped_at)

    parts = [answer_text]
    if source_url:
        parts.append(f"Source: {source_url}")
    parts.append(f"\nLast updated from sources: {date_str}")

    formatted = "\n".join(parts)

    log.info(
        "Response formatted: %d sentence(s), has_source=%s",
        len(_split_sentences(answer_text)), bool(source_url),
    )
    return formatted


# ══════════════════════════════════════════════════════════════════════════════
# SELF-TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    MOCK_META = {
        "source_url":  "https://groww.in/mutual-funds/hdfc-technology-fund-direct-growth",
        "scraped_at":  "2026-06-30T16:40:43.903849+00:00",
        "scheme_name": "HDFC TECHNOLOGY FUND - DIRECT PLAN GROWTH",
        "field":       "expense_ratio",
    }

    MOCK_META_NO_DATE = {
        "source_url":  "https://groww.in/mutual-funds/hdfc-liquid-fund-direct-growth",
        "scraped_at":  "unknown",
        "scheme_name": "HDFC LIQUID FUND",
        "field":       "fund_managers",
    }

    tests = [
        # (description, raw_llm_text, meta, expected_checks)
        (
            "Normal factual answer -- <= 3 sentences",
            "The direct plan expense ratio of HDFC Technology Fund is 1.11%.",
            MOCK_META,
            {
                "has_source": True,
                "has_footer": True,
                "sentences_le_3": True,
                "no_info": False,
            },
        ),
        (
            "LLM returns 5 sentences -- must be truncated to 3",
            (
                "Sentence one. Sentence two. Sentence three. "
                "Sentence four. Sentence five."
            ),
            MOCK_META,
            {
                "has_source": True,
                "has_footer": True,
                "sentences_le_3": True,
                "no_info": False,
            },
        ),
        (
            "LLM adds hallucinated Source and footer -- must be stripped",
            (
                "The expense ratio is 1.11%.\n"
                "Source: https://hallucinated-url.com\n"
                "Last updated from sources: 2025-01-01"
            ),
            MOCK_META,
            {
                "has_source": True,    # real source injected from meta
                "has_footer": True,
                "sentences_le_3": True,
                "hallucinated_url": False,  # hallucinated URL should be gone
            },
        ),
        (
            "LLM returns no-info phrase -- passthrough without citation",
            "I don't have that information in my current data.",
            MOCK_META,
            {
                "has_source": False,   # no citation for no-info
                "has_footer": True,
                "no_info": True,
            },
        ),
        (
            "Missing scraped_at -- footer falls back to estimated date",
            "The fund managers of HDFC Liquid Fund are listed below.",
            MOCK_META_NO_DATE,
            {
                "has_footer": True,
                "estimated_date": True,
            },
        ),
    ]

    print("FORMATTER SELF-TEST")
    print("=" * 70)
    all_pass = True

    for desc, raw, meta, checks in tests:
        result = format_response(raw, meta)
        lines  = result.split("\n")

        has_source       = any(l.lower().startswith("source:") for l in lines)
        has_footer       = any("last updated from sources:" in l.lower() for l in lines)
        answer_lines     = [l for l in lines if l.strip()
                            and not l.lower().startswith("source:")
                            and not l.lower().startswith("last updated")]
        answer_block     = " ".join(answer_lines)
        sentence_count   = len(_split_sentences(answer_block))
        has_no_info      = "i don't have that information" in result.lower()
        has_hallucinated = "hallucinated-url.com" in result

        fail_reasons = []
        if "has_source"       in checks and checks["has_source"]       != has_source:
            fail_reasons.append(f"has_source: expected {checks['has_source']}, got {has_source}")
        if "has_footer"       in checks and not has_footer:
            fail_reasons.append("footer missing")
        if "sentences_le_3"   in checks and sentence_count > 3:
            fail_reasons.append(f"sentence count {sentence_count} > 3")
        if "no_info"          in checks and checks["no_info"] != has_no_info:
            fail_reasons.append(f"no_info: expected {checks['no_info']}, got {has_no_info}")
        if "hallucinated_url" in checks and checks["hallucinated_url"] != has_hallucinated:
            fail_reasons.append(f"hallucinated URL present: {has_hallucinated}")
        if "estimated_date"   in checks and "estimated" not in result:
            fail_reasons.append("estimated date fallback missing")

        status = "[PASS]" if not fail_reasons else "[FAIL]"
        if fail_reasons:
            all_pass = False

        print(f"  {status}  {desc}")
        if fail_reasons:
            for r in fail_reasons:
                print(f"           REASON: {r}")
        else:
            print(f"         sentences={sentence_count}  source={has_source}  footer={has_footer}")
        print()

    print("=" * 70)
    print(f"  Result: {'ALL PASS' if all_pass else 'SOME FAILED'}")
    print()
