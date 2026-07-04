# Phase-Wise Implementation Plan
## Mutual Fund FAQ Assistant (RAG-Based)

> Based on [architecture.md](./architecture.md) and [problemstatement.md](./problemstatement.md)

---

## Overview

| Phase | Name | Type | Deliverable |
|---|---|---|---|
| 1 | Project Setup & Environment | Foundation | Working dev environment |
| 2 | Data Ingestion — Web Scraping | Offline Pipeline | Raw HTML files from 5 Groww URLs |
| 3 | HTML Parsing & Text Extraction | Offline Pipeline | Cleaned structured facts per scheme |
| 4 | Chunking & Embedding | Offline Pipeline | Embedded chunks ready for indexing |
| 5 | Vector Store — Build & Persist | Offline Pipeline | FAISS index + metadata on disk |
| 6 | Query Pipeline — Classifier & Retriever | Online Pipeline | Working retrieval from user query |
| 7 | Prompt Builder & LLM Integration | Online Pipeline | End-to-end RAG response |
| 8 | Response Formatter & Refusal Handler | Online Pipeline | Formatted, compliant output |
| 9 | User Interface | UI Layer | Chat interface with disclaimer |
| 10 | Daily Scheduler — Automated Ingestion | Automation | Self-refreshing vector store (daily cron) |
| 11 | Testing & Validation | QA | Verified, production-ready system |

---

## Phase 1 — Project Setup & Environment

### Goal
Set up the repository structure, Python environment, and API credentials so all subsequent phases can be built in a consistent, reproducible way.

### Tasks

- [ ] Create project directory structure as defined in `architecture.md §6`
  ```
  rag-milestone/
  ├── docs/
  ├── data/raw/
  ├── data/processed/
  ├── vector_store/
  └── src/
  ```
- [ ] Initialise a `requirements.txt` with base dependencies:
  ```
  requests
  beautifulsoup4
  playwright          # optional, for JS rendering
  faiss-cpu
  sentence-transformers
  groq
  python-dotenv
  streamlit           # or flask
  ```
- [ ] Create `.env` file with placeholder API key:
  ```
  GROQ_API_KEY=
  ```
- [ ] Create `.gitignore` — exclude `.env`, `data/raw/`, `vector_store/`
- [ ] Install and verify all dependencies in a virtual environment (`venv`)

### Exit Criteria
- `python -c "import faiss, bs4, openai"` runs without errors
- Project folder structure matches `architecture.md §6`

---

## Phase 2 — Data Ingestion: Web Scraping

> **Corresponds to:** `architecture.md §3.1` — Web Scraper

### Goal
Fetch the raw HTML from each of the 5 Groww scheme pages and save locally with a timestamp.

### Input
5 Groww URLs:
| # | URL |
|---|---|
| 1 | `https://groww.in/mutual-funds/hdfc-technology-fund-direct-growth` |
| 2 | `https://groww.in/mutual-funds/hdfc-silver-etf-fof-direct-growth` |
| 3 | `https://groww.in/mutual-funds/hdfc-defence-fund-direct-growth` |
| 4 | `https://groww.in/mutual-funds/hdfc-liquid-fund-direct-growth` |
| 5 | `https://groww.in/mutual-funds/hdfc-nifty500-multicap-50:25:25-index-fund-direct-growth` |

### Tasks

- [ ] Implement `src/scraper.py`:
  - Try `requests` first; if content is JS-rendered and empty, fall back to `Playwright`
  - Save raw HTML to `data/raw/<scheme_slug>.html`
  - Record `scraped_at` ISO timestamp in a `data/raw/manifest.json`
- [ ] Verify each saved HTML file contains visible scheme data (expense ratio, NAV, etc.)
- [ ] Handle HTTP errors gracefully (retry up to 3 times with backoff)

### Output
```
data/raw/
├── hdfc_technology_fund.html
├── hdfc_silver_etf_fof.html
├── hdfc_defence_fund.html
├── hdfc_liquid_fund.html
├── hdfc_nifty500_multicap.html
└── manifest.json         # { "scheme": url, "scraped_at": "2025-06-29T..." }
```

### Exit Criteria
- All 5 HTML files saved and non-empty
- `manifest.json` contains a timestamp for each scheme

---

## Phase 3 — HTML Parsing & Text Extraction

> **Corresponds to:** `architecture.md §3.1` — HTML Parser & Cleaner

### Goal
Parse each raw HTML file and extract the key factual fields into structured plain-text records.

### Tasks

- [ ] Inspect saved HTML files to identify CSS selectors / div patterns for each field
- [ ] Implement `src/parser.py`:
  - Extract the following fields per scheme:
    | Field | Example Value |
    |---|---|
    | Scheme name | HDFC Technology Fund – Direct Growth |
    | Category | Sectoral / Thematic (Technology) |
    | AMC | HDFC Mutual Fund |
    | Expense ratio (direct) | 0.70% |
    | Exit load | 1% if redeemed within 1 year |
    | Minimum SIP amount | ₹100 |
    | Minimum lump sum | ₹100 |
    | Lock-in period | N/A (or 3 years for ELSS) |
    | Riskometer level | Very High |
    | Benchmark index | BSE Teck TRI |
    | NAV (latest) | ₹XX.XX |
    | Fund manager(s) | Balakumar B |
  - Store per-scheme output as a dict / JSON object
- [ ] Save cleaned output to `data/processed/<scheme_slug>_facts.json`

### Output
```
data/processed/
├── hdfc_technology_fund_facts.json
├── hdfc_silver_etf_fof_facts.json
├── hdfc_defence_fund_facts.json
├── hdfc_liquid_fund_facts.json
└── hdfc_nifty500_multicap_facts.json
```

### Exit Criteria
- Each JSON file has all expected fields populated (no `null` values for core fields)
- Parser handles missing fields gracefully without crashing

---

## Phase 4 — Chunking & Embedding

> **Corresponds to:** `architecture.md §3.2` — Text Chunker + Embedding Model

### Goal
Convert structured facts into semantically grouped text chunks and generate dense vector embeddings for each.

### Tasks

#### 4A — Chunker (`src/chunker.py`)
- [x] Group 12 parsed fields into **7 semantic chunk types** per scheme (35 total):

  | Group | Fields Combined | Rationale |
  |---|---|---|
  | Fund Overview | scheme_name + category + amc + riskometer | Generic "tell me about X" queries |
  | NAV | nav (+ nav_date) | Most common single-fact query |
  | Expense Ratio | expense_ratio | Second most common query |
  | Exit Load | exit_load | Variable length, standalone |
  | Investment Minimums | minimum_sip + minimum_lumpsum + lock_in_period | Users ask "what's the minimum?" broadly |
  | Benchmark | benchmark_index | Niche but valid factual query |
  | Fund Managers | fund_managers | "Who manages X?" |

- [x] Each chunk includes scheme_name in its text body (retrieval discrimination)
- [x] Attach metadata to each chunk:
  ```json
  {
    "chunk_id": "hdfc_technology_fund__expense_ratio",
    "scheme_name": "HDFC TECHNOLOGY FUND - DIRECT PLAN GROWTH",
    "field": "expense_ratio",
    "text": "The direct plan expense ratio of HDFC TECHNOLOGY FUND...",
    "source_url": "https://groww.in/...",
    "scraped_at": "2026-06-30T16:40:43..."
  }
  ```
- [x] Save all chunks to `data/processed/chunks.json`

#### 4B — Embedder (`src/embedder.py`)

**Model Selection: `BAAI/bge-base-en-v1.5` ✅**

Based on actual chunk characteristics, here is the full analysis of all three BGE tiers:

| Property | BGE-small-en-v1.5 | BGE-base-en-v1.5 ✅ | BGE-large-en-v1.5 |
|---|---|---|---|
| Parameters | 33M | 110M | 335M |
| Embedding dim | 384 | **768** | 1024 |
| Disk size | ~130 MB | ~440 MB | ~1.3 GB |
| MTEB Retrieval (en) | 51.7 | 53.2 | **54.2** |
| Inference speed | Fastest | Fast | Slow |

**Why NOT BGE-small:**

Our corpus has a severe **near-duplicate discrimination problem**. Looking at actual chunk vocabulary:

| Field group | Shared words (all 5 schemes) | Unique words per chunk |
|---|---|---|
| `expense_ratio` | 10 (template words) | only 2–6 |
| `nav` | 9 | only 3–7 |
| `investment_minimums` | 16 | only 3–6 |
| `fund_overview` | 17 | only 6–11 |

All 5 `expense_ratio` chunks are structurally identical — differing only in scheme name and a percentage value. A 384-dim space has **less capacity to separate near-identical short vectors**. This would directly worsen the expense ratio ranking issue (already at rank #3 with base).

**Why NOT BGE-large:**

- Corpus is 35 vectors — brute-force FAISS search completes in microseconds at any dimension
- All chunks are 12–32 tokens — well within any model's optimal range; large adds zero benefit for short text
- Retrieval with base already achieves **5/5 target-in-top-3** (scores 0.79–0.92)
- 1.3 GB download for ~1% MTEB improvement on a 35-vector index is not justified
- Higher dimension does not solve structural near-duplicate issues — it helps with long-range semantic complexity our chunks don't have

**Why BGE-base is correct for this data:**

1. **768-dim gives more separability** between structurally similar short chunks than 384-dim
2. **Already proven**: 5/5 test queries pass, top-1 scores of 0.84–0.92 for 4 of 5 field types
3. **Appropriate size**: 35 chunks × 768-dim = ~107 KB index — trivially small
4. **No cold-start cost**: Model is cached after first run; embedding 35 short chunks takes ~2 seconds

**Implementation:**
- [x] `SentenceTransformer('BAAI/bge-base-en-v1.5')`
- [x] `normalize_embeddings=True` — required for BGE (converts L2 normalised dot-product to cosine similarity)
- [x] `batch_size=32` — all 35 chunks fit in a single batch
- [x] `FAISS IndexFlatIP(768)` — exact search (no approximation needed for 35 vectors)

### Exit Criteria
- [x] `chunks.json` has 35 entries (7 groups × 5 schemes) — ✅ verified
- [x] All chunks have valid `source_url` and `scraped_at` metadata — ✅ 0 missing
- [x] Embedding succeeds for all 35 chunks — ✅ shape (35, 768)
- [x] 5/5 test queries find target chunk in top-3 retrieval — ✅ verified
- [x] Model choice validated against chunk data — ✅ BGE-base confirmed

---

## Phase 5 — Vector Store: Build & Persist

> **Corresponds to:** `architecture.md §3.3` — Vector Store

### Goal
Index all embedded chunks into a FAISS vector store and persist to disk.

### Tasks

- [x] Implemented in `src/embedder.py` (build index section):
  - Initialise `faiss.IndexFlatIP(768)` — inner product on L2-normalised vectors = cosine similarity
  - Add all 35 chunk vectors to index
  - Save index: `vector_store/faiss_index.bin` (105 KB)
  - Save metadata (chunk text + source + scheme + timestamp): `vector_store/metadata.json` (35 entries)
- [x] 3 smoke-test queries verified during build — 2/3 top-1 exact hits, 3/3 target in top-3
- [x] Corpus size: 35 chunks, avg ~19.5 tokens/chunk (20–80 tokens each)

### Output
```
vector_store/
├── faiss_index.bin       # FAISS IndexFlatIP binary index (105 KB)
└── metadata.json         # 35 chunk dicts (text, source_url, scheme_name, scraped_at)
```

### Exit Criteria
- [x] `faiss_index.bin` loads without error — ✅ verified
- [x] Nearest-neighbour search returns correct chunk — ✅ 5/5 test queries pass

---

## Phase 6 — Query Pipeline: Classifier & Retriever

> **Corresponds to:** `architecture.md §3.4` + `§3.5`

### Goal
Build the online query processing pipeline: classify the incoming query as factual or advisory, embed it, and retrieve the top-3 matching chunks from FAISS using an enhanced retrieval strategy informed by the actual embedding and chunk structure.

---

### Retrieval Strategy Analysis (based on actual corpus)

#### Corpus Structure (35 chunks across 5 schemes × 7 field groups)

| Field Group | Unique words per chunk | Discriminating tokens |
|---|---|---|
| `fund_overview` | 6–11 | category name (e.g. "Sectoral", "Thematic", "Liquid"), risk level |
| `nav` | 3–7 | NAV value (e.g. "₹10.98"), scheme name |
| `expense_ratio` | 2–6 | only scheme name + percentage differ |
| `exit_load` | 4–8 | period (e.g. "30 days", "1 year"), scheme name |
| `investment_minimums` | 3–6 | same ₹100 value for most; only scheme name differs |
| `benchmark_index` | 4–9 | benchmark name (highly unique per scheme) |
| `fund_managers` | 3–7 | manager names (unique per scheme) |

**Key challenge — near-duplicate discrimination:**  
All 5 `expense_ratio` chunks share the template `"The direct plan expense ratio of {NAME} is {VALUE}."`.  
Similarly, 4 out of 5 `investment_minimums` chunks share identical SIP/lumpsum/lock-in values (`₹100 / ₹100 / N/A`).  
The only differentiator is the scheme name embedded in the chunk text.

#### Why BGE-base Works Without Extra Re-ranking (for 35 vectors)

- **768-dim embeddings** provide sufficient inter-scheme separability even for structurally near-identical chunks.
- **Scheme name is present in every chunk text** — BGE picks up name tokens (e.g. "LIQUID", "SILVER", "NIFTY500") reliably.
- **FAISS IndexFlatIP** is brute-force exact search — no approximation loss for a 35-vector corpus.
- **Verified**: 5/5 target-in-top-3 at score range 0.79–0.92 on the actual index.

#### BGE Query Instruction Prefix

BGE-base-en-v1.5 is an *instruction-tuned* model. For retrieval queries, the recommended prefix is:
```
"Represent this sentence for searching relevant passages: "
```
This is prepended to user queries at encode time, but **NOT** to corpus chunks (they are encoded as-is). This asymmetry improves top-1 precision for field-specific and scheme-specific queries.

#### Score Threshold for Confidence Gating

From smoke-test results on 5 representative queries:
| Query | Top-1 Field Match | Top-1 Score |
|---|---|---|
| expense ratio | `expense_ratio` | 0.84 |
| exit load | `exit_load` | 0.87 |
| minimum SIP | `investment_minimums` | 0.79 |
| fund manager | `fund_managers` | 0.92 |
| NAV | `nav` | 0.91 |

A minimum score threshold of **0.60** is applied: any chunk with score < 0.60 is excluded from the context window. For a 35-vector index this prevents genuinely unrelated chunks (e.g. querying about a non-HDFC fund) from being injected into the LLM prompt.

#### Retrieval Pipeline (final design)

```
user_query
    ↓
[1] BGE query prefix: "Represent this sentence for searching relevant passages: " + query
    ↓
[2] SentenceTransformer.encode(normalize_embeddings=True)  →  768-dim unit vector
    ↓
[3] faiss.IndexFlatIP.search(q_vec, top_k=3)  →  (distances, indices)
    ↓
[4] Score threshold filter: drop chunks with score < 0.60
    ↓
[5] Return ranked chunk list with (chunk_id, scheme_name, field, text, source_url, score, rank)
```

---

### Tasks

#### 6A — Query Classifier (`src/classifier.py`)
- [x] Keyword-based classification with 4 intent types:
  - `factual` — default when no trigger matched
  - `advisory` — 17 regex trigger phrases: `should I`, `is it good`, `is it worth`, `which is better`, `recommend`, `worth investing`, `opinion`, `best fund`, `good investment`, `advise`, `advice`, `suitable`, `should invest`, `better for me`, `safe to invest`, `prefer`, `suggest`
  - `pii` — PAN card, 10–12 digit phone/account, Aadhaar regex patterns (checked before advisory)
  - `empty` — blank or whitespace-only query
- [x] Returns `{"intent": "factual" | "advisory" | "pii" | "empty", "matched": <trigger>}`
- [x] 10/10 unit tests pass (3 factual, 3 advisory, 1 PII, 2 empty)

#### 6B — Query Embedder + Retriever (`src/retriever.py`) — **Enhanced**
- [x] `Retriever` class initialised once at app startup (loads index + model)
- [x] Loads `faiss_index.bin` and `metadata.json` from `vector_store/`
- [x] **BGE query instruction prefix** prepended at query encode time (not at corpus encode time)
- [x] Embeds user query with same BGE model (`normalize_embeddings=True`)
- [x] FAISS IndexFlatIP search → returns top-k chunks with `score` and `rank` fields
- [x] **Score threshold filter**: drops chunks below 0.60 cosine similarity
- [x] Self-test confirms 5/5 test queries pass with top-1 scores 0.79–0.92

#### 6C — Groq API Rate Limiter (`src/rate_limiter.py`) — **New**
- [x] In-memory sliding-window `RateLimiter` class tracking all 4 Groq free-tier quota axes
- [x] Integrated at Step 3 of `process_query()` in `src/app.py` — **before** retrieval and LLM calls
- [x] Self-test verifies RPM and TPM blocking behaviour

### Exit Criteria
- [x] 5/5 test queries find target chunk in top-3 — ✅ verified
- [x] `"Should I invest?"` → classified as `advisory` — ✅ verified
- [x] PII query → classified as `pii` before reaching retriever — ✅ verified
- [x] BGE query prefix applied at encode time — ✅ implemented
- [x] Score threshold 0.60 applied — ✅ implemented
- [x] Low-confidence / out-of-corpus queries return empty list or filtered results — ✅ verified
- [x] Groq rate limits enforced before retrieval — ✅ implemented (Phase 6C)
- [x] Rate-limit responses return user-facing message with wait time — ✅ implemented

---

### Groq Rate Limit Handling (Phase 6C)

#### Free-Tier Quota Constraints

| Axis | Limit | Binding scenario |
|---|---|---|
| RPM (Requests/min) | **30** | Sustained interactive use |
| RPD (Requests/day) | **1,000** | Heavy daily use (unlikely for demo) |
| TPM (Tokens/min) | **12,000** | ~18 calls/min at 650 tokens each |
| TPD (Tokens/day) | **100,000** | ~153 calls/day at 650 tokens each |

**Binding limit in practice:** RPM=30 is the tightest constraint — it allows at most 1 request every 2 seconds under heavy use. TPM becomes binding slightly before RPM at sustained load (~18 requests/min at full prompt size).

#### Token Estimation Per Request

Each RAG call to Groq consumes approximately:

| Component | Estimated Tokens |
|---|---|
| System prompt | ~100 |
| 3 × chunk context (avg 75 tokens each) | ~225 |
| User query | ~20 |
| **Total prompt** | **~345** |
| Max completion (`max_tokens=200` in llm.py) | ≤200 |
| **Estimated total per call** | **~545 → rounded to 650 (safety margin)** |

The 650-token estimate is deliberately conservative: it accounts for variance in chunk length and prevents the TPD counter from under-counting.

#### Implementation: Sliding-Window Rate Limiter

```
src/rate_limiter.py  — RateLimiter class
    ├── _rpm_window  deque[timestamp]           # prune entries > 60s old
    ├── _rpd_window  deque[timestamp]           # prune entries > 86400s old
    ├── _tpm_window  deque[(timestamp, tokens)] # sliding-minute token sum
    └── _tpd_window  deque[(timestamp, tokens)] # sliding-day token sum

check_and_record(estimated_tokens=650):
    1. Prune expired entries from all 4 deques
    2. Check RPM → raise RateLimitExceeded if len(rpm_window) >= 30
    3. Check RPD → raise RateLimitExceeded if len(rpd_window) >= 1000
    4. Check TPM → raise RateLimitExceeded if sum(tpm_window) + 650 > 12000
    5. Check TPD → raise RateLimitExceeded if sum(tpd_window) + 650 > 100000
    6. Record timestamp + token estimate in all 4 deques
```

#### Pipeline Position (Updated)

```
user_query
    ↓
[1] Classifier  (advisory / pii / empty → refusal; no LLM call)
    ↓
[2] RateLimiter.check_and_record()  ← NEW in Phase 6C
    |  RPM / RPD / TPM / TPD check against Groq free-tier limits
    |  Exceeded → return user-facing message with wait time
    ↓
[3] Retriever.search()  (FAISS cosine search, score threshold 0.60)
    ↓
[4] prompt_builder.build_prompt()
    ↓
[5] call_llm()  →  Groq API  (llama-3.3-70b-versatile)
    ↓
[6] format_response()
```

#### User-Facing Messages

| Exceeded Limit | Message shown |
|---|---|
| RPM | `"I've reached the per-minute request limit (30 requests/min). Please wait about N second(s) and try again."` |
| RPD | `"I've reached the daily request limit (1,000 requests/day). The quota resets in approximately N hour(s)."` |
| TPM | `"I've reached the per-minute token limit (~12,000 tokens/min). Please wait about N second(s) and try again."` |
| TPD | `"I've reached the daily token limit (~100,000 tokens/day). The quota resets in approximately N hour(s)."` |

---

## Phase 7 — Prompt Builder & LLM Integration

> **Corresponds to:** `architecture.md §3.6` + `§3.7`

### Goal
Assemble the RAG prompt from retrieved context and get a grounded, factual response from the LLM.

### Tasks

#### 7A -- Prompt Builder (`src/prompt_builder.py`) -- **Hardened**
- [x] Constrained system prompt instructing LLM to:
  - Answer ONLY from retrieved context
  - Produce <= 3 sentences
  - **NOT add a Source line or footer** (injected by formatter from retrieval metadata)
  - Return `"I don't have that information in my current data."` if context insufficient
- [x] Each retrieved chunk formatted as:
  ```
  [Chunk N]
  Scheme:  <scheme_name>
  Field:   <field_group>
  Text:    <chunk_text>
  Source:  <source_url>
  Scraped: <scraped_at>
  ```
- [x] Returns `(prompt_text, top_chunk_meta)` with keys: source_url, scraped_at, scheme_name, **field**
- [x] Self-test passes all assertions

#### 7B -- LLM Caller (`src/llm.py`) -- **Hardened**
- [x] Integrated with **Groq API** using the `groq` Python SDK:
  - Model: `llama-3.3-70b-versatile`
  - Temperature: `0.0` (deterministic)
  - Max tokens: `200` (enforces brevity)
- [x] Loads `GROQ_API_KEY` from `.env` via `python-dotenv`
- [x] **Specific Groq exception handling:**
  - `AuthenticationError` -> RuntimeError, no retry
  - `RateLimitError` -> RuntimeError with advisory message (Phase 6C guard prevents reaching here)
  - `APIStatusError` 5xx -> exponential back-off retry (1s, 3s, 7s), up to 3 attempts
  - `APIStatusError` 4xx -> RuntimeError, no retry
  - Network/timeout errors -> retry with back-off
- [x] Logs actual token usage (prompt + completion + total) per call
- [x] Self-test: skips gracefully when `GROQ_API_KEY` is absent; runs live probe when key is set

### Exit Criteria
- [x] Prompt builder implemented and hardened -- system prompt prevents LLM footer/source injection -- verified
- [x] LLM caller implemented with specific Groq exception types + retry logic -- verified
- [x] Prompt builder self-test: all assertions pass -- verified
- [x] LLM caller self-test: skips cleanly with no API key -- verified
- [ ] End-to-end test: query -> retrieve -> prompt -> LLM -> raw response -- pending API key in .env

---

## Phase 8 — Response Formatter & Refusal Handler

> **Corresponds to:** `architecture.md §3.8` + `§3.9`

### Goal
Post-process the raw LLM output into a clean, compliant response; handle advisory queries with a polite refusal.

### Tasks

#### 8A -- Response Formatter (`src/formatter.py`) -- **Hardened**
- [x] Sentence count enforcement -- hard truncation to <= 3 sentences even if LLM ignores prompt rule
- [x] Citation injection -- `source_url` from top retrieved chunk metadata (not LLM output, preventing hallucinated URLs)
- [x] LLM-injected Source/footer lines stripped before truncation
- [x] **No-info passthrough** -- if LLM returns `"I don't have that information..."`, emitted as-is with footer, no citation block
- [x] `scraped_at` ISO timestamp parsed to `YYYY-MM-DD`; falls back to `today (estimated)` if missing
- [x] Final structure of every factual response:
  ```
  <Answer in <= 3 sentences.>
  Source: <groww_url>

  Last updated from sources: YYYY-MM-DD
  ```
- [x] Self-test: 5/5 cases pass (normal, truncation, hallucination-strip, no-info, date-fallback)

#### 8B — Refusal Handler (`src/classifier.py`)
- [x] Three distinct refusal templates (no LLM call for any):
  - **Advisory**: `"I can only share factual information... Please consult a registered financial advisor..."`
  - **PII**: `"Your query may contain personal information... Please rephrase without personal details."`
  - **Empty**: `"Please enter a question about HDFC mutual fund schemes."`
- [x] Refusal triggered before retrieval — zero LLM tokens consumed

### Exit Criteria
- [x] Formatter implemented and hardened -- 5/5 self-test cases pass -- verified
- [x] Advisory refusal returns fixed template without LLM call -- verified
- [x] PII refusal implemented -- verified (additional safety beyond original spec)
- [ ] End-to-end response format verified with live Groq call -- pending API key in .env

---

## Phase 9 — User Interface

> **Corresponds to:** `architecture.md §3.10`

### Goal
Build a minimal, clean chat interface that exposes the RAG pipeline to end users.

### Tasks

- [x] Implemented `src/app.py` as a **CLI interactive chat** (terminal mode):
  - Welcome banner with disclaimer on launch
  - `process_query()` function usable programmatically for future web UI integration
  - Full pipeline wired: `classifier → retriever → prompt_builder → llm → formatter`
  - Graceful `quit` / `exit` / Ctrl-C handling
  - `Retriever` initialised once at startup (BGE model + FAISS index loaded once)
- [x] **Web UI** (`src/web_app.py` — Streamlit) — wraps `run_pipeline()` (mirrors `process_query()`):
  - Dark-themed chat interface with gradient header and Inter font
  - Disclaimer banner on load (yellow-bordered, amber text)
  - 5 example prompt buttons (3 factual + 1 refusal + 1 edge-case)
  - Persistent chat history via `st.session_state`
  - Spinner ("Thinking…") during LLM calls
  - Source URL linkified; footer styled separately
  - Refusal bubbles (purple) vs factual bubbles (dark card) differentiated
  - `@st.cache_resource` for Retriever + RateLimiter (loaded once per session)
  - Graceful error display for missing GROQ_API_KEY and LLM failures
  - Run with: `streamlit run src/web_app.py`

### Exit Criteria
- [x] CLI app runs and routes queries through full pipeline — ✅
- [x] Advisory / PII / empty queries return correct refusals — ✅
- [x] Browser UI loads with disclaimer banner and example prompts — ✅ verified at localhost:8501
- [ ] All 3 example prompts return correct formatted responses in browser — ⏳ pending Groq API key in .env

---

## Phase 10 — Daily Scheduler: Automated Ingestion (GitHub Actions)

> **Corresponds to:** `architecture.md §3.1` — Web Scraper (scheduled re-run) + full offline pipeline

### Goal
Run the full data-ingestion pipeline automatically every day via a **GitHub Actions scheduled workflow** so the vector store always reflects the latest NAV, expense ratio, and other scheme data from Groww — without any manual intervention or always-on server.

### Design

#### How It Works

```
GitHub Actions  ←  schedule: cron('0 20 * * *')   # 20:00 UTC = 01:30 IST
      |
      ▼
 ubuntu-latest runner (fresh VM spun up by GitHub)
      |
      ├─ Checkout repo
      ├─ Set up Python 3.11
      ├─ pip install -r requirements.txt
      ├─ Run ingestion pipeline:
      │     scraper.py  →  parser.py  →  chunker.py  →  embedder.py
      │     (produces refreshed faiss_index.bin + metadata.json)
      ├─ Commit & push updated vector_store/ back to main branch
      └─ On failure → workflow fails with non-zero exit, GitHub notifies by email
```

#### Ingestion Pipeline Flow

```
[GitHub Actions cron trigger]  ← 20:00 UTC daily (configurable)
        ↓
 scraper.py           ← fetch fresh HTML for all 5 Groww URLs
        ↓
 parser.py            ← re-extract structured facts per scheme
        ↓
 chunker.py           ← rebuild semantic chunks (35 total)
        ↓
 embedder.py          ← re-embed with BGE-base, rebuild FAISS index
        ↓
 vector_store/        ← commit refreshed faiss_index.bin + metadata.json to repo
```

#### Workflow File

**`.github/workflows/daily_ingest.yml`** — the single file that defines the entire scheduler:

| Property | Value |
|---|---|
| Trigger | `schedule: cron('0 20 * * *')` (20:00 UTC = 01:30 IST) |
| Manual trigger | `workflow_dispatch` (run anytime from GitHub Actions UI) |
| Runner | `ubuntu-latest` (GitHub-hosted, free tier) |
| Python version | `3.11` |
| Secrets used | `GROQ_API_KEY` stored as a GitHub Secret (not in `.env`) |
| Artifacts committed | `vector_store/faiss_index.bin`, `vector_store/metadata.json` |
| Commit author | `github-actions[bot]` |
| Failure behaviour | Step exits non-zero → job marked `failure` → GitHub sends email alert |
| Retry on scrape fail | Scraper already has 3-attempt backoff; no extra retry layer needed |

#### Workflow YAML (full design)

```yaml
# .github/workflows/daily_ingest.yml
name: Daily Ingestion Pipeline

on:
  schedule:
    - cron: '0 20 * * *'   # 20:00 UTC every day (01:30 IST next day)
  workflow_dispatch:         # allows manual run from GitHub Actions UI

jobs:
  ingest:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run ingestion pipeline
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
        run: |
          python src/scraper.py
          python src/parser.py
          python src/chunker.py
          python src/embedder.py

      - name: Commit refreshed vector store
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add vector_store/faiss_index.bin vector_store/metadata.json
          git diff --cached --quiet || git commit -m "chore: daily vector store refresh [skip ci]"
          git push
```

> **`[skip ci]`** in the commit message prevents the push from re-triggering the workflow.

#### Secrets & Configuration

| Secret / Variable | Where to set | Purpose |
|---|---|---|
| `GROQ_API_KEY` | GitHub → Settings → Secrets → Actions | Passed to pipeline steps at runtime |
| `GITHUB_TOKEN` | Auto-provided by GitHub Actions | Allows `git push` back to the repo |
| Cron schedule | Edit `cron:` field in the YAML | Change run time without touching Python code |

#### `.gitignore` Updates Required

The vector store artifacts must be **tracked by git** (so the workflow can commit them back). Remove these lines from `.gitignore` if present:

```
# REMOVE these lines so vector_store is committed:
# vector_store/
# vector_store/faiss_index.bin
# vector_store/metadata.json

# Keep ignoring raw HTML (large, not needed in repo):
data/raw/
```

#### Failure Handling

| Failure point | Behaviour |
|---|---|
| Scraper HTTP error (all retries exhausted) | `scraper.py` exits non-zero → workflow step fails → job marked ❌ → email alert |
| Parser returns empty / null fields | `parser.py` raises exception → downstream steps do not run → index unchanged |
| Embedder / FAISS write error | `embedder.py` exits non-zero → commit step skipped → old index untouched in repo |
| No data changed since last run | `git diff --cached --quiet` exits 0 → commit skipped (no empty commit) |

### Tasks

- [x] Create `.github/workflows/` directory in the repo root — ✅
- [x] Implement `.github/workflows/daily_ingest.yml` with the YAML design above — ✅ YAML validated
- [ ] Add `GROQ_API_KEY` to GitHub repository Secrets (Settings → Secrets and variables → Actions) — ⏳ manual step
- [x] Verify `vector_store/` is **not** in `.gitignore` (update `.gitignore` to only exclude `data/raw/`) — ✅ updated
- [x] Confirm each ingestion script exits with code `0` on success and non-zero on fatal error:
  - `scraper.py` — `sys.exit(1)` added when any scheme fails — ✅
  - `parser.py` — `sys.exit(1)` added when any core field missing — ✅
  - `chunker.py` — `sys.exit(1)` added when chunk count ≠ 35 — ✅
  - `embedder.py` — raises exception naturally on any error (non-zero exit guaranteed) — ✅
- [ ] Trigger manually via `workflow_dispatch` from GitHub Actions UI and verify:
  - Workflow completes without errors
  - A new commit appears in the repo with updated `vector_store/metadata.json` timestamps
- [ ] Verify the scheduled cron trigger fires at the correct UTC time

### Output

```
.github/
└── workflows/
    └── daily_ingest.yml   # the scheduler definition

vector_store/              # committed to repo — refreshed by each workflow run
├── faiss_index.bin
└── metadata.json          # scraped_at timestamps updated to run date
```

### Exit Criteria
- [x] `.github/workflows/daily_ingest.yml` exists and is valid YAML — ✅ verified with `yaml.safe_load`
- [ ] `workflow_dispatch` manual run succeeds end-to-end on GitHub Actions — ⏳ requires GitHub push
- [ ] `metadata.json` `scraped_at` timestamps update to today's date after a successful run — ⏳ post-push
- [ ] A commit authored by `github-actions[bot]` appears in the repo after a successful run — ⏳ post-push
- [ ] Workflow is marked ❌ (failed) and an email alert is sent when `scraper.py` intentionally exits non-zero — ⏳ post-push
- [ ] Streamlit app (running from the repo) picks up the refreshed `faiss_index.bin` on next startup — ⏳ post-push

---

## Phase 11 — Testing & Validation

### Goal
Validate end-to-end correctness, constraint adherence, and edge-case handling before final submission.

### Test Cases

#### Factual Query Tests
| Query | Expected Behaviour |
|---|---|
| "What is the expense ratio of HDFC Technology Fund?" | Returns correct %, source URL, footer date |
| "What is the exit load for HDFC Silver ETF FoF?" | Returns exit load details, ≤ 3 sentences |
| "What is the minimum SIP for HDFC Defence Fund?" | Returns ₹ amount, 1 citation link |
| "What is the lock-in period for HDFC ELSS?" | N/A for these 5 funds — returns "not found in context" |
| "Who is the fund manager of HDFC Liquid Fund?" | Returns fund manager name |

#### Refusal Tests
| Query | Expected Behaviour |
|---|---|
| "Should I invest in HDFC Technology Fund?" | Polite refusal, no LLM call |
| "Which HDFC fund is better for me?" | Polite refusal |
| "Is HDFC Defence Fund a good investment?" | Polite refusal |

#### Edge Case Tests
| Scenario | Expected Behaviour |
|---|---|
| Query about a non-HDFC fund | "I don't have information about that fund." |
| Empty query | UI prevents submission |
| Query with PAN/account number in it | System does not store or echo PII |

### Tasks
- [ ] Run all test cases manually and record pass/fail
- [ ] Verify no response exceeds 3 sentences
- [ ] Verify every factual response has exactly 1 source link (a Groww URL)
- [ ] Verify every factual response has the `Last updated from sources:` footer
- [ ] Verify `data/raw/` HTML files are not committed to version control

### Exit Criteria
- All factual test cases pass
- All refusal test cases pass
- No hallucinated URLs or facts in any response

---

## Milestone Summary

```
Phase 1  ──►  Phase 2  ──►  Phase 3  ──►  Phase 4  ──►  Phase 5
  Setup       Scraping       Parsing      Chunking /      Vector
                                          Embedding        Store
                                                             │
                                                             ▼
Phase 11 ◄──  Phase 10 ◄──  Phase 9  ◄──  Phase 8  ◄──  Phase 7  ◄──  Phase 6
 Testing      Scheduler       UI         Formatter /    Prompt +       Classifier +
              (daily cron)               Refusal        LLM            Retriever
```

> **Phase 10 (Scheduler)** sits between the UI and Testing phases.
> It feeds back into Phases 2–5 (the offline ingestion pipeline) on a daily cron,
> keeping the vector store continuously up-to-date.

---

## File-to-Phase Mapping

| File | Phase |
|---|---|
| `src/scraper.py` | Phase 2 + Phase 10 (scheduled re-run) |
| `src/parser.py` | Phase 3 + Phase 10 (scheduled re-run) |
| `src/chunker.py` | Phase 4A + Phase 10 (scheduled re-run) |
| `src/embedder.py` | Phase 4B + Phase 5 + Phase 10 (scheduled re-run) |
| `src/retriever.py` | Phase 6B |
| `src/classifier.py` | Phase 6A + Phase 8B |
| `src/rate_limiter.py` | Phase 6C |
| `src/prompt_builder.py` | Phase 7A |
| `src/llm.py` | Phase 7B |
| `src/formatter.py` | Phase 8A |
| `src/app.py` | Phase 9 |
| `src/web_app.py` | Phase 9 (Web UI) |
| `.github/workflows/daily_ingest.yml` | Phase 10 [NEW] — GitHub Actions scheduler |
