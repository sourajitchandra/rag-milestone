"""
web_app.py — Phase 9: Browser-Based Chat UI (Streamlit)
---------------------------------------------------------
Provides a clean, disclaimer-aware chat interface that wraps the
process_query() pipeline from app.py.

Features:
  - Persistent chat history (via st.session_state)
  - Disclaimer banner on load
  - 5 example prompt buttons (3 factual + 1 advisory + 1 edge-case)
  - Full pipeline: classify → rate-limit → retrieve → LLM → format
  - Graceful error display

Usage:
    streamlit run src/web_app.py
    (from project root)
"""

import sys
import logging
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
# Ensure project root is on sys.path so imports from src/ work correctly
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st

from src.classifier import classify_query, get_refusal_response
from src.retriever import Retriever
from src.rate_limiter import RateLimiter, RateLimitExceeded
from src.prompt_builder import build_prompt
from src.llm import call_llm
from src.formatter import format_response

# ── Logging (suppress noisy INFO from pipeline inside Streamlit) ──────────────
logging.basicConfig(level=logging.WARNING)

# ══════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG  (must be the very first Streamlit call)
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="HDFC Mutual Fund FAQ Assistant",
    page_icon="📈",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ══════════════════════════════════════════════════════════════════════════════
# CUSTOM CSS
# ══════════════════════════════════════════════════════════════════════════════

st.markdown(
    """
    <style>
    /* ── Fonts ────────────────────────────────────────────────────────── */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    /* ── Hide default Streamlit chrome ───────────────────────────────── */
    #MainMenu, footer, header { visibility: hidden; }

    /* ── Page background ─────────────────────────────────────────────── */
    .stApp {
        background: linear-gradient(135deg, #0f1117 0%, #1a1d27 60%, #141820 100%);
        min-height: 100vh;
    }

    /* ── Disclaimer banner ───────────────────────────────────────────── */
    .disclaimer-banner {
        background: linear-gradient(90deg, rgba(255,193,7,0.12) 0%, rgba(255,152,0,0.08) 100%);
        border: 1px solid rgba(255,193,7,0.35);
        border-radius: 12px;
        padding: 14px 20px;
        margin-bottom: 20px;
        color: #ffc107;
        font-size: 0.82rem;
        line-height: 1.5;
    }

    /* ── Chat messages ───────────────────────────────────────────────── */
    .user-bubble {
        background: linear-gradient(135deg, #2563eb, #1d4ed8);
        color: #fff;
        padding: 12px 18px;
        border-radius: 18px 18px 4px 18px;
        margin: 8px 0 8px 40px;
        font-size: 0.93rem;
        line-height: 1.55;
        box-shadow: 0 2px 12px rgba(37,99,235,0.3);
    }

    .assistant-bubble {
        background: linear-gradient(135deg, #1e2535, #252d3f);
        border: 1px solid rgba(255,255,255,0.08);
        color: #e2e8f0;
        padding: 14px 18px;
        border-radius: 18px 18px 18px 4px;
        margin: 8px 40px 8px 0;
        font-size: 0.93rem;
        line-height: 1.65;
        box-shadow: 0 2px 12px rgba(0,0,0,0.3);
    }

    .assistant-bubble .source-line {
        color: #60a5fa;
        font-size: 0.82rem;
        margin-top: 8px;
    }

    .assistant-bubble .footer-line {
        color: #6b7280;
        font-size: 0.78rem;
        margin-top: 4px;
        border-top: 1px solid rgba(255,255,255,0.06);
        padding-top: 6px;
    }

    .refusal-bubble {
        background: linear-gradient(135deg, #1f1a2e, #261e38);
        border: 1px solid rgba(167,139,250,0.25);
        color: #c4b5fd;
        padding: 14px 18px;
        border-radius: 18px 18px 18px 4px;
        margin: 8px 40px 8px 0;
        font-size: 0.93rem;
        line-height: 1.65;
    }

    /* ── Example prompt buttons ──────────────────────────────────────── */
    .example-label {
        color: #6b7280;
        font-size: 0.78rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 8px;
    }

    /* ── Header ──────────────────────────────────────────────────────── */
    .app-header {
        text-align: center;
        margin-bottom: 24px;
    }
    .app-header h1 {
        font-size: 1.9rem;
        font-weight: 700;
        background: linear-gradient(135deg, #60a5fa, #a78bfa);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 4px;
    }
    .app-header p {
        color: #9ca3af;
        font-size: 0.88rem;
    }

    /* ── Stacked messages container ──────────────────────────────────── */
    .chat-container {
        max-height: 520px;
        overflow-y: auto;
        padding: 4px 0;
    }

    /* ── Input area tweaks ───────────────────────────────────────────── */
    .stTextInput > div > div > input {
        background: #1e2535;
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 12px;
        color: #e2e8f0;
        padding: 12px 16px;
        font-size: 0.93rem;
    }
    .stTextInput > div > div > input:focus {
        border-color: #3b82f6;
        box-shadow: 0 0 0 2px rgba(59,130,246,0.2);
    }

    /* ── Button tweaks ───────────────────────────────────────────────── */
    .stButton > button {
        border-radius: 10px;
        font-size: 0.82rem;
        font-weight: 500;
        transition: all 0.2s ease;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ══════════════════════════════════════════════════════════════════════════════
# CACHED RESOURCES  (loaded once per session, not per query)
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_resource(show_spinner="Loading knowledge base…")
def load_retriever() -> Retriever:
    """Initialise Retriever once — loads BGE model + FAISS index."""
    return Retriever()


@st.cache_resource
def load_rate_limiter() -> RateLimiter:
    """Shared rate-limiter across the session (tracks Groq quota)."""
    return RateLimiter()


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE  (mirrors app.py process_query, but Streamlit-aware)
# ══════════════════════════════════════════════════════════════════════════════

def _classify_bubble(intent: str) -> str:
    """Return the CSS class to use for the assistant bubble."""
    if intent in ("advisory", "pii", "empty"):
        return "refusal-bubble"
    return "assistant-bubble"


def _render_response(text: str, intent: str) -> str:
    """
    Convert the raw formatted response text into HTML for the chat bubble.
    Linkifies the 'Source:' line and styles the footer.
    """
    css_class = _classify_bubble(intent)
    lines = text.split("\n")
    html_parts = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith("source:"):
            url = stripped[len("source:"):].strip()
            html_parts.append(
                f'<div class="source-line">🔗 Source: '
                f'<a href="{url}" target="_blank" rel="noopener noreferrer">{url}</a></div>'
            )
        elif stripped.lower().startswith("last updated from sources:"):
            html_parts.append(f'<div class="footer-line">🗓 {stripped}</div>')
        else:
            html_parts.append(f"<p style='margin:0 0 6px 0'>{stripped}</p>")

    inner = "\n".join(html_parts)
    return f'<div class="{css_class}">{inner}</div>'


def run_pipeline(query: str, retriever: Retriever, rate_limiter: RateLimiter) -> tuple[str, str]:
    """
    Run the full RAG pipeline for a user query.

    Returns:
        (formatted_response, intent)
    """
    # Step 1 — Classify
    classification = classify_query(query)
    intent = classification["intent"]

    # Step 2 — Refusals (no LLM)
    if intent != "factual":
        return get_refusal_response(intent), intent

    # Step 3 — Rate limit
    try:
        rate_limiter.check_and_record()
    except RateLimitExceeded as e:
        return str(e), "rate_limited"

    # Step 4 — Retrieve
    chunks = retriever.search(query, top_k=3)
    if not chunks:
        return "I don't have information about that in my current data.\n\nLast updated from sources: N/A", "factual"

    # Step 5 — Prompt
    prompt, top_meta = build_prompt(query, chunks)

    # Step 6 — LLM
    try:
        raw_response = call_llm(prompt)
    except RuntimeError as exc:
        return f"⚠️ LLM error: {exc}", "error"

    # Step 7 — Format
    formatted = format_response(raw_response, top_meta)
    return formatted, intent


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE  initialisation
# ══════════════════════════════════════════════════════════════════════════════

if "messages" not in st.session_state:
    st.session_state.messages = []          # list of {"role", "content", "intent"}

if "pending_query" not in st.session_state:
    st.session_state.pending_query = ""     # set by example-prompt buttons

# ══════════════════════════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════════════════════════

st.markdown(
    """
    <div class="app-header">
        <h1>📈 HDFC Mutual Fund FAQ</h1>
        <p>Instant, factual answers about 5 HDFC schemes — powered by RAG</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ══════════════════════════════════════════════════════════════════════════════
# DISCLAIMER BANNER
# ══════════════════════════════════════════════════════════════════════════════

st.markdown(
    """
    <div class="disclaimer-banner">
        ⚠️ <strong>Important Disclaimer:</strong> This assistant provides
        <em>factual information only</em> about select HDFC mutual fund schemes
        (Technology, Silver ETF FoF, Defence, Liquid, and Nifty500 Multicap).
        It does <strong>not</strong> provide investment advice, recommendations,
        or opinions. Data is sourced from Groww and may not reflect the latest
        values. Always verify with official sources and consult a SEBI-registered
        financial advisor before investing.
    </div>
    """,
    unsafe_allow_html=True,
)

# ══════════════════════════════════════════════════════════════════════════════
# LOAD RESOURCES
# ══════════════════════════════════════════════════════════════════════════════

retriever = load_retriever()
rate_limiter = load_rate_limiter()

# ══════════════════════════════════════════════════════════════════════════════
# EXAMPLE PROMPTS
# ══════════════════════════════════════════════════════════════════════════════

st.markdown('<div class="example-label">Try an example</div>', unsafe_allow_html=True)

example_prompts = [
    "What is the expense ratio of HDFC Technology Fund?",
    "What is the exit load for HDFC Silver ETF FoF?",
    "Who manages the HDFC Defence Fund?",
    "What is the minimum SIP for HDFC Liquid Fund?",
    "Should I invest in HDFC Technology Fund?",
]

cols = st.columns(len(example_prompts))
for col, prompt in zip(cols, example_prompts):
    if col.button(prompt[:38] + ("…" if len(prompt) > 38 else ""), key=f"ex_{prompt[:20]}"):
        st.session_state.pending_query = prompt

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# CHAT HISTORY DISPLAY
# ══════════════════════════════════════════════════════════════════════════════

for msg in st.session_state.messages:
    if msg["role"] == "user":
        st.markdown(
            f'<div class="user-bubble">🧑 {msg["content"]}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            _render_response(msg["content"], msg.get("intent", "factual")),
            unsafe_allow_html=True,
        )

# ══════════════════════════════════════════════════════════════════════════════
# INPUT + PROCESSING
# ══════════════════════════════════════════════════════════════════════════════

# Pre-fill from example button if clicked
default_val = st.session_state.pop("pending_query", "")

with st.form(key="query_form", clear_on_submit=True):
    user_input = st.text_input(
        label="Ask a question",
        value=default_val,
        placeholder="e.g. What is the NAV of HDFC Liquid Fund?",
        label_visibility="collapsed",
    )
    submit = st.form_submit_button("Send ➤", use_container_width=True)

if submit and user_input.strip():
    query = user_input.strip()

    # Add user message to history
    st.session_state.messages.append({"role": "user", "content": query})

    # Run pipeline with spinner
    with st.spinner("Thinking…"):
        response, intent = run_pipeline(query, retriever, rate_limiter)

    # Add assistant message to history
    st.session_state.messages.append({"role": "assistant", "content": response, "intent": intent})

    # Rerun to refresh the chat display
    st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# FOOTER
# ══════════════════════════════════════════════════════════════════════════════

st.markdown(
    """
    <div style='text-align:center;color:#374151;font-size:0.75rem;margin-top:32px;'>
        RAG-based FAQ · HDFC Mutual Funds · Data from Groww ·
        Facts only — no investment advice
    </div>
    """,
    unsafe_allow_html=True,
)
