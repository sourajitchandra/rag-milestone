"""
parser.py — Phase 3: HTML Parsing & Text Extraction
------------------------------------------------------
Parses raw HTML saved by scraper.py and extracts structured facts
for each HDFC mutual fund scheme.

Strategy (layered, most reliable first):
  1. Parse the Next.js __NEXT_DATA__ JSON blob embedded in the page
     (contains clean, machine-readable fund metadata)
  2. Regex extraction on the visible page text (fund management block,
     About block, structured labels)
  3. BeautifulSoup CSS selector patterns on the DOM

Fields extracted per scheme:
  - scheme_name, category, amc
  - expense_ratio, exit_load
  - minimum_sip, minimum_lumpsum
  - lock_in_period, riskometer
  - benchmark_index, nav, nav_date, fund_managers

Output: data/processed/<scheme_slug>_facts.json

Usage:
    python src/parser.py
"""

import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).resolve().parent.parent
RAW_DIR   = BASE_DIR / "data" / "raw"
PROC_DIR  = BASE_DIR / "data" / "processed"
PROC_DIR.mkdir(parents=True, exist_ok=True)

# ── Scheme registry (matches scraper.py) ──────────────────────────────────────
SCHEMES = [
    {
        "name": "HDFC Technology Fund",
        "slug": "hdfc_technology_fund",
        "url":  "https://groww.in/mutual-funds/hdfc-technology-fund-direct-growth",
    },
    {
        "name": "HDFC Silver ETF FoF",
        "slug": "hdfc_silver_etf_fof",
        "url":  "https://groww.in/mutual-funds/hdfc-silver-etf-fof-direct-growth",
    },
    {
        "name": "HDFC Defence Fund",
        "slug": "hdfc_defence_fund",
        "url":  "https://groww.in/mutual-funds/hdfc-defence-fund-direct-growth",
    },
    {
        "name": "HDFC Liquid Fund",
        "slug": "hdfc_liquid_fund",
        "url":  "https://groww.in/mutual-funds/hdfc-liquid-fund-direct-growth",
    },
    {
        "name": "HDFC Nifty500 Multicap 50:25:25",
        "slug": "hdfc_nifty500_multicap",
        "url":  "https://groww.in/mutual-funds/hdfc-nifty500-multicap-50:25:25-index-fund-direct-growth",
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — Next.js __NEXT_DATA__ JSON extraction
# ══════════════════════════════════════════════════════════════════════════════

def _extract_next_data(soup: BeautifulSoup) -> dict:
    """
    Groww is a Next.js app. Every page embeds all server-side props in a
    <script id="__NEXT_DATA__" type="application/json"> tag.
    This gives clean, structured data without brittle CSS selectors.
    """
    tag = soup.find("script", {"id": "__NEXT_DATA__"})
    if not tag or not tag.string:
        return {}
    try:
        return json.loads(tag.string)
    except json.JSONDecodeError as exc:
        log.warning("  __NEXT_DATA__ JSON parse error: %s", exc)
        return {}


def _parse_from_next_data(nd: dict) -> dict:
    """
    Navigate the Next.js props tree to extract all required fields.
    Returns a partial facts dict (missing keys → None).
    """
    facts: dict = {k: None for k in [
        "scheme_name", "category", "amc", "expense_ratio", "exit_load",
        "minimum_sip", "minimum_lumpsum", "lock_in_period", "riskometer",
        "benchmark_index", "nav", "nav_date", "fund_managers",
    ]}

    try:
        page_props = nd.get("props", {}).get("pageProps", {})
        mf_data    = page_props.get("mfServerSideData", {})
        stp        = mf_data.get("stp_details", {})
        fund_data  = mf_data.get("fund_data", {})
        scheme_info = mf_data.get("scheme_info", {})

        # ── scheme_name ───────────────────────────────────────────────────────
        name = (
            stp.get("legal_name")
            or stp.get("scheme_name")
            or fund_data.get("scheme_name")
            or scheme_info.get("scheme_name")
        )
        if name:
            facts["scheme_name"] = name.strip()

        # ── category ─────────────────────────────────────────────────────────
        cat = stp.get("category") or fund_data.get("category")
        sub = stp.get("sub_category") or fund_data.get("sub_category")
        if cat and sub and sub.lower() != cat.lower():
            facts["category"] = f"{cat} – {sub}".strip()
        elif cat:
            facts["category"] = cat.strip()

        # ── AMC / fund house ──────────────────────────────────────────────────
        amc = (
            stp.get("amc_name")
            or fund_data.get("amc_name")
            or scheme_info.get("amc_name")
        )
        if amc:
            facts["amc"] = amc.strip()

        # ── expense_ratio ─────────────────────────────────────────────────────
        er = (
            stp.get("expense_ratio")
            or fund_data.get("expense_ratio")
            or mf_data.get("expense_ratio")
        )
        if er is not None:
            facts["expense_ratio"] = f"{er}%"

        # ── exit_load ─────────────────────────────────────────────────────────
        el = (
            stp.get("exit_load")
            or fund_data.get("exit_load")
            or mf_data.get("exit_load_desc")
        )
        if el:
            facts["exit_load"] = str(el).strip()

        # ── minimum_sip ───────────────────────────────────────────────────────
        sip = (
            stp.get("min_sip_amount")
            or fund_data.get("min_sip_amount")
            or mf_data.get("min_sip_amount")
        )
        if sip is not None:
            facts["minimum_sip"] = f"₹{sip}"

        # ── minimum_lumpsum ───────────────────────────────────────────────────
        lump = (
            stp.get("min_purchase_amount")
            or fund_data.get("min_purchase_amount")
            or stp.get("min_investment")
        )
        if lump is not None:
            facts["minimum_lumpsum"] = f"₹{lump}"

        # ── lock_in_period ────────────────────────────────────────────────────
        lock = (
            stp.get("lock_in_period")
            or fund_data.get("lock_in_period")
        )
        if lock is not None:
            facts["lock_in_period"] = str(lock).strip() if lock else "N/A"

        # ── riskometer ────────────────────────────────────────────────────────
        risk = (
            stp.get("risk_rating")
            or fund_data.get("risk_rating")
            or stp.get("risk")
        )
        if risk:
            facts["riskometer"] = str(risk).strip()

        # ── benchmark_index ───────────────────────────────────────────────────
        bench = (
            stp.get("benchmark_name")
            or fund_data.get("benchmark_name")
            or stp.get("benchmark")
        )
        if bench:
            facts["benchmark_index"] = bench.strip()

        # ── NAV ───────────────────────────────────────────────────────────────
        nav = (
            stp.get("nav")
            or fund_data.get("nav")
            or mf_data.get("latest_nav")
        )
        if nav is not None:
            facts["nav"] = f"₹{nav}"

        nav_date = stp.get("nav_date") or fund_data.get("nav_date")
        if nav_date:
            facts["nav_date"] = str(nav_date)

        # ── fund_managers ─────────────────────────────────────────────────────
        mgrs = (
            mf_data.get("fund_managers")
            or fund_data.get("fund_managers")
            or stp.get("fund_managers")
        )
        if mgrs:
            if isinstance(mgrs, list):
                names = []
                for m in mgrs:
                    if isinstance(m, dict):
                        n = m.get("name") or m.get("manager_name") or ""
                        if n:
                            names.append(n.strip())
                    elif isinstance(m, str):
                        names.append(m.strip())
                facts["fund_managers"] = ", ".join(names) if names else None
            elif isinstance(mgrs, str):
                facts["fund_managers"] = mgrs.strip()

    except Exception as exc:
        log.warning("  __NEXT_DATA__ navigation error: %s", exc)

    return facts


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — Regex extraction on visible page text
# ══════════════════════════════════════════════════════════════════════════════

def _get_full_text(soup: BeautifulSoup) -> str:
    """Return all visible text joined from the page body."""
    body = soup.find("body")
    return body.get_text(separator=" ", strip=True) if body else ""


def _extract_fund_managers(text: str) -> str | None:
    """
    Extract fund manager names from the 'Fund management' section.
    Pattern: "Fund management [initials] FirstName LastName Month Year"
    """
    mgr_blocks = re.findall(
        r'Fund management\s+(.*?)(?:About HDFC|Investment Objective|Fund benchmark)',
        text, re.S
    )
    if not mgr_blocks:
        return None

    block = mgr_blocks[0]
    # Match names before a month (Jan–Dec)
    names = re.findall(
        r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s+'
        r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)',
        block
    )
    # Deduplicate while preserving order
    seen = set()
    unique_names = []
    for n in names:
        if n not in seen:
            seen.add(n)
            unique_names.append(n)
    return ", ".join(unique_names) if unique_names else None


def _extract_category(text: str) -> str | None:
    """Extract fund category from page text."""
    # Priority order: specific to generic
    patterns = [
        # "Category average (Equity Sectoral)" — most reliable
        (r'Category average \(([^)]+)\)', 1),
        # "Equity Sectoral" / "Equity Thematic" etc.
        (r'Equity\s+(Sectoral|Thematic|Large Cap|Mid Cap|Small Cap|Balanced|Hybrid)', 1),
        # "ETF Fund of Fund" or "Fund of Fund"
        (r'(ETF Fund of Fund|Gold ETF Fund of Fund|Silver ETF Fund of Fund)', 1),
        # "Index Fund"
        (r'(Nifty\d+[^\s]+\s+Index Fund|NIFTY[^\s]+\s+Index Fund|Index Fund)', 1),
        # "Liquid Fund", "Overnight Fund"
        (r'(Liquid Fund|Overnight Fund|Ultra Short|Money Market)', 1),
    ]
    for pat, grp in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return m.group(grp).strip()
    return None


def _extract_exit_load(text: str) -> str | None:
    """
    Extract current exit load from the dated exit load history section.
    Groww shows dated entries; the most recent one is the current policy.
    """
    # Try to find the "about" paragraph exit load first (reliable)
    about_m = re.search(
        r'(?:About HDFC[^\n]+\n|About\s+HDFC[^\n]+)(.*?)(?:Investment Objective|Fund benchmark)',
        text, re.S
    )
    if about_m:
        about_block = about_m.group(1)
        m = re.search(r'[Ee]xit load of ([^;]+?)(?:;|\.|$)', about_block)
        if m:
            val = m.group(1).strip()
            if val and val != "0":
                return f"Exit load of {val}."

    # Fall back: find first "Exit load of X%" in the exit load section
    m = re.search(
        r'Exit [Ll]oad\s+(?:\d{2}\s+\w+\s+\d{4}\s+)?[Ee]xit load of\s+([^.]+\.)',
        text
    )
    if m:
        return f"Exit load of {m.group(1).strip()}"

    # Check for Nil / no exit load
    if re.search(r'[Ee]xit [Ll]oad[^A-Za-z]{0,20}(?:Nil|nil|0%|Zero|None)', text):
        return "Nil"

    # Nifty500 Multicap: if exit load section exists but no amount → Nil
    if re.search(r'[Ee]xit [Ll]oad\s+Stamp duty', text):
        return "Nil"

    return None


def _regex_extract(text: str) -> dict:
    """
    Extract all required fields using regex patterns.
    This is the Layer 2 fallback.
    """
    facts: dict = {}

    # ── NAV ───────────────────────────────────────────────────────────────────
    m = re.search(
        r'Latest NAV as of [^\s]+ \w+ \d+\s+is\s+[₹\u20b9]([\d,]+\.?\d*)',
        text, re.I
    )
    if not m:
        m = re.search(r'NAV[^₹\u20b9]{0,30}[₹\u20b9]([\d,]+\.?\d*)', text, re.I)
    if m:
        facts["nav"] = f"₹{m.group(1).replace(',', '')}"

    # ── expense_ratio ─────────────────────────────────────────────────────────
    # Use the labeled sibling in the summary bar: "Expense ratio\s*\d+.xx%"
    m = re.search(r'Expense ratio\s*([\d]+\.[\d]+)%', text)
    if m:
        facts["expense_ratio"] = f"{m.group(1)}%"
    else:
        m = re.search(r'[Ee]xpense [Rr]atio\s+is\s+([\d]+\.[\d]+)%', text)
        if m:
            facts["expense_ratio"] = f"{m.group(1)}%"

    # ── exit_load ─────────────────────────────────────────────────────────────
    el = _extract_exit_load(text)
    if el:
        facts["exit_load"] = el

    # ── minimum_sip ───────────────────────────────────────────────────────────
    m = re.search(r'[Mm]inimum SIP [Ii]nvestment\s+(?:is set to\s+)?[₹\u20b9]([\d,]+)', text)
    if not m:
        m = re.search(r'Min\. for SIP\s+[₹\u20b9]([\d,]+)', text)
    if m:
        facts["minimum_sip"] = f"₹{m.group(1).replace(',', '')}"

    # ── minimum_lumpsum ───────────────────────────────────────────────────────
    # Handle both ₹amount and "Not Supported"
    m = re.search(r'[Mm]inimum Lumpsum [Ii]nvestment\s+(?:is\s+)?[₹\u20b9]([\d,]+)', text)
    if not m:
        m = re.search(r'Min\. for 1st investment\s+([₹\u20b9][\d,]+|Not Supported)', text)
    if m:
        val = m.group(1).strip()
        if val == "Not Supported":
            facts["minimum_lumpsum"] = "Not Supported (direct SIP only)"
        else:
            facts["minimum_lumpsum"] = f"₹{val.replace('₹', '').replace(',', '')}"

    # ── riskometer ────────────────────────────────────────────────────────────
    m = re.search(
        r'(Very High|Moderately High|High|Moderate|Moderately Low|Low)\s+[Rr]isk',
        text
    )
    if m:
        facts["riskometer"] = m.group(1).strip()

    # ── benchmark_index ───────────────────────────────────────────────────────
    m = re.search(
        r'[Ff]und benchmark\s*([^\n]+?)(?:\s{2,}|Scheme Information|SID|Fund house)',
        text
    )
    if m:
        facts["benchmark_index"] = m.group(1).strip()

    # ── AMC ───────────────────────────────────────────────────────────────────
    m = re.search(r'[Ff]und house\s+(HDFC [A-Za-z\s]+?)(?:\s{2,}|Rank|Total AUM|\n)', text)
    if m:
        facts["amc"] = m.group(1).strip()

    # ── category ─────────────────────────────────────────────────────────────
    cat = _extract_category(text)
    if cat:
        facts["category"] = cat

    # ── fund_managers ─────────────────────────────────────────────────────────
    mgrs = _extract_fund_managers(text)
    if mgrs:
        facts["fund_managers"] = mgrs

    return facts


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 3 — BeautifulSoup DOM selectors
# ══════════════════════════════════════════════════════════════════════════════

def _dom_extract(soup: BeautifulSoup) -> dict:
    """
    Extract facts from specific DOM patterns in Groww's HTML.
    Used as a final patch-up layer for any fields still missing.
    """
    facts: dict = {}

    # ── scheme_name: <title> tag ──────────────────────────────────────────────
    title_tag = soup.find("title")
    if title_tag:
        title_text = title_tag.get_text(strip=True)
        name_part = title_text.split(" - ")[0].strip()
        if name_part:
            facts["scheme_name"] = name_part

    # ── expense_ratio: label+value sibling pattern ───────────────────────────
    er_labels = soup.find_all(string=re.compile(r"^Expense ratio$", re.I))
    for label in er_labels:
        parent = label.parent
        if not parent:
            continue
        gp = parent.parent
        if gp:
            siblings = [s.get_text(strip=True) for s in gp.children
                        if hasattr(s, "get_text")]
            for sib in siblings:
                if re.match(r"^\d+\.?\d*%$", sib):
                    facts["expense_ratio"] = sib
                    break

    # ── riskometer: risk badge ────────────────────────────────────────────────
    risk_tags = soup.find_all(
        string=re.compile(r"(Very High|Moderately High|High|Moderate|Moderately Low|Low)\s+Risk", re.I)
    )
    for rt in risk_tags:
        m = re.search(
            r"(Very High|Moderately High|High|Moderate|Moderately Low|Low)\s+Risk", rt, re.I
        )
        if m:
            facts["riskometer"] = m.group(1).strip()
            break

    # ── minimum_sip from DOM sibling ─────────────────────────────────────────
    sip_labels = soup.find_all(string=re.compile(r"Min\. for SIP", re.I))
    for label in sip_labels:
        parent = label.parent
        if parent:
            gp = parent.parent
            if gp:
                sibs = [s.get_text(strip=True) for s in gp.children
                        if hasattr(s, "get_text") and s.get_text(strip=True)]
                for sib in sibs:
                    if sib == str(label).strip():
                        continue
                    m = re.search(r"[₹\u20b9]([\d,]+)", sib)
                    if m:
                        facts["minimum_sip"] = f"₹{m.group(1).replace(',', '')}"
                        break

    # ── category ─────────────────────────────────────────────────────────────
    # Look for the subtitle row (e.g. "Equity Sectoral" right after fund name)
    cat_candidates = soup.find_all(
        string=re.compile(r"\b(Sectoral|Thematic|ETF FoF|Index Fund|Liquid|FoF)\b", re.I)
    )
    for ct in cat_candidates[:5]:
        parent = ct.parent
        if parent and parent.name in ("div", "span", "a", "p"):
            text = ct.strip()
            if len(text) < 60:
                facts.setdefault("category", text)
                break

    return facts


# ══════════════════════════════════════════════════════════════════════════════
# UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def _merge(base: dict, patch: dict) -> dict:
    """Fill None / missing values in base with values from patch."""
    for k, v in patch.items():
        if v and not base.get(k):
            base[k] = v
    return base


def _post_process(facts: dict, text: str) -> dict:
    """Final clean-up and inference steps."""

    # ── lock_in_period: infer from fund name ──────────────────────────────────
    if not facts.get("lock_in_period"):
        name = (facts.get("scheme_name") or "").lower()
        facts["lock_in_period"] = "3 years" if ("elss" in name or "tax saver" in name) else "N/A"

    # ── exit_load: final attempt if still missing ─────────────────────────────
    if not facts.get("exit_load"):
        el = _extract_exit_load(text)
        facts["exit_load"] = el or "Nil"

    # ── exit_load: normalise "0" / "0%" → "Nil" ──────────────────────────────
    el = facts.get("exit_load", "")
    if el and re.match(r"^[Ee]xit load of\s+0\.?$", el.strip()):
        facts["exit_load"] = "Nil"

    # ── amc: default for all 5 schemes ───────────────────────────────────────
    if not facts.get("amc"):
        facts["amc"] = "HDFC Mutual Fund"

    # ── Normalise riskometer casing ───────────────────────────────────────────
    if facts.get("riskometer"):
        r = facts["riskometer"]
        # Ensure title case (e.g. "VERY HIGH" → "Very High")
        facts["riskometer"] = " ".join(w.capitalize() for w in r.split())

    # ── Normalise NAV ─────────────────────────────────────────────────────────
    if facts.get("nav") and not facts["nav"].startswith("₹"):
        facts["nav"] = f"₹{facts['nav']}"

    return facts


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PARSER — orchestrates all layers
# ══════════════════════════════════════════════════════════════════════════════

def parse_scheme(scheme: dict, scraped_at: str | None) -> dict:
    """
    Parse a single scheme's HTML file.
    Returns a complete facts dict for that scheme.
    """
    slug = scheme["slug"]
    name = scheme["name"]
    url  = scheme["url"]
    html_path = RAW_DIR / f"{slug}.html"

    if not html_path.exists():
        log.error("  HTML file not found: %s", html_path)
        return {"slug": slug, "scheme_name": name, "source_url": url,
                "error": "html_missing"}

    log.info("━━━ Parsing: %s", name)
    html = html_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    # ── Layer 1: Next.js JSON ─────────────────────────────────────────────────
    nd = _extract_next_data(soup)
    facts = _parse_from_next_data(nd)
    filled1 = sum(1 for v in facts.values() if v)
    log.info("  Layer 1 (Next.js JSON): %d/%d fields filled", filled1, len(facts))

    # ── Layer 2: regex on full text ───────────────────────────────────────────
    full_text = _get_full_text(soup)
    regex_facts = _regex_extract(full_text)
    facts = _merge(facts, regex_facts)
    filled2 = sum(1 for v in facts.values() if v)
    log.info("  Layer 2 (regex): %d/%d fields filled", filled2, len(facts))

    # ── Layer 3: DOM selectors ────────────────────────────────────────────────
    dom_facts = _dom_extract(soup)
    facts = _merge(facts, dom_facts)
    filled3 = sum(1 for v in facts.values() if v)
    log.info("  Layer 3 (DOM): %d/%d fields filled", filled3, len(facts))

    # ── Post-processing ───────────────────────────────────────────────────────
    facts = _post_process(facts, full_text)

    # ── Ensure scheme_name is never null ─────────────────────────────────────
    if not facts.get("scheme_name"):
        facts["scheme_name"] = name

    # ── Attach provenance metadata ────────────────────────────────────────────
    facts["slug"]       = slug
    facts["source_url"] = url
    facts["scraped_at"] = scraped_at or "unknown"
    facts["parsed_at"]  = datetime.now(timezone.utc).isoformat()

    # ── Final fill count ──────────────────────────────────────────────────────
    core_fields = [
        "scheme_name", "category", "amc", "expense_ratio", "exit_load",
        "minimum_sip", "minimum_lumpsum", "lock_in_period", "riskometer",
        "benchmark_index", "nav", "fund_managers",
    ]
    filled = sum(1 for f in core_fields if facts.get(f))
    missing = [f for f in core_fields if not facts.get(f)]
    log.info("  Final: %d/%d core fields filled", filled, len(core_fields))
    if missing:
        log.warning("  Missing fields: %s", missing)

    return facts


def save_facts(facts: dict, slug: str) -> Path:
    """Save the facts dict as JSON to data/processed/."""
    out_path = PROC_DIR / f"{slug}_facts.json"
    out_path.write_text(
        json.dumps(facts, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("  ✓ Saved → %s", out_path)
    return out_path


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    log.info("╔══════════════════════════════════════════════════════════╗")
    log.info("║  Mutual Fund FAQ Assistant — Phase 3: HTML Parser        ║")
    log.info("╚══════════════════════════════════════════════════════════╝")

    # Load manifest to get scraped_at timestamps
    manifest_path = RAW_DIR / "manifest.json"
    scraped_at_map: dict = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for s in manifest.get("schemes", []):
            scraped_at_map[s["slug"]] = s.get("scraped_at")
    else:
        log.warning("manifest.json not found — scraped_at will be 'unknown'")

    results = []
    for scheme in SCHEMES:
        slug = scheme["slug"]
        scraped_at = scraped_at_map.get(slug)
        facts = parse_scheme(scheme, scraped_at)
        save_facts(facts, slug)
        results.append(facts)
        log.info("")

    # ── Summary ───────────────────────────────────────────────────────────────
    log.info("═" * 60)
    log.info("PARSING SUMMARY")
    log.info("═" * 60)

    core_fields = [
        "scheme_name", "category", "amc", "expense_ratio", "exit_load",
        "minimum_sip", "minimum_lumpsum", "lock_in_period", "riskometer",
        "benchmark_index", "nav", "fund_managers",
    ]

    all_ok = True
    for r in results:
        missing = [f for f in core_fields if not r.get(f)]
        status = "✓" if not missing else "⚠"
        log.info(
            "  %s %-40s | missing: %s",
            status,
            (r.get("scheme_name") or r["slug"])[:40],
            missing if missing else "none",
        )
        if missing:
            all_ok = False

    log.info("━" * 60)
    if all_ok:
        log.info("  ✓ All schemes fully parsed. Ready for Phase 4 (chunker.py).")
    else:
        log.warning("  ⚠ Some fields missing — see warnings above.")
        log.error("Aborting: parse incomplete. Vector store will NOT be refreshed.")
        sys.exit(1)
    log.info("═" * 60)


if __name__ == "__main__":
    main()
