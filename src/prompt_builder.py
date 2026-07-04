"""
prompt_builder.py — Phase 7A: Prompt Assembly
-----------------------------------------------
Assembles the RAG prompt from retrieved context chunks and the user query.

Design decisions:
  - The system prompt tells the LLM to produce ONLY the factual answer
    in ≤ 3 sentences. It must NOT add a source line or footer — those are
    injected by the formatter from retrieval metadata (preventing hallucination).
  - The context block is structured so the LLM can identify which scheme
    and field each chunk belongs to.
  - Returns (prompt_text, top_chunk_meta) so the formatter can inject the
    verified source URL and scraped_at timestamp.

Usage:
    from prompt_builder import build_prompt
    prompt, top_meta = build_prompt(query, retrieved_chunks)
"""

import logging

log = logging.getLogger(__name__)

# ── System prompt ─────────────────────────────────────────────────────────────
# Key constraints enforced here:
#   1. Facts-only — no advice, no opinion
#   2. Answer ONLY from the provided context chunks
#   3. ≤ 3 sentences (brevity)
#   4. If answer is not in context → exact fallback phrase
#   5. Do NOT add a source line or footer — the pipeline injects those from
#      retrieval metadata to prevent hallucinated URLs.
SYSTEM_PROMPT = """\
You are a facts-only mutual fund FAQ assistant.

Rules:
1. Answer ONLY using the information in the CONTEXT section below.
2. Your answer must be at most 3 sentences. Be concise.
3. Do NOT include investment advice, opinions, or recommendations.
4. Do NOT add a "Source:" line or "Last updated" footer — those are added separately.
5. If the answer is not present in the context, respond with exactly:
   I don't have that information in my current data.

Do NOT fabricate facts, numbers, or URLs.\
"""


def build_prompt(query: str, chunks: list[dict]) -> tuple[str, dict]:
    """
    Build the full RAG prompt for the LLM.

    Args:
        query:  The user's factual question.
        chunks: List of retrieved chunk dicts (from retriever.search()).
                Each dict must have: scheme_name, field, text, source_url, scraped_at.

    Returns:
        (prompt_text, top_chunk_meta)

        prompt_text   — Full prompt string to send to the LLM.
        top_chunk_meta — Dict with source_url, scraped_at, scheme_name from
                         the highest-ranked chunk; passed to format_response()
                         for citation injection. Never taken from LLM output.
    """
    # ── Format each chunk into a labelled block ───────────────────────────────
    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        context_parts.append(
            f"[Chunk {i}]\n"
            f"Scheme:  {chunk.get('scheme_name', 'Unknown')}\n"
            f"Field:   {chunk.get('field', 'Unknown')}\n"
            f"Text:    {chunk.get('text', '')}\n"
            f"Source:  {chunk.get('source_url', '')}\n"
            f"Scraped: {chunk.get('scraped_at', 'unknown')}"
        )

    context_block = "\n\n".join(context_parts)

    # ── Assemble full prompt ──────────────────────────────────────────────────
    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"CONTEXT:\n{context_block}\n\n"
        f"USER QUESTION:\n{query}"
    )

    # ── Extract top-chunk metadata for the formatter ──────────────────────────
    # Uses the highest-ranked (rank=1) chunk. The formatter injects this
    # verified URL into the response — it never trusts the LLM for URLs.
    top_meta = {}
    if chunks:
        top = chunks[0]
        top_meta = {
            "source_url":  top.get("source_url", ""),
            "scraped_at":  top.get("scraped_at", "unknown"),
            "scheme_name": top.get("scheme_name", ""),
            "field":       top.get("field", ""),
        }

    log.info(
        "Prompt built: %d chunk(s), %d chars total",
        len(chunks), len(prompt),
    )
    return prompt, top_meta


# ══════════════════════════════════════════════════════════════════════════════
# SELF-TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Synthetic chunks (mirrors actual metadata.json structure)
    mock_chunks = [
        {
            "chunk_id":    "hdfc_technology_fund__expense_ratio",
            "scheme_name": "HDFC TECHNOLOGY FUND - DIRECT PLAN GROWTH",
            "field":       "expense_ratio",
            "text":        "The direct plan expense ratio of HDFC TECHNOLOGY FUND - DIRECT PLAN GROWTH is 1.11%.",
            "source_url":  "https://groww.in/mutual-funds/hdfc-technology-fund-direct-growth",
            "scraped_at":  "2026-06-30T16:40:43.903849+00:00",
            "score":       0.8432,
            "rank":        1,
        },
        {
            "chunk_id":    "hdfc_technology_fund__fund_overview",
            "scheme_name": "HDFC TECHNOLOGY FUND - DIRECT PLAN GROWTH",
            "field":       "fund_overview",
            "text":        "HDFC TECHNOLOGY FUND - DIRECT PLAN GROWTH is a Equity Sectoral fund managed by HDFC MUTUAL FUND.",
            "source_url":  "https://groww.in/mutual-funds/hdfc-technology-fund-direct-growth",
            "scraped_at":  "2026-06-30T16:40:43.903849+00:00",
            "score":       0.7901,
            "rank":        2,
        },
    ]

    query = "What is the expense ratio of HDFC Technology Fund?"
    prompt, top_meta = build_prompt(query, mock_chunks)

    print("PROMPT BUILDER SELF-TEST")
    print("=" * 60)
    print(f"  Query      : {query}")
    print(f"  Chunks     : {len(mock_chunks)}")
    print(f"  Prompt len : {len(prompt)} chars")
    print(f"  Top meta   : source_url={top_meta['source_url'][:50]}")
    print()
    print("  --- Prompt preview (first 600 chars) ---")
    print(prompt[:600])
    print("  ...")
    print()

    # Assertions
    assert "Answer ONLY" in prompt, "System prompt constraint missing"
    assert "Do NOT add a" in prompt, "No-footer instruction missing"
    assert "expense_ratio" in prompt, "Field label missing from context block"
    assert top_meta["source_url"].startswith("https://"), "top_meta source_url invalid"
    assert "field" in top_meta, "top_meta missing field key"

    print("  [PASS] All assertions passed.")
    print("=" * 60)
