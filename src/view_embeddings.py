"""
view_embeddings.py — Visualise FAISS chunk embeddings in 2-D
--------------------------------------------------------------
Loads the persisted FAISS index + metadata and projects the 768-dim
BGE embeddings down to 2-D with PCA, then renders two side-by-side
scatter plots:
  • Left  — coloured by FIELD TYPE  (expense_ratio, nav, …)
  • Right — coloured by SCHEME NAME (hdfc_technology_fund, …)

Hovering over any point shows the full chunk text in a tooltip.

Usage:
    python src/view_embeddings.py
"""

import json
import textwrap
from pathlib import Path

import faiss
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from sklearn.decomposition import PCA

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).resolve().parent.parent
INDEX_PATH    = BASE_DIR / "vector_store" / "faiss_index.bin"
METADATA_PATH = BASE_DIR / "vector_store" / "metadata.json"

# ── Colour palettes ───────────────────────────────────────────────────────────
FIELD_COLOURS = {
    "fund_overview":       "#4C72B0",
    "nav":                 "#DD8452",
    "expense_ratio":       "#55A868",
    "exit_load":           "#C44E52",
    "investment_minimums": "#8172B3",
    "benchmark_index":     "#937860",
    "fund_managers":       "#DA8BC3",
}

SCHEME_COLOURS = {
    "hdfc_technology_fund":   "#1f77b4",
    "hdfc_silver_etf_fof":    "#ff7f0e",
    "hdfc_defence_fund":      "#2ca02c",
    "hdfc_liquid_fund":       "#d62728",
    "hdfc_nifty500_multicap": "#9467bd",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_data() -> tuple[np.ndarray, list[dict]]:
    """Reconstruct embeddings from the FAISS index and load metadata."""
    if not INDEX_PATH.exists():
        raise FileNotFoundError(f"FAISS index not found: {INDEX_PATH}\nRun src/embedder.py first.")
    if not METADATA_PATH.exists():
        raise FileNotFoundError(f"Metadata not found: {METADATA_PATH}\nRun src/embedder.py first.")

    index    = faiss.read_index(str(INDEX_PATH))
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))

    n = index.ntotal
    dim = index.d
    vectors = np.zeros((n, dim), dtype=np.float32)
    for i in range(n):
        vectors[i] = index.reconstruct(i)

    print(f"[OK] Loaded {n} embeddings (dim={dim}) from {INDEX_PATH.name}")
    print(f"[OK] Loaded {len(metadata)} metadata entries")
    return vectors, metadata


def reduce_to_2d(vectors: np.ndarray) -> np.ndarray:
    """Project 768-dim embeddings to 2-D with PCA."""
    pca = PCA(n_components=2, random_state=42)
    coords = pca.fit_transform(vectors)
    var = pca.explained_variance_ratio_
    print(f"[OK] PCA variance explained: PC1={var[0]:.1%}  PC2={var[1]:.1%}  total={sum(var):.1%}")
    return coords


def parse_chunk_id(chunk_id: str) -> tuple[str, str]:
    """
    Split chunk_id like 'hdfc_technology_fund__expense_ratio'
    into (scheme_key, field_key).
    """
    parts = chunk_id.split("__", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return chunk_id, chunk_id


def make_legend(colour_map: dict, title: str) -> list[mpatches.Patch]:
    return [
        mpatches.Patch(color=c, label=label.replace("_", " ").title())
        for label, c in colour_map.items()
    ]


# ── Plot ──────────────────────────────────────────────────────────────────────

def plot(coords: np.ndarray, metadata: list[dict]) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    fig.patch.set_facecolor("#0f1117")
    for ax in axes:
        ax.set_facecolor("#1a1d27")
        ax.tick_params(colors="#aaaaaa")
        for spine in ax.spines.values():
            spine.set_edgecolor("#333344")

    # annotation box (shared, shown on hover)
    annot_box = axes[0].annotate(
        "", xy=(0, 0), xytext=(15, 15),
        textcoords="offset points",
        bbox=dict(boxstyle="round,pad=0.5", fc="#1e2030", ec="#7c83fd", lw=1.2, alpha=0.95),
        arrowprops=dict(arrowstyle="->", color="#7c83fd"),
        fontsize=8, color="#e0e0f0",
        visible=False,
        zorder=10,
    )

    all_scatter = []   # (scatter_obj, axis_index, labels_list)
    x, y = coords[:, 0], coords[:, 1]

    # ── Panel 1: colour by field ───────────────────────────────────────────────
    ax1 = axes[0]
    ax1.set_title("Embeddings by Field Type", color="#e0e0f0", fontsize=13, pad=10)
    ax1.set_xlabel("PC 1", color="#888899")
    ax1.set_ylabel("PC 2", color="#888899")

    field_scatter_map: dict[str, object] = {}
    for i, meta in enumerate(metadata):
        scheme_key, field_key = parse_chunk_id(meta["chunk_id"])
        colour = FIELD_COLOURS.get(field_key, "#cccccc")
        sc = ax1.scatter(x[i], y[i], c=colour, s=90, zorder=5,
                         edgecolors="#ffffff22", linewidths=0.4)
        field_scatter_map.setdefault(field_key, []).append((x[i], y[i], i))

    # Re-draw as grouped scatter so legend works cleanly
    ax1.cla()
    ax1.set_facecolor("#1a1d27")
    ax1.set_title("Embeddings by Field Type", color="#e0e0f0", fontsize=13, pad=10)
    ax1.set_xlabel("PC 1", color="#888899")
    ax1.set_ylabel("PC 2", color="#888899")
    ax1.tick_params(colors="#aaaaaa")

    for field_key, pts in field_scatter_map.items():
        xi = [p[0] for p in pts]
        yi = [p[1] for p in pts]
        idxs = [p[2] for p in pts]
        colour = FIELD_COLOURS.get(field_key, "#cccccc")
        sc = ax1.scatter(xi, yi, c=colour, s=90, zorder=5,
                         edgecolors="#ffffff33", linewidths=0.5,
                         label=field_key.replace("_", " ").title())
        all_scatter.append((sc, 0, idxs))

    ax1.legend(
        loc="upper left", fontsize=8,
        facecolor="#1a1d27", edgecolor="#444455", labelcolor="#ccccdd",
        title="Field", title_fontsize=9,
    )

    # ── Panel 2: colour by scheme ──────────────────────────────────────────────
    ax2 = axes[1]
    ax2.set_facecolor("#1a1d27")
    ax2.set_title("Embeddings by Scheme", color="#e0e0f0", fontsize=13, pad=10)
    ax2.set_xlabel("PC 1", color="#888899")
    ax2.set_ylabel("PC 2", color="#888899")
    ax2.tick_params(colors="#aaaaaa")

    scheme_scatter_map: dict[str, list] = {}
    for i, meta in enumerate(metadata):
        scheme_key, _ = parse_chunk_id(meta["chunk_id"])
        scheme_scatter_map.setdefault(scheme_key, []).append((x[i], y[i], i))

    for scheme_key, pts in scheme_scatter_map.items():
        xi = [p[0] for p in pts]
        yi = [p[1] for p in pts]
        idxs = [p[2] for p in pts]
        colour = SCHEME_COLOURS.get(scheme_key, "#cccccc")
        label = scheme_key.replace("hdfc_", "HDFC ").replace("_", " ").title()
        sc = ax2.scatter(xi, yi, c=colour, s=90, zorder=5,
                         edgecolors="#ffffff33", linewidths=0.5, label=label)
        all_scatter.append((sc, 1, idxs))

    ax2.legend(
        loc="upper left", fontsize=7.5,
        facecolor="#1a1d27", edgecolor="#444455", labelcolor="#ccccdd",
        title="Scheme", title_fontsize=9,
    )

    # ── Hover tooltip ─────────────────────────────────────────────────────────
    # One annotation per axis
    annots = []
    for ax in axes:
        a = ax.annotate(
            "", xy=(0, 0), xytext=(15, 15),
            textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.6", fc="#1e2030", ec="#7c83fd", lw=1.2, alpha=0.96),
            arrowprops=dict(arrowstyle="->", color="#7c83fd"),
            fontsize=8, color="#e0e0f0",
            visible=False, zorder=20,
        )
        annots.append(a)

    def on_hover(event):
        for ann in annots:
            ann.set_visible(False)

        if event.inaxes not in axes:
            fig.canvas.draw_idle()
            return

        ax_idx = list(axes).index(event.inaxes)
        ann = annots[ax_idx]

        for sc, sc_ax_idx, idxs in all_scatter:
            if sc_ax_idx != ax_idx:
                continue
            cont, info = sc.contains(event)
            if cont:
                ind = info["ind"][0]          # index within this scatter's points
                chunk_idx = idxs[ind]
                meta = metadata[chunk_idx]
                scheme_key, field_key = parse_chunk_id(meta["chunk_id"])

                wrapped_text = "\n".join(textwrap.wrap(meta["text"], width=55))
                tip = (
                    f"chunk_id : {meta['chunk_id']}\n"
                    f"field    : {field_key}\n"
                    f"scheme   : {scheme_key}\n"
                    f"-------------------------------------\n"
                    f"{wrapped_text}\n"
                    f"-------------------------------------\n"
                    f"source   : {meta['source_url']}\n"
                    f"scraped  : {meta['scraped_at'][:10]}"
                )
                ann.set_text(tip)
                pos = sc.get_offsets()[ind]
                ann.xy = pos
                ann.set_visible(True)
                fig.canvas.draw_idle()
                return

        fig.canvas.draw_idle()

    fig.canvas.mpl_connect("motion_notify_event", on_hover)

    # ── Print table of all chunks ──────────────────────────────────────────────
    print("\n" + "=" * 72)
    print(f"  {'#':<4}  {'chunk_id':<45}  {'PC1':>7}  {'PC2':>7}")
    print("-" * 72)
    for i, meta in enumerate(metadata):
        print(f"  {i:<4}  {meta['chunk_id']:<45}  {x[i]:>7.4f}  {y[i]:>7.4f}")
    print("=" * 72)
    print(f"\n  35 chunks | 768 dims -> 2-D PCA")
    print("  Hover over any point in the plot window to see full chunk text.\n")

    plt.suptitle(
        "Mutual Fund FAQ - BGE-base Chunk Embeddings (PCA 2-D Projection)",
        color="#e8e8f8", fontsize=14, fontweight="bold", y=1.01,
    )
    plt.tight_layout()
    plt.show()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    print("+" + "=" * 58 + "+")
    print("|         Embedding Visualiser -- Phase 5 Inspection       |")
    print("+" + "=" * 58 + "+\n")

    vectors, metadata = load_data()
    coords            = reduce_to_2d(vectors)
    plot(coords, metadata)


if __name__ == "__main__":
    main()
