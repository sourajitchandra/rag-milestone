# Evaluation Criteria
## Mutual Fund FAQ Assistant — Phase-Wise

> Evaluation framework for each phase of [implementation_plan.md](./implementation_plan.md).  
> Each phase has: **What to Evaluate**, **How to Test**, **Pass/Fail Criteria**, and **Metrics**.

---

## Phase 1 — Project Setup & Environment

### What to Evaluate
That the development environment is correctly configured, all dependencies install cleanly, and the directory structure is production-ready before any code is written.

### How to Test

| Test | Command | Expected Result |
|---|---|---|
| Dependencies install | `pip install -r requirements.txt` | No errors; all packages resolved |
| Core imports | `python -c "import faiss, bs4, sentence_transformers, groq"` | No `ImportError` |
| Virtual environment isolated | `pip list` inside venv | Only project packages listed |
| `.env` loaded | `python -c "from dotenv import load_dotenv; load_dotenv(); import os; print(os.getenv('GROQ_API_KEY'))"` | Returns non-empty string |
| Folder structure | `tree rag-milestone/` | All required directories present |
| `.gitignore` working | `git status` | `.env`, `data/raw/`, `vector_store/` shown as ignored |

### Pass Criteria
- [ ] All imports succeed with zero errors
- [ ] `GROQ_API_KEY` is accessible via `os.getenv()`
- [ ] All 5 directories (`docs/`, `data/raw/`, `data/processed/`, `vector_store/`, `src/`) exist
- [ ] `.env` is not tracked by git

### Fail Criteria
- Any `ImportError` or `ModuleNotFoundError`
- `GROQ_API_KEY` returns `None`
- Missing directories

### Metrics
| Metric | Target |
|---|---|
| Packages installed without conflict | 100% |
| Required directories present | 5 / 5 |
| `.env` excluded from git | ✅ |

---

## Phase 2 — Data Ingestion: Web Scraping

### What to Evaluate
That all 5 Groww scheme pages are successfully fetched, stored as non-empty HTML files, and timestamped accurately in `manifest.json`.

### How to Test

| Test | Method | Expected Result |
|---|---|---|
| All 5 HTML files created | `ls data/raw/*.html \| wc -l` | Returns `5` |
| Files are non-empty | `wc -c data/raw/*.html` | Each file > 10,000 bytes |
| Content has fund data | `grep -i "expense ratio" data/raw/hdfc_technology_fund.html` | Match found |
| Manifest has all entries | `python -c "import json; d=json.load(open('data/raw/manifest.json')); print(len(d))"` | Returns `5` |
| Manifest has timestamps | Check each entry has `scraped_at` key | ISO 8601 timestamp present |
| Retry on failure | Simulate network drop (disconnect mid-scrape) | Scraper retries 3× then logs failure |

### Pass Criteria
- [ ] All 5 HTML files exist and are > 10 KB
- [ ] Each file contains at least one of: `expense ratio`, `exit load`, `NAV`
- [ ] `manifest.json` has exactly 5 entries, each with a valid `scraped_at` timestamp
- [ ] HTTP errors are caught and logged, not raised as unhandled exceptions

### Fail Criteria
- Any HTML file is empty or missing
- `manifest.json` is absent or has < 5 entries
- Scraper crashes with an unhandled exception on a 404 or timeout

### Metrics
| Metric | Target |
|---|---|
| URLs successfully scraped | 5 / 5 |
| Average file size | > 10 KB per file |
| Manifest completeness | 5 / 5 entries with timestamps |
| Error handling | Retry ≤ 3×, then graceful log |

---

## Phase 3 — HTML Parsing & Text Extraction

### What to Evaluate
That the parser correctly extracts all 9+ structured fields from each scheme's HTML and saves them as valid JSON — with no silent failures on missing fields.

### How to Test

| Test | Method | Expected Result |
|---|---|---|
| All 5 fact files created | `ls data/processed/*_facts.json \| wc -l` | Returns `5` |
| Valid JSON | `python -m json.tool data/processed/hdfc_technology_fund_facts.json` | Parses without error |
| Core fields present | Check each JSON for required keys | All 9 fields exist |
| No null core fields | Assert `expense_ratio`, `exit_load`, `minimum_sip`, `riskometer` are non-null | Non-null for 5/5 funds |
| Missing field handled | Remove a CSS selector; re-run parser | Returns `null`, does not crash |
| Lock-in field for non-ELSS | Check `hdfc_liquid_fund_facts.json` lock-in value | Returns "N/A" or descriptive text, not null |
| Special characters | Print fund name and NAV fields | ₹ and % preserved correctly |

#### Required Fields Checklist Per Scheme
| Field | Key in JSON | Core? |
|---|---|---|
| Scheme name | `scheme_name` | ✅ |
| Category | `category` | ✅ |
| AMC | `amc` | ✅ |
| Expense ratio | `expense_ratio` | ✅ |
| Exit load | `exit_load` | ✅ |
| Minimum SIP | `minimum_sip` | ✅ |
| Minimum lump sum | `minimum_lumpsum` | ✅ |
| Lock-in period | `lock_in_period` | ✅ |
| Riskometer | `riskometer` | ✅ |
| Benchmark index | `benchmark_index` | ⬜ Optional |
| NAV | `nav` | ⬜ Optional |
| Fund manager(s) | `fund_managers` | ⬜ Optional |

### Pass Criteria
- [ ] All 5 `_facts.json` files are valid JSON
- [ ] All 9 core fields are present in every file
- [ ] Core fields are non-null for ≥ 4 / 5 schemes
- [ ] Parser does not raise an exception when a field is missing

### Fail Criteria
- Any `_facts.json` file is invalid JSON
- Core field `expense_ratio` or `minimum_sip` is null for all 5 schemes
- Parser crashes on missing field (unhandled `AttributeError`)

### Metrics
| Metric | Target |
|---|---|
| Core fields populated per scheme | ≥ 8 / 9 |
| Schemes with 0 null core fields | ≥ 4 / 5 |
| Parser crash rate | 0 unhandled exceptions |

---

## Phase 4 — Chunking & Embedding

### What to Evaluate
**4A (Chunker):** That field-level chunks are correctly created with all required metadata.  
**4B (Embedder):** That BGE embeddings are generated with the correct dimension and `normalize_embeddings=True`.

### How to Test

#### 4A — Chunker
| Test | Method | Expected Result |
|---|---|---|
| Chunk count in range | `python -c "import json; print(len(json.load(open('data/processed/chunks.json'))))"` | Between 45 and 90 |
| Each chunk has required metadata | Assert keys: `chunk_id`, `scheme_name`, `field`, `text`, `source_url`, `scraped_at` | All keys present |
| No empty chunk text | Filter `text == ""` | Zero empty chunks |
| Chunk text contains scheme name | Spot-check 5 random chunks | Each has scheme name embedded in text |
| Source URL is a Groww URL | Assert `source_url.startswith("https://groww.in")` | True for 100% of chunks |
| Each scheme contributes chunks | Count unique `scheme_name` values | Exactly 5 distinct schemes |

#### 4B — Embedder
| Test | Method | Expected Result |
|---|---|---|
| Embedding dimension | `print(vectors.shape)` | `(N, 768)` — BGE base dimension |
| Normalized vectors | `import numpy as np; print(np.linalg.norm(vectors[0]))` | ≈ 1.0 (L2 norm) |
| No zero vectors | `assert not any(np.all(v == 0) for v in vectors)` | Passes |
| BGE model loads | `SentenceTransformer('BAAI/bge-base-en-v1.5')` | Loads in < 30 seconds |
| Batch encoding works | Encode all chunks at once with `batch_size=16` | Completes without OOM error |

### Pass Criteria
- [ ] `chunks.json` has 45–90 entries
- [ ] Every chunk has all 6 required metadata fields
- [ ] No chunk has empty `text`
- [ ] All source URLs start with `https://groww.in`
- [ ] All embedding vectors have shape `(N, 768)` and L2 norm ≈ 1.0

### Fail Criteria
- `chunks.json` has < 40 chunks (indicates failed parsing upstream)
- Any chunk missing `source_url` or `scraped_at`
- Embedding dimension ≠ 768
- Any vector has L2 norm = 0 (zero vector)

### Metrics
| Metric | Target |
|---|---|
| Total chunks | 45–90 |
| Chunks with complete metadata | 100% |
| Embedding dimension | 768 (BGE base) |
| Vectors normalized (L2 norm ≈ 1.0) | 100% |

---

## Phase 5 — Vector Store: Build & Persist

### What to Evaluate
That the FAISS index is built correctly from the BGE embeddings, persisted to disk, and that nearest-neighbour search returns the right chunks for a known query.

### How to Test

| Test | Method | Expected Result |
|---|---|---|
| Index file exists | `os.path.exists('vector_store/faiss_index.bin')` | `True` |
| Index loads without error | `faiss.read_index('vector_store/faiss_index.bin')` | No exception |
| Index has correct vector count | `index.ntotal` | Equals total chunk count |
| Index dimension correct | `index.d` | `768` |
| Metadata file valid JSON | `python -m json.tool vector_store/metadata.json` | Parses without error |
| Known-query retrieval test | Embed `"expense ratio"`, search top-1 | Returns an expense_ratio chunk |
| Correct scheme retrieved | Query `"HDFC Liquid Fund expense ratio"` | Top chunk `scheme_name == "HDFC Liquid Fund"` |

#### Retrieval Sanity Tests
| Query Embedding Input | Expected Top-1 Field | Expected Scheme |
|---|---|---|
| `"expense ratio HDFC Technology Fund"` | `expense_ratio` | HDFC Technology Fund |
| `"exit load silver ETF"` | `exit_load` | HDFC Silver ETF FoF |
| `"minimum SIP defence fund"` | `minimum_sip` | HDFC Defence Fund |
| `"riskometer liquid fund"` | `riskometer` | HDFC Liquid Fund |
| `"benchmark index nifty500"` | `benchmark_index` | HDFC Nifty500 Multicap |

### Pass Criteria
- [ ] `faiss_index.bin` exists, loads, and has `ntotal == chunk_count`
- [ ] `metadata.json` is valid and has same count as index
- [ ] All 5 sanity retrieval tests return the correct scheme in top-1
- [ ] FAISS search completes in < 100 ms for any query

### Fail Criteria
- Index file missing or fails to load
- `index.ntotal` ≠ chunk count (incomplete indexing)
- Any sanity test returns wrong scheme in top-1

### Metrics
| Metric | Target |
|---|---|
| Retrieval accuracy on 5 sanity tests | 5 / 5 |
| FAISS search latency | < 100 ms |
| Index file size | < 5 MB (expected for ~90 chunks × 768d) |

---

## Phase 6 — Query Pipeline: Classifier & Retriever

### What to Evaluate
**Classifier:** Correctly labels queries as factual or advisory.  
**Retriever:** Returns top-3 semantically relevant chunks for factual queries.

### How to Test

#### 6A — Classifier Evaluation

| Query | Expected Intent | Pass If |
|---|---|---|
| "What is the expense ratio of HDFC Liquid Fund?" | `factual` | Returns `factual` |
| "Who manages HDFC Defence Fund?" | `factual` | Returns `factual` |
| "What is the minimum SIP?" | `factual` | Returns `factual` |
| "Should I invest in HDFC Technology Fund?" | `advisory` | Returns `advisory` |
| "Which HDFC fund is better?" | `advisory` | Returns `advisory` |
| "Is HDFC Defence Fund worth investing?" | `advisory` | Returns `advisory` |
| "Recommend me a mutual fund" | `advisory` | Returns `advisory` |
| "What is the riskometer of HDFC Silver ETF?" | `factual` | Returns `factual` |
| "Is this a good fund?" | `advisory` | Returns `advisory` |
| "What is the lock-in period?" | `factual` | Returns `factual` |

#### 6B — Retriever Evaluation

| Query | Expected Top Chunk Field | Expected Scheme |
|---|---|---|
| "What is the expense ratio of HDFC Technology Fund?" | `expense_ratio` | HDFC Technology Fund |
| "Exit load for silver ETF fund" | `exit_load` | HDFC Silver ETF FoF |
| "Minimum SIP for defence fund" | `minimum_sip` | HDFC Defence Fund |
| "Riskometer classification of HDFC Liquid Fund" | `riskometer` | HDFC Liquid Fund |
| "Benchmark index for HDFC Nifty500 Multicap" | `benchmark_index` | HDFC Nifty500 Multicap |

### Pass Criteria
- [ ] Classifier accuracy ≥ 9 / 10 on the test set above
- [ ] No advisory query is classified as `factual`
- [ ] Retriever top-1 chunk matches expected field for ≥ 4 / 5 retrieval tests
- [ ] Retrieved chunks always include `source_url` and `scraped_at` metadata

### Fail Criteria
- Classifier accuracy < 8 / 10
- Any advisory query classified as `factual` (false negative = compliance risk)
- Retriever returns chunks from wrong scheme for an explicitly named fund

### Metrics
| Metric | Target |
|---|---|
| Classifier accuracy | ≥ 90% (9/10) |
| Advisory false-negative rate | 0% |
| Retriever top-1 accuracy | ≥ 80% (4/5) |
| Retrieval latency | < 200 ms per query |

---

## Phase 7 — Prompt Builder & LLM Integration

### What to Evaluate
That the RAG prompt is assembled correctly and the Groq LLM returns grounded, factual responses that respect the constraint: ≤ 3 sentences, 1 citation, 1 footer.

### How to Test

#### 7A — Prompt Builder
| Test | Check | Expected |
|---|---|---|
| System prompt present | Assert `SYSTEM:` section in output | ✅ |
| Context injected | Assert `CONTEXT:` section has 3 chunks | ✅ |
| User question injected | Assert `USER QUESTION:` section has the query | ✅ |
| `scraped_at` accessible | Check formatter receives date from top chunk | Non-null date string |
| `source_url` accessible | Check formatter receives URL from top chunk | Groww URL string |

#### 7B — LLM Output Quality Tests
Run 5 factual queries end-to-end (scraper → parser → chunker → embedder → FAISS → retriever → prompt → Groq → raw response):

| Query | Grounded? | Has Facts? | No Advice? |
|---|---|---|---|
| "What is the expense ratio of HDFC Technology Fund?" | Must cite % from corpus | Yes | Yes |
| "What is the exit load for HDFC Silver ETF FoF?" | Must cite exit condition from corpus | Yes | Yes |
| "What is the minimum SIP for HDFC Defence Fund?" | Must cite ₹ amount from corpus | Yes | Yes |
| "Who manages HDFC Liquid Fund?" | Must cite fund manager name from corpus | Yes | Yes |
| "What is the riskometer of HDFC Nifty500 Multicap?" | Must cite riskometer label from corpus | Yes | Yes |

#### Groundedness Check (per response)
- Fact stated in response must appear verbatim or near-verbatim in one of the 3 retrieved chunks
- No number or name in response that is not in any retrieved chunk

### Pass Criteria
- [ ] All 5 factual queries return a non-empty response
- [ ] Groq API call succeeds with `temperature=0.0` and `max_tokens=200`
- [ ] All responses are grounded (fact can be traced back to a retrieved chunk)
- [ ] No response contains investment advice or recommendation

### Fail Criteria
- Groq API call fails (bad key, timeout)
- Any response contains a number or fund fact not present in the retrieved chunks (hallucination)
- Response is empty

### Metrics
| Metric | Target |
|---|---|
| Groq API success rate | 100% |
| Grounded responses | 5 / 5 |
| Responses with no advisory content | 5 / 5 |
| Average LLM latency (Groq) | < 2 seconds |

---

## Phase 8 — Response Formatter & Refusal Handler

### What to Evaluate
**Formatter:** Every factual response is ≤ 3 sentences, has exactly 1 Groww citation link, and has the `Last updated from sources:` footer.  
**Refusal Handler:** All advisory queries get a polite, template-based refusal — without any LLM call.

### How to Test

#### 8A — Response Formatter Tests
| Check | Method | Expected |
|---|---|---|
| Sentence count ≤ 3 | Split on `.!?`; count sentences | ≤ 3 sentences |
| Exactly 1 citation link | Count URLs matching `groww.in` in output | Exactly 1 |
| Footer present | Assert `"Last updated from sources:"` in response | ✅ |
| Footer has a date | Regex `\d{4}-\d{2}-\d{2}` after footer label | Date found |
| No hallucinated URL | Assert no URL other than the injected one | ✅ |
| Formatter bypassed for refusals | Pass refusal text through formatter | Response unchanged |

#### 8B — Refusal Handler Tests
| Query | LLM Called? | Refusal Returned? | Contains Advice? |
|---|---|---|---|
| "Should I invest in HDFC Technology Fund?" | No | Yes | No |
| "Which fund is best for me?" | No | Yes | No |
| "Is HDFC Defence Fund worth it?" | No | Yes | No |
| "Recommend the safest fund" | No | Yes | No |

#### Full Response Format Validation (5 factual queries)
```
Expected format:
<sentence 1>. <sentence 2>. <optional sentence 3>.
Source: https://groww.in/...

Last updated from sources: YYYY-MM-DD
```

| Field | Present | Correct |
|---|---|---|
| Answer (1–3 sentences) | ✅ | Must be factual |
| `Source:` Groww URL | ✅ | Must match chunk's `source_url` |
| `Last updated from sources:` footer | ✅ | Must have valid date |

### Pass Criteria
- [ ] 100% of factual responses have ≤ 3 sentences
- [ ] 100% of factual responses have exactly 1 citation link (a Groww URL)
- [ ] 100% of factual responses have the footer with a date
- [ ] 0% of refusal responses contain investment advice
- [ ] 0% of refusal responses trigger an LLM call

### Fail Criteria
- Any factual response > 3 sentences
- Any factual response with 0 or > 1 citation links
- Any factual response missing the footer
- Any refusal that calls Groq API

### Metrics
| Metric | Target |
|---|---|
| Responses ≤ 3 sentences | 100% |
| Responses with exactly 1 citation | 100% |
| Responses with footer | 100% |
| Refusals with no LLM call | 100% |
| Refusal response time | < 50 ms (template-only, no API) |

---

## Phase 9 — User Interface

### What to Evaluate
That the chat UI renders correctly, the disclaimer is always visible, the 3 example prompts work end-to-end, and the interface correctly handles both factual and advisory queries.

### How to Test

| Test | How | Expected |
|---|---|---|
| UI loads in browser | Navigate to `localhost:8501` (Streamlit) | Page loads without error |
| Welcome message visible | Check page heading | "Ask me anything factual about HDFC mutual fund schemes." |
| Disclaimer visible at load | Scan for disclaimer text | "Facts-only. No investment advice." visible |
| Disclaimer visible after scroll | Scroll to bottom of chat | Disclaimer still visible (sticky) |
| Example prompt 1 works | Click "What is the expense ratio of HDFC Technology Fund?" | Returns formatted factual response |
| Example prompt 2 works | Click "What is the exit load for HDFC Liquid Fund?" | Returns formatted factual response |
| Example prompt 3 works | Click "What is the minimum SIP for HDFC Defence Fund?" | Returns formatted factual response |
| Advisory query refused | Type "Should I invest?" and submit | Returns polite refusal, no facts |
| Empty submit blocked | Click submit with empty input | Button disabled or "Please enter a question." |
| Response includes source link | Click a source link in any response | Opens correct Groww page |
| Response includes footer | Check below each factual answer | "Last updated from sources: YYYY-MM-DD" visible |

### Pass Criteria
- [ ] UI loads without console errors
- [ ] Disclaimer is visible at all times (sticky positioning)
- [ ] All 3 example prompts return correct, formatted responses
- [ ] Advisory query returns refusal without crashing
- [ ] Empty submission is blocked at UI level
- [ ] Every response has a clickable Groww source link
- [ ] Every response has the `Last updated from sources:` footer

### Fail Criteria
- UI fails to load
- Disclaimer disappears when scrolled
- Any example prompt returns an error or empty response
- Submit button allows empty input

### Metrics
| Metric | Target |
|---|---|
| UI load time | < 3 seconds |
| Example prompts working | 3 / 3 |
| Disclaimer always visible | ✅ |
| End-to-end response time (UI → response) | < 5 seconds |

---

## Phase 10 — End-to-End Testing & Validation

### What to Evaluate
Complete system correctness across all 5 factual query types, all refusal scenarios, all edge cases from `edge-cases.md`, and constraint compliance.

### Factual Query Test Suite (15 queries)

| # | Query | Expected | Pass If |
|---|---|---|---|
| F-01 | "What is the expense ratio of HDFC Technology Fund?" | Returns correct % | Non-empty, cites Groww URL |
| F-02 | "What is the expense ratio of HDFC Silver ETF FoF?" | Returns correct % | Non-empty, cites Groww URL |
| F-03 | "What is the exit load for HDFC Defence Fund?" | Returns exit load terms | ≤ 3 sentences |
| F-04 | "What is the exit load for HDFC Liquid Fund?" | Returns exit load terms | ≤ 3 sentences |
| F-05 | "What is the minimum SIP for HDFC Nifty500 Multicap?" | Returns ₹ amount | Has 1 citation |
| F-06 | "What is the minimum SIP for HDFC Technology Fund?" | Returns ₹ amount | Has 1 citation |
| F-07 | "What is the riskometer of HDFC Silver ETF FoF?" | Returns risk label | Factual, no advice |
| F-08 | "What is the benchmark index of HDFC Defence Fund?" | Returns index name | Factual, no advice |
| F-09 | "Who manages HDFC Liquid Fund?" | Returns fund manager name | From corpus only |
| F-10 | "What is the NAV of HDFC Technology Fund?" | Returns ₹ value | Has footer date |
| F-11 | "What is the lock-in period for HDFC Silver ETF FoF?" | Returns "N/A" or equivalent | Accurate |
| F-12 | "What is the minimum lump sum for HDFC Defence Fund?" | Returns ₹ amount | From corpus |
| F-13 | "What is the category of HDFC Liquid Fund?" | "Liquid / Debt" | Accurate |
| F-14 | "What is the AMC for these schemes?" | HDFC Mutual Fund | From corpus |
| F-15 | "What is the expense ratio of HDFC Nifty500 Multicap?" | Returns correct % | Non-empty |

### Refusal Test Suite (8 queries)

| # | Query | Must Refuse | LLM Called? |
|---|---|---|---|
| R-01 | "Should I invest in HDFC Technology Fund?" | ✅ | No |
| R-02 | "Which HDFC fund is better for me?" | ✅ | No |
| R-03 | "Is HDFC Defence Fund a good investment?" | ✅ | No |
| R-04 | "Recommend a fund for me" | ✅ | No |
| R-05 | "Which fund gives the best returns?" | ✅ | No |
| R-06 | "Is it worth investing in silver ETF right now?" | ✅ | No |
| R-07 | "What is my best option among these funds?" | ✅ | No |
| R-08 | "Which fund should I pick for tax saving?" | ✅ | No |

### Constraint Compliance Checklist

| Constraint | Check Method | Target |
|---|---|---|
| Response ≤ 3 sentences | Count sentences in all factual responses | 100% |
| Exactly 1 citation per response | Count Groww URLs per response | 100% |
| Footer in every response | Assert `Last updated from sources:` | 100% |
| No investment advice in factual responses | Manual review + keyword scan | 0 violations |
| No PII stored or echoed | Test with PAN in query | PII redacted |
| No hallucinated facts | Cross-check response vs retrieved chunks | 0 hallucinations |
| Source URL always from corpus | Assert URL matches `groww.in/mutual-funds/hdfc-*` | 100% |

### Overall Pass Criteria
- [ ] ≥ 13 / 15 factual query tests pass (87% accuracy)
- [ ] 8 / 8 refusal tests pass (100%)
- [ ] 0 advisory queries misclassified as factual
- [ ] 0 hallucinated facts in any response
- [ ] 0 responses > 3 sentences
- [ ] 0 responses with missing citation or footer

### Metrics Dashboard (Phase 10 Gate)

| Metric | Target | Measured |
|---|---|---|
| Factual query pass rate | ≥ 87% (13/15) | ___ / 15 |
| Refusal pass rate | 100% (8/8) | ___ / 8 |
| Advisory false-negative rate | 0% | ___ |
| Responses ≤ 3 sentences | 100% | ___ % |
| Responses with 1 citation | 100% | ___ % |
| Responses with footer | 100% | ___ % |
| Hallucination count | 0 | ___ |
| Avg end-to-end latency | < 5 seconds | ___ s |

---

## Consolidated Phase Gate Summary

| Phase | Gate Condition | Blocker? |
|---|---|---|
| 1 | All imports succeed; `GROQ_API_KEY` loadable; folders exist | ✅ Yes |
| 2 | 5 HTML files saved, non-empty, timestamped | ✅ Yes |
| 3 | 5 fact JSONs with ≥ 8/9 core fields non-null | ✅ Yes |
| 4 | chunks.json: 45–90 entries; vectors dim=768; normalized | ✅ Yes |
| 5 | FAISS loads; 5/5 sanity retrievals pass | ✅ Yes |
| 6 | Classifier ≥ 90%; 0 advisory false-negatives; retriever ≥ 80% | ✅ Yes |
| 7 | Groq returns grounded responses; 0 hallucinations | ✅ Yes |
| 8 | 100% responses formatted; 0 refusals call LLM | ✅ Yes |
| 9 | UI loads; disclaimer sticky; 3/3 examples work | ✅ Yes |
| 10 | ≥ 87% factual pass; 100% refusals pass; 0 hallucinations | ✅ Yes |
