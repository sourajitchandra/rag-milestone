"""
embedder.py — Phase 4B + Phase 5: Embedding & Vector Store
------------------------------------------------------------
Generates BGE embeddings for all chunks and builds a persisted FAISS index.

Embedding model: BAAI/bge-base-en-v1.5 (dim=768, normalize_embeddings=True)
Vector store:    faiss.IndexFlatIP (inner-product on normalized vectors = cosine)

Inputs:  data/processed/chunks.json
Outputs: vector_store/faiss_index.bin
         vector_store/metadata.json

Usage:
    python src/embedder.py
"""

import json
import logging
import numpy as np
from pathlib import Path

import faiss
from sentence_transformers import SentenceTransformer

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).resolve().parent.parent
CHUNKS_PATH = BASE_DIR / "data" / "processed" / "chunks.json"
VS_DIR      = BASE_DIR / "vector_store"
VS_DIR.mkdir(parents=True, exist_ok=True)

INDEX_PATH    = VS_DIR / "faiss_index.bin"
METADATA_PATH = VS_DIR / "metadata.json"

# ── Model config ──────────────────────────────────────────────────────────────
MODEL_NAME    = "BAAI/bge-base-en-v1.5"
EMBEDDING_DIM = 768


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 4B — EMBEDDING
# ══════════════════════════════════════════════════════════════════════════════

def load_chunks() -> list[dict]:
    """Load chunks from data/processed/chunks.json."""
    if not CHUNKS_PATH.exists():
        raise FileNotFoundError(f"chunks.json not found at {CHUNKS_PATH}. Run chunker.py first.")
    chunks = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))
    log.info("Loaded %d chunks from %s", len(chunks), CHUNKS_PATH)
    return chunks


def load_model() -> SentenceTransformer:
    """Load the BGE embedding model."""
    log.info("Loading embedding model: %s", MODEL_NAME)
    model = SentenceTransformer(MODEL_NAME)
    log.info("Model loaded. Embedding dimension: %d", model.get_embedding_dimension())
    return model


def embed_chunks(model: SentenceTransformer, chunks: list[dict]) -> np.ndarray:
    """
    Generate normalised embeddings for all chunk texts.
    BGE requires normalize_embeddings=True for cosine similarity.
    """
    texts = [chunk["text"] for chunk in chunks]
    log.info("Embedding %d chunks...", len(texts))

    vectors = model.encode(
        texts,
        normalize_embeddings=True,  # required for BGE cosine similarity
        show_progress_bar=True,
        batch_size=32,
    )

    log.info("Embeddings shape: %s", vectors.shape)
    return vectors


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 5 — FAISS INDEX BUILD & PERSIST
# ══════════════════════════════════════════════════════════════════════════════

def build_index(vectors: np.ndarray) -> faiss.Index:
    """
    Build a FAISS index from the embedding vectors.
    Uses IndexFlatIP (inner product) because BGE vectors are L2-normalised,
    so inner product = cosine similarity. Higher score = more similar.
    """
    dim = vectors.shape[1]
    log.info("Building FAISS IndexFlatIP (dim=%d)", dim)

    index = faiss.IndexFlatIP(dim)
    index.add(vectors.astype(np.float32))

    log.info("Index built. Total vectors: %d", index.ntotal)
    return index


def save_index(index: faiss.Index) -> None:
    """Persist the FAISS index to disk."""
    faiss.write_index(index, str(INDEX_PATH))
    size_kb = INDEX_PATH.stat().st_size / 1024
    log.info("✓ FAISS index saved → %s (%.1f KB)", INDEX_PATH, size_kb)


def save_metadata(chunks: list[dict]) -> None:
    """
    Save chunk metadata alongside the index.
    The i-th entry in metadata corresponds to the i-th vector in the index.
    """
    metadata = []
    for chunk in chunks:
        metadata.append({
            "chunk_id":    chunk["chunk_id"],
            "scheme_name": chunk["scheme_name"],
            "field":       chunk["field"],
            "text":        chunk["text"],
            "source_url":  chunk["source_url"],
            "scraped_at":  chunk["scraped_at"],
        })

    METADATA_PATH.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("✓ Metadata saved → %s (%d entries)", METADATA_PATH, len(metadata))


# ══════════════════════════════════════════════════════════════════════════════
# VERIFICATION
# ══════════════════════════════════════════════════════════════════════════════

def verify_index(model: SentenceTransformer, index: faiss.Index, metadata: list[dict]) -> None:
    """
    Smoke test: embed known queries and verify the expected chunk appears
    in the top-3 results (exit criterion: 3/3 target-in-top-3).
    Also reports whether the target is the top-1 hit for additional insight.
    """
    test_queries = [
        ("What is the expense ratio of HDFC Technology Fund?", "expense_ratio", "hdfc_technology_fund"),
        ("Who manages HDFC Liquid Fund?", "fund_managers", "hdfc_liquid_fund"),
        ("What is the NAV of HDFC Defence Fund?", "nav", "hdfc_defence_fund"),
    ]

    log.info("")
    log.info("═" * 60)
    log.info("INDEX VERIFICATION (smoke tests — exit criterion: 3/3 in top-3)")
    log.info("═" * 60)

    top1_hits = 0
    top3_hits = 0

    for query, expected_field, expected_slug in test_queries:
        q_vec = model.encode([query], normalize_embeddings=True).astype(np.float32)
        distances, indices = index.search(q_vec, 3)

        top1_meta  = metadata[indices[0][0]]
        top1_score = distances[0][0]

        # Check if target appears anywhere in top-3
        in_top3 = False
        in_top1 = False
        target_rank = None
        for rank, (idx, score) in enumerate(zip(indices[0], distances[0])):
            chunk_id = metadata[idx]["chunk_id"]
            if expected_field in chunk_id and expected_slug in chunk_id:
                in_top3 = True
                target_rank = rank + 1
                if rank == 0:
                    in_top1 = True
                break

        top3_hits += int(in_top3)
        top1_hits += int(in_top1)

        if in_top3:
            rank_label = "rank #1 ✓✓" if in_top1 else f"rank #{target_rank} (top-3 ✓)"
            log.info("  ✓ Query  : %s", query)
            log.info("    Target : %s_%s — found at %s (top-1 score=%.4f)",
                     expected_slug, expected_field, rank_label, top1_score)
        else:
            log.warning("  ✗ Query  : %s", query)
            log.warning("    Target : %s_%s — NOT in top-3", expected_slug, expected_field)
            log.warning("    Top-1  : %s (score=%.4f)", top1_meta["chunk_id"], top1_score)

    log.info("━" * 60)
    log.info("  Top-1 exact hits : %d / %d", top1_hits, len(test_queries))
    log.info("  Top-3 hits       : %d / %d  ← exit criterion", top3_hits, len(test_queries))
    if top3_hits == len(test_queries):
        log.info("  ✓ EXIT CRITERION MET — all targets found in top-3.")
    else:
        log.warning("  ✗ EXIT CRITERION NOT MET — %d targets missing from top-3.",
                    len(test_queries) - top3_hits)
    log.info("═" * 60)


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    log.info("╔══════════════════════════════════════════════════════════╗")
    log.info("║  Mutual Fund FAQ Assistant — Phase 4B+5: Embed & Index   ║")
    log.info("╚══════════════════════════════════════════════════════════╝")

    # ── Phase 4B: Embed ───────────────────────────────────────────────────────
    chunks = load_chunks()
    model  = load_model()
    vectors = embed_chunks(model, chunks)

    # ── Phase 5: Build & persist FAISS index ──────────────────────────────────
    index = build_index(vectors)
    save_index(index)
    save_metadata(chunks)

    # ── Verify ────────────────────────────────────────────────────────────────
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    verify_index(model, index, metadata)

    # ── Summary ───────────────────────────────────────────────────────────────
    log.info("")
    log.info("Pipeline complete:")
    log.info("  Chunks embedded  : %d", len(chunks))
    log.info("  Vector dimension : %d", EMBEDDING_DIM)
    log.info("  Index vectors    : %d", index.ntotal)
    log.info("  Index file       : %s", INDEX_PATH)
    log.info("  Metadata file    : %s", METADATA_PATH)


if __name__ == "__main__":
    main()
