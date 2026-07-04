"""
scraper.py — Phase 2: Data Ingestion (Web Scraping)
-----------------------------------------------------
Fetches raw HTML from each of the 5 Groww mutual fund scheme pages.

Strategy:
  1. Try with requests (fast, no JS execution)
  2. If fund-specific content is missing → fall back to Playwright (headless Chromium)
  3. Retry up to 3x with exponential backoff on any failure
  4. Save raw HTML to data/raw/<scheme_slug>.html
  5. Write data/raw/manifest.json with scraped_at timestamps per scheme

Usage:
    python src/scraper.py
"""

import os
import sys
import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent          # project root
RAW_DIR  = BASE_DIR / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# 5 target Groww URLs
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

# Keywords that must appear in valid fund HTML (basic content check)
CONTENT_MARKERS = [
    "expense ratio", "Expense Ratio",
    "exit load", "Exit Load",
    "nav", "NAV",
    "fund manager", "Fund Manager",
    "hdfc", "HDFC",
]

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

MAX_RETRIES     = 3
RETRY_BACKOFF   = 2      # seconds (doubled on each retry: 2, 4, 8)
REQUEST_TIMEOUT = 20     # seconds


# ── Helper: check if HTML has useful fund content ─────────────────────────────
def _has_fund_content(html: str) -> bool:
    """Return True if at least 2 content markers are found in the HTML."""
    lower = html.lower()
    hits = sum(1 for m in CONTENT_MARKERS if m.lower() in lower)
    return hits >= 2


# ── Strategy 1: plain requests ────────────────────────────────────────────────
def _fetch_with_requests(url: str) -> str | None:
    """
    Fetch page HTML using requests. Returns HTML string or None on failure.
    Retries up to MAX_RETRIES times with exponential backoff.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            log.info("  [requests] Attempt %d/%d → %s", attempt, MAX_RETRIES, url)
            resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)

            if resp.status_code == 200:
                log.info("  [requests] HTTP 200 — %d bytes received", len(resp.text))
                return resp.text
            else:
                log.warning("  [requests] HTTP %d — retrying…", resp.status_code)

        except requests.exceptions.Timeout:
            log.warning("  [requests] Timeout on attempt %d", attempt)
        except requests.exceptions.RequestException as e:
            log.warning("  [requests] Error on attempt %d: %s", attempt, e)

        if attempt < MAX_RETRIES:
            wait = RETRY_BACKOFF * (2 ** (attempt - 1))
            log.info("  [requests] Waiting %ds before retry…", wait)
            time.sleep(wait)

    log.error("  [requests] All %d attempts failed.", MAX_RETRIES)
    return None


# ── Strategy 2: Playwright (headless Chromium) ───────────────────────────────
def _fetch_with_playwright(url: str) -> str | None:
    """
    Fetch JS-rendered HTML using Playwright headless browser.
    Returns HTML string or None if Playwright is not installed / fails.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        log.error("  [playwright] Not installed. Run: playwright install chromium")
        return None

    log.info("  [playwright] Launching headless browser for %s", url)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=REQUEST_HEADERS["User-Agent"],
                    locale="en-US",
                )
                page = context.new_page()

                # Block images/fonts/media to speed up load
                page.route(
                    "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,mp4}",
                    lambda route: route.abort(),
                )

                page.goto(url, timeout=45_000, wait_until="domcontentloaded")

                # Wait for at least one of the fund-data selectors to appear
                try:
                    page.wait_for_selector(
                        "text=/expense ratio/i, text=/exit load/i, text=/nav/i",
                        timeout=15_000,
                    )
                    log.info("  [playwright] Fund content detected on page.")
                except PWTimeout:
                    log.warning("  [playwright] Timeout waiting for fund content selectors.")

                html = page.content()
                browser.close()

            log.info("  [playwright] %d bytes received", len(html))
            return html

        except PWTimeout:
            log.warning("  [playwright] Navigation timeout on attempt %d", attempt)
        except Exception as e:
            log.warning("  [playwright] Error on attempt %d: %s", attempt, e)

        if attempt < MAX_RETRIES:
            wait = RETRY_BACKOFF * (2 ** (attempt - 1))
            log.info("  [playwright] Waiting %ds before retry…", wait)
            time.sleep(wait)

    log.error("  [playwright] All %d attempts failed.", MAX_RETRIES)
    return None


# ── Core: scrape one scheme ───────────────────────────────────────────────────
def scrape_scheme(scheme: dict) -> dict:
    """
    Fetch and save HTML for one scheme.
    Returns a manifest entry dict with status and metadata.
    """
    name = scheme["name"]
    slug = scheme["slug"]
    url  = scheme["url"]
    out_path = RAW_DIR / f"{slug}.html"

    log.info("━━━ Scraping: %s", name)
    log.info("    URL: %s", url)

    html = None
    method_used = None

    # ── Step 1: try requests ──────────────────────────────────────────────────
    raw_html = _fetch_with_requests(url)

    if raw_html and _has_fund_content(raw_html):
        log.info("  ✓ requests returned valid fund content.")
        html = raw_html
        method_used = "requests"
    else:
        if raw_html:
            log.warning("  ✗ requests HTML missing fund content markers → falling back to Playwright.")
        else:
            log.warning("  ✗ requests failed → falling back to Playwright.")

        # ── Step 2: fall back to Playwright ──────────────────────────────────
        pw_html = _fetch_with_playwright(url)

        if pw_html and _has_fund_content(pw_html):
            log.info("  ✓ Playwright returned valid fund content.")
            html = pw_html
            method_used = "playwright"
        elif pw_html:
            log.warning("  ✗ Playwright HTML also missing fund content markers. Saving anyway.")
            html = pw_html
            method_used = "playwright_partial"
        else:
            log.error("  ✗ Both strategies failed for %s", name)
            return {
                "name": name,
                "slug": slug,
                "url": url,
                "status": "failed",
                "method": None,
                "scraped_at": None,
                "file": None,
                "bytes": 0,
            }

    # ── Save HTML to disk ─────────────────────────────────────────────────────
    scraped_at = datetime.now(timezone.utc).isoformat()

    # Validate completeness (check closing tag present)
    if "</html>" not in html.lower():
        log.warning("  ⚠ HTML may be truncated (no </html> tag found).")

    out_path.write_text(html, encoding="utf-8")
    size_bytes = out_path.stat().st_size
    log.info("  ✓ Saved → %s (%d bytes)", out_path, size_bytes)

    return {
        "name":       name,
        "slug":       slug,
        "url":        url,
        "status":     "success" if "partial" not in method_used else "partial",
        "method":     method_used,
        "scraped_at": scraped_at,
        "file":       str(out_path.relative_to(BASE_DIR)),
        "bytes":      size_bytes,
    }


# ── Save manifest ─────────────────────────────────────────────────────────────
def save_manifest(entries: list[dict]) -> None:
    manifest_path = RAW_DIR / "manifest.json"
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_schemes": len(entries),
        "schemes": entries,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("✓ manifest.json saved → %s", manifest_path)


# ── Post-scrape validation ────────────────────────────────────────────────────
def validate_results(entries: list[dict]) -> None:
    log.info("\n%s", "═" * 60)
    log.info("SCRAPING SUMMARY")
    log.info("═" * 60)

    passed = 0
    for e in entries:
        status_icon = "✓" if e["status"] == "success" else ("⚠" if e["status"] == "partial" else "✗")
        log.info(
            "  %s %-35s | %-18s | %s",
            status_icon,
            e["name"],
            e.get("method") or "N/A",
            f"{e['bytes']:,} bytes" if e["bytes"] else "0 bytes",
        )
        if e["status"] in ("success", "partial"):
            passed += 1

    log.info("━" * 60)
    log.info("  Result: %d / %d schemes scraped successfully", passed, len(entries))

    if passed < len(entries):
        log.warning(
            "  ⚠ %d scheme(s) failed. Check network and re-run scraper.py.",
            len(entries) - passed,
        )
    else:
        log.info("  ✓ All schemes scraped. Ready for Phase 3 (parser.py).")

    log.info("═" * 60)


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    log.info("╔══════════════════════════════════════════════════════════╗")
    log.info("║   Mutual Fund FAQ Assistant — Phase 2: Web Scraper       ║")
    log.info("╚══════════════════════════════════════════════════════════╝")
    log.info("Output directory: %s", RAW_DIR)
    log.info("")

    manifest_entries = []

    for scheme in SCHEMES:
        entry = scrape_scheme(scheme)
        manifest_entries.append(entry)
        log.info("")

    save_manifest(manifest_entries)
    validate_results(manifest_entries)

    # ── Exit with non-zero code if any scheme failed (signals GitHub Actions) ──
    failed = sum(1 for e in manifest_entries if e["status"] == "failed")
    if failed:
        log.error("Aborting: %d scheme(s) failed to scrape. Vector store will NOT be refreshed.", failed)
        sys.exit(1)


if __name__ == "__main__":
    main()
