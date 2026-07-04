"""
app.py — Phase 9: Main Application Entry Point
--------------------------------------------------
Orchestrates the full RAG pipeline: classify → retrieve → prompt → LLM → format.

Modes:
  1. CLI mode (default): Interactive terminal chat
  2. API mode (future): Can be imported and called programmatically

Usage:
    python src/app.py
"""

import logging
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.classifier import classify_query, get_refusal_response
from src.retriever import Retriever
from src.rate_limiter import RateLimiter, RateLimitExceeded
from src.prompt_builder import build_prompt
from src.llm import call_llm
from src.formatter import format_response

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def process_query(query: str, retriever: Retriever, rate_limiter: RateLimiter) -> str:
    """
    Process a single user query through the full RAG pipeline.

    Steps:
        1. Classify the query (factual / advisory / pii / empty)
        2. If non-factual → return refusal (no LLM call)
        3. Rate-limit check — enforces Groq free-tier quotas (no retrieval/LLM if exceeded)
        4. Retrieve top-3 chunks from FAISS
        5. Build the constrained prompt
        6. Call the LLM via Groq
        7. Format the response (≤3 sentences, citation, footer)

    Returns:
        The formatted response string.
    """
    # ── Step 1: Classify ──────────────────────────────────────────────────────
    classification = classify_query(query)
    intent = classification["intent"]
    log.info("Query classified as: %s", intent)

    # ── Step 2: Refusal for non-factual queries ───────────────────────────────
    if intent != "factual":
        log.info("Non-factual query — returning refusal (no LLM call)")
        return get_refusal_response(intent)

    # ── Step 3: Rate-limit check (Groq free-tier quota guard) ─────────────────
    # Checked BEFORE retrieval so no FAISS/embedding work is wasted when quota
    # is exhausted.  RateLimitExceeded carries the user-facing message.
    try:
        rate_limiter.check_and_record()
    except RateLimitExceeded as e:
        log.warning("Rate limit exceeded: %s", e)
        return str(e)

    # ── Step 4: Retrieve ──────────────────────────────────────────────────────
    chunks = retriever.search(query, top_k=3)
    log.info("Retrieved %d chunks", len(chunks))

    if not chunks:
        return "I don't have information about that in my current data."

    for c in chunks:
        log.info("  #%d  %s (score=%.4f)", c["rank"], c["chunk_id"], c["score"])

    # ── Step 5: Build prompt ──────────────────────────────────────────────────
    prompt, top_meta = build_prompt(query, chunks)

    # ── Step 6: Call LLM ──────────────────────────────────────────────────────
    try:
        raw_response = call_llm(prompt)
    except RuntimeError as exc:
        log.error("LLM call failed: %s", exc)
        return "Sorry, I'm unable to process your request right now. Please try again later."

    # ── Step 7: Format response ───────────────────────────────────────────────
    formatted = format_response(raw_response, top_meta)

    return formatted


# ══════════════════════════════════════════════════════════════════════════════
# CLI MODE
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  Mutual Fund FAQ Assistant                               ║")
    print("║  Facts-only. No investment advice.                       ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()
    print("  Ask me anything factual about HDFC mutual fund schemes.")
    print("  Type 'quit' or 'exit' to stop.")
    print()

    # Initialise retriever (loads model + index — may take a few seconds)
    log.info("Loading retriever...")
    retriever = Retriever()

    # Initialise rate limiter (shared across all queries in this session)
    rate_limiter = RateLimiter()
    log.info(
        "Rate limiter ready. Groq limits: RPM=%d  RPD=%d  TPM=%d  TPD=%d",
        30, 1_000, 12_000, 100_000,
    )
    print("  Ready!\n")

    while True:
        try:
            query = input("  You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Goodbye!")
            break

        if not query:
            continue
        if query.lower() in ("quit", "exit", "q"):
            print("  Goodbye!")
            break

        print()
        response = process_query(query, retriever, rate_limiter)
        print(f"  Assistant:\n")
        for line in response.split("\n"):
            print(f"    {line}")
        print()


if __name__ == "__main__":
    main()
