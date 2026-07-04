# Mutual Fund FAQ Assistant (RAG-Based)

A facts-only FAQ assistant for 5 HDFC mutual fund schemes, built with a RAG pipeline using BGE embeddings, FAISS vector store, and Groq LLM.

---

## Selected Schemes

| # | Scheme | Category |
|---|---|---|
| 1 | HDFC Technology Fund – Direct Growth | Sectoral / Thematic (Technology) |
| 2 | HDFC Silver ETF FoF – Direct Growth | Fund of Funds (Commodity / Silver) |
| 3 | HDFC Defence Fund – Direct Growth | Sectoral / Thematic (Defence) |
| 4 | HDFC Liquid Fund – Direct Growth | Liquid / Debt |
| 5 | HDFC Nifty500 Multicap 50:25:25 Index Fund – Direct Growth | Index / Multicap |

---

## Architecture Overview

```
[5 Groww URLs]
    │
    ▼
[Web Scraper] → [HTML Parser] → [Chunker] → [BGE Embedder] → [FAISS Index]
                                                                    │
[User Query] → [Classifier] → [Retriever] → [Prompt Builder] → [Groq LLM] → [Formatter] → [UI]
```

- **Embedding:** `BAAI/bge-base-en-v1.5` (local, dim=768)
- **Vector Store:** FAISS `IndexFlatL2`
- **LLM:** `llama-3.3-70b-versatile` via Groq API (temperature=0.0)
- **UI:** Streamlit

See [`docs/architecture.md`](docs/architecture.md) for the full technical breakdown.

---

## Setup

### 1. Clone & create virtual environment
```bash
git clone <repo-url>
cd rag-milestone
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
playwright install chromium   # for JS-rendered fallback
```

### 3. Configure API key
```bash
cp .env.example .env
# Edit .env and add your Groq API key:
# GROQ_API_KEY=your_key_here
```
Get a free key at [console.groq.com](https://console.groq.com).

### 4. Run the ingestion pipeline (offline — run once)
```bash
python src/scraper.py       # Phase 2: fetch HTML
python src/parser.py        # Phase 3: extract facts
python src/chunker.py       # Phase 4A: create chunks
python src/embedder.py      # Phase 4B + 5: embed & build FAISS index
```

### 5. Launch the assistant
```bash
streamlit run src/app.py
```

---

## Project Structure

```
rag-milestone/
├── docs/
│   ├── problemstatement.md
│   ├── architecture.md
│   ├── implementation_plan.md
│   ├── edge-cases.md
│   └── eval.md
├── data/
│   ├── raw/            # Raw HTML from Groww (gitignored)
│   └── processed/      # Parsed facts + chunks (gitignored)
├── vector_store/       # FAISS index + metadata (gitignored)
├── src/
│   ├── scraper.py
│   ├── parser.py
│   ├── chunker.py
│   ├── embedder.py
│   ├── retriever.py
│   ├── classifier.py
│   ├── prompt_builder.py
│   ├── llm.py
│   ├── formatter.py
│   └── app.py
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Disclaimer

> **Facts-only. No investment advice.**  
> This assistant provides factual information about mutual fund schemes only. It does not provide investment advice, recommendations, or opinions. Always consult a registered financial advisor before making investment decisions.

---

## Known Limitations

- Corpus is static — data reflects the scrape date shown in each response footer
- Only covers the 5 HDFC schemes listed above
- English queries only
- No real-time NAV feed
