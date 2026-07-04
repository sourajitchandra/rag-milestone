"""
chunker.py — Phase 4A: Text Chunking (Semantic Grouping)
----------------------------------------------------------
Converts each scheme's _facts.json into semantically grouped text chunks
with embedded metadata for FAISS indexing.

Strategy (revised from 1-per-field to semantic grouping):
  7 chunk groups per scheme × 5 schemes = 35 chunks total

  1. Fund Overview   — scheme_name + category + amc + riskometer
  2. NAV             — nav (+ nav_date if available)
  3. Expense Ratio   — expense_ratio
  4. Exit Load       — exit_load
  5. Investment Mins  — minimum_sip + minimum_lumpsum + lock_in_period
  6. Benchmark       — benchmark_index
  7. Fund Managers   — fund_managers

Each chunk includes the scheme name in its text body to enable
retrieval discrimination between funds with similar field values.

Output: data/processed/chunks.json

Usage:
    python src/chunker.py
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
PROC_DIR = BASE_DIR / "data" / "processed"

# ── Scheme slugs (matches scraper/parser) ─────────────────────────────────────
SLUGS = [
    "hdfc_technology_fund",
    "hdfc_silver_etf_fof",
    "hdfc_defence_fund",
    "hdfc_liquid_fund",
    "hdfc_nifty500_multicap",
]


# ══════════════════════════════════════════════════════════════════════════════
# CHUNK BUILDERS — one function per semantic group
# ══════════════════════════════════════════════════════════════════════════════

def _build_fund_overview(facts: dict) -> dict | None:
    """Group 1: scheme_name + category + amc + riskometer."""
    name = facts.get("scheme_name")
    cat  = facts.get("category")
    amc  = facts.get("amc")
    risk = facts.get("riskometer")

    if not name:
        return None

    parts = [f"{name} is a {cat} fund" if cat else f"{name} is a mutual fund"]
    if amc:
        parts[0] += f" managed by {amc}."
    else:
        parts[0] += "."
    if risk:
        parts.append(f"It is classified as {risk} risk on the riskometer.")

    text = " ".join(parts)

    return _make_chunk(
        slug=facts["slug"],
        field="fund_overview",
        text=text,
        facts=facts,
    )


def _build_nav(facts: dict) -> dict | None:
    """Group 2: NAV (+ nav_date if available)."""
    name = facts.get("scheme_name")
    nav  = facts.get("nav")
    if not name or not nav:
        return None

    nav_date = facts.get("nav_date")
    if nav_date:
        text = f"The latest NAV of {name} is {nav} (as of {nav_date})."
    else:
        text = f"The latest NAV of {name} is {nav}."

    return _make_chunk(
        slug=facts["slug"],
        field="nav",
        text=text,
        facts=facts,
    )


def _build_expense_ratio(facts: dict) -> dict | None:
    """Group 3: Expense ratio."""
    name = facts.get("scheme_name")
    er   = facts.get("expense_ratio")
    if not name or not er:
        return None

    text = f"The direct plan expense ratio of {name} is {er}."

    return _make_chunk(
        slug=facts["slug"],
        field="expense_ratio",
        text=text,
        facts=facts,
    )


def _build_exit_load(facts: dict) -> dict | None:
    """Group 4: Exit load."""
    name = facts.get("scheme_name")
    el   = facts.get("exit_load")
    if not name or not el:
        return None

    # Normalise: if exit_load already starts with "Exit load of ...",
    # use it as-is; otherwise wrap it.
    if el.lower().startswith("exit load"):
        text = f"The exit load for {name} is: {el}"
    elif el.lower() == "nil":
        text = f"{name} has no exit load (Nil)."
    else:
        text = f"The exit load for {name} is {el}."

    return _make_chunk(
        slug=facts["slug"],
        field="exit_load",
        text=text,
        facts=facts,
    )


def _build_investment_minimums(facts: dict) -> dict | None:
    """Group 5: minimum_sip + minimum_lumpsum + lock_in_period."""
    name    = facts.get("scheme_name")
    sip     = facts.get("minimum_sip")
    lump    = facts.get("minimum_lumpsum")
    lock_in = facts.get("lock_in_period")

    if not name or (not sip and not lump):
        return None

    parts = []
    if sip:
        parts.append(f"The minimum SIP amount for {name} is {sip}.")
    if lump:
        parts.append(f"The minimum lumpsum investment is {lump}.")
    if lock_in:
        parts.append(f"Lock-in period: {lock_in}.")

    text = " ".join(parts)

    return _make_chunk(
        slug=facts["slug"],
        field="investment_minimums",
        text=text,
        facts=facts,
    )


def _build_benchmark(facts: dict) -> dict | None:
    """Group 6: Benchmark index."""
    name  = facts.get("scheme_name")
    bench = facts.get("benchmark_index")
    if not name or not bench:
        return None

    text = f"The benchmark index for {name} is {bench}."

    return _make_chunk(
        slug=facts["slug"],
        field="benchmark_index",
        text=text,
        facts=facts,
    )


def _build_fund_managers(facts: dict) -> dict | None:
    """Group 7: Fund managers."""
    name = facts.get("scheme_name")
    mgrs = facts.get("fund_managers")
    if not name or not mgrs:
        return None

    text = f"{name} is managed by {mgrs}."

    return _make_chunk(
        slug=facts["slug"],
        field="fund_managers",
        text=text,
        facts=facts,
    )


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _make_chunk(slug: str, field: str, text: str, facts: dict) -> dict:
    """Create a chunk dict with text + metadata."""
    return {
        "chunk_id":    f"{slug}__{field}",
        "scheme_name": facts.get("scheme_name", slug),
        "field":       field,
        "text":        text.strip(),
        "source_url":  facts.get("source_url", ""),
        "scraped_at":  facts.get("scraped_at", "unknown"),
    }


# All builders in order
CHUNK_BUILDERS = [
    _build_fund_overview,
    _build_nav,
    _build_expense_ratio,
    _build_exit_load,
    _build_investment_minimums,
    _build_benchmark,
    _build_fund_managers,
]


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def build_chunks() -> list[dict]:
    """Load all facts files and build chunks. Returns the chunk list."""
    all_chunks: list[dict] = []

    for slug in SLUGS:
        facts_path = PROC_DIR / f"{slug}_facts.json"
        if not facts_path.exists():
            log.warning("  Facts file not found: %s — skipping", facts_path)
            continue

        facts = json.loads(facts_path.read_text(encoding="utf-8"))
        log.info("━━━ Chunking: %s", facts.get("scheme_name", slug))

        scheme_chunks = []
        for builder in CHUNK_BUILDERS:
            chunk = builder(facts)
            if chunk:
                scheme_chunks.append(chunk)
            else:
                log.warning("  Skipped empty chunk from %s", builder.__name__)

        log.info("  → %d chunks created", len(scheme_chunks))
        all_chunks.extend(scheme_chunks)

    return all_chunks


def save_chunks(chunks: list[dict]) -> Path:
    """Save chunks to data/processed/chunks.json."""
    out_path = PROC_DIR / "chunks.json"
    out_path.write_text(
        json.dumps(chunks, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("✓ chunks.json saved → %s (%d chunks)", out_path, len(chunks))
    return out_path


def main() -> None:
    log.info("╔══════════════════════════════════════════════════════════╗")
    log.info("║  Mutual Fund FAQ Assistant — Phase 4A: Chunker           ║")
    log.info("╚══════════════════════════════════════════════════════════╝")

    chunks = build_chunks()
    save_chunks(chunks)

    # ── Summary ───────────────────────────────────────────────────────────────
    log.info("")
    log.info("═" * 60)
    log.info("CHUNKING SUMMARY")
    log.info("═" * 60)

    # Group by scheme
    from collections import Counter
    scheme_counts = Counter(c["scheme_name"] for c in chunks)
    field_counts  = Counter(c["field"] for c in chunks)

    log.info("  Total chunks: %d", len(chunks))
    log.info("")
    log.info("  By scheme:")
    for name, count in scheme_counts.items():
        log.info("    %-50s %d chunks", name[:50], count)
    log.info("")
    log.info("  By field group:")
    for field, count in field_counts.items():
        log.info("    %-25s %d chunks", field, count)

    # Validate metadata
    missing_source = sum(1 for c in chunks if not c.get("source_url"))
    missing_scraped = sum(1 for c in chunks if not c.get("scraped_at") or c["scraped_at"] == "unknown")
    log.info("")
    log.info("  Metadata check:")
    log.info("    Missing source_url : %d", missing_source)
    log.info("    Missing scraped_at : %d", missing_scraped)

    # Token length estimate
    avg_tokens = sum(len(c["text"].split()) for c in chunks) / max(len(chunks), 1)
    log.info("    Avg tokens/chunk   : %.1f", avg_tokens)

    log.info("━" * 60)
    if len(chunks) == 35 and missing_source == 0:
        log.info("  ✓ All chunks valid. Ready for Phase 4B (embedder.py).")
    else:
        log.warning("  ⚠ Expected 35 chunks, got %d. Check warnings above.", len(chunks))
        log.error("Aborting: chunking incomplete. Vector store will NOT be refreshed.")
        sys.exit(1)
    log.info("═" * 60)


if __name__ == "__main__":
    main()
