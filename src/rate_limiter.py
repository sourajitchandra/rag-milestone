"""
rate_limiter.py — Phase 6C: Groq API Rate Limit Guard
-------------------------------------------------------
Enforces Groq free-tier quota limits using in-memory sliding windows.

Groq Free-Tier Limits (as of 2026-07):
    RPM  (Requests per Minute)  :    30
    RPD  (Requests per Day)     : 1 000
    TPM  (Tokens per Minute)    : 12 000
    TPD  (Tokens per Day)       : 100 000

Pipeline position:
    classify → [rate_limit_check] → retrieve → prompt → LLM → format

Why here (not in llm.py):
    Blocking before retrieval avoids wasting FAISS + embedding work on a call
    that will be rejected by the Groq API anyway.

Token estimation:
    Each RAG call sends roughly 450–600 prompt tokens (system prompt ~100,
    3 × chunk context ~60–80 tokens each, user query ~20 tokens) and receives
    up to 200 completion tokens (max_tokens in llm.py). We estimate conservatively
    at 650 tokens per request: this keeps daily headroom accurate without
    requiring an actual pre-call tokeniser.

Usage:
    from rate_limiter import RateLimiter, RateLimitExceeded

    rl = RateLimiter()           # create once at startup
    try:
        rl.check_and_record()    # call before every LLM-bound query
    except RateLimitExceeded as e:
        return str(e)            # return the user-facing message
"""

import logging
import time
from collections import deque
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


# ── Groq free-tier limits ─────────────────────────────────────────────────────
RPM_LIMIT = 30           # max requests per 60-second window
RPD_LIMIT = 1_000        # max requests per 24-hour window
TPM_LIMIT = 12_000       # max tokens per 60-second window
TPD_LIMIT = 100_000      # max tokens per 24-hour window

# ── Token estimation ──────────────────────────────────────────────────────────
# Conservative upper-bound per request:
#   prompt  ≈ 100 (system) + 3×75 (chunks) + 20 (query) = 345
#   response ≤ 200 (max_tokens in llm.py)
#   total   ≈ 545  →  round up to 650 for safety margin
TOKENS_PER_REQUEST_ESTIMATE = 650

# ── Window sizes (seconds) ────────────────────────────────────────────────────
MINUTE_WINDOW = 60
DAY_WINDOW    = 86_400   # 24 × 60 × 60


class RateLimitExceeded(Exception):
    """Raised when a Groq quota limit would be exceeded."""


@dataclass
class RateLimiter:
    """
    Sliding-window rate limiter for Groq API calls.

    Uses four deques — one per quota axis — each storing the timestamp
    of every recorded request. Old entries are pruned before each check.

    All state is in-memory: resets on process restart.
    For a single-session CLI / web app, this is sufficient.
    """

    # Deques of (timestamp: float) for the sliding minute window
    _rpm_window: deque = field(default_factory=deque)
    _tpm_window: deque = field(default_factory=deque)  # stores (timestamp, tokens) tuples

    # Deques for the sliding 24-hour window
    _rpd_window: deque = field(default_factory=deque)
    _tpd_window: deque = field(default_factory=deque)  # stores (timestamp, tokens) tuples

    # ── Public API ────────────────────────────────────────────────────────────

    def check_and_record(self, estimated_tokens: int = TOKENS_PER_REQUEST_ESTIMATE) -> None:
        """
        Check whether a new LLM request is within all quota limits.
        If allowed, record the request immediately.
        If not, raise RateLimitExceeded with a user-facing message and
        the number of seconds until the limit resets.

        Args:
            estimated_tokens: Estimated total tokens for this request.
                               Defaults to TOKENS_PER_REQUEST_ESTIMATE (650).

        Raises:
            RateLimitExceeded: When any quota would be exceeded.
        """
        now = time.time()

        # Prune expired entries from all windows
        self._prune(now)

        # ── Check all four limits before recording anything ────────────────
        self._check_rpm(now)
        self._check_rpd(now)
        self._check_tpm(now, estimated_tokens)
        self._check_tpd(now, estimated_tokens)

        # ── Record the request ─────────────────────────────────────────────
        self._rpm_window.append(now)
        self._rpd_window.append(now)
        self._tpm_window.append((now, estimated_tokens))
        self._tpd_window.append((now, estimated_tokens))

        log.info(
            "Rate limiter: RPM=%d/%d  RPD=%d/%d  TPM~%d/%d  TPD~%d/%d",
            len(self._rpm_window), RPM_LIMIT,
            len(self._rpd_window), RPD_LIMIT,
            self._tpm_used(), TPM_LIMIT,
            self._tpd_used(), TPD_LIMIT,
        )

    def status(self) -> dict:
        """
        Return current quota usage.  Useful for logging or debugging.

        Returns:
            dict with keys: rpm_used, rpm_limit, rpd_used, rpd_limit,
                            tpm_used, tpm_limit, tpd_used, tpd_limit
        """
        self._prune(time.time())
        return {
            "rpm_used":  len(self._rpm_window),
            "rpm_limit": RPM_LIMIT,
            "rpd_used":  len(self._rpd_window),
            "rpd_limit": RPD_LIMIT,
            "tpm_used":  self._tpm_used(),
            "tpm_limit": TPM_LIMIT,
            "tpd_used":  self._tpd_used(),
            "tpd_limit": TPD_LIMIT,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _prune(self, now: float) -> None:
        """Remove entries outside their respective sliding windows."""
        minute_cutoff = now - MINUTE_WINDOW
        day_cutoff    = now - DAY_WINDOW

        while self._rpm_window and self._rpm_window[0] < minute_cutoff:
            self._rpm_window.popleft()
        while self._rpd_window and self._rpd_window[0] < day_cutoff:
            self._rpd_window.popleft()
        while self._tpm_window and self._tpm_window[0][0] < minute_cutoff:
            self._tpm_window.popleft()
        while self._tpd_window and self._tpd_window[0][0] < day_cutoff:
            self._tpd_window.popleft()

    def _tpm_used(self) -> int:
        return sum(t for _, t in self._tpm_window)

    def _tpd_used(self) -> int:
        return sum(t for _, t in self._tpd_window)

    def _check_rpm(self, now: float) -> None:
        if len(self._rpm_window) >= RPM_LIMIT:
            # The oldest entry in the window tells us when it will expire
            oldest = self._rpm_window[0]
            wait   = int(MINUTE_WINDOW - (now - oldest)) + 1
            log.warning("Rate limit: RPM limit reached (%d/%d). Wait %ds.", len(self._rpm_window), RPM_LIMIT, wait)
            raise RateLimitExceeded(
                f"I've reached the per-minute request limit ({RPM_LIMIT} requests/min).\n"
                f"Please wait about {wait} second(s) and try again."
            )

    def _check_rpd(self, now: float) -> None:
        if len(self._rpd_window) >= RPD_LIMIT:
            oldest = self._rpd_window[0]
            wait_h = int((DAY_WINDOW - (now - oldest)) / 3600) + 1
            log.warning("Rate limit: RPD limit reached (%d/%d).", len(self._rpd_window), RPD_LIMIT)
            raise RateLimitExceeded(
                f"I've reached the daily request limit ({RPD_LIMIT} requests/day).\n"
                f"The quota resets in approximately {wait_h} hour(s). Please try again later."
            )

    def _check_tpm(self, now: float, new_tokens: int) -> None:
        used = self._tpm_used()
        if used + new_tokens > TPM_LIMIT:
            oldest = self._tpm_window[0][0] if self._tpm_window else now
            wait   = int(MINUTE_WINDOW - (now - oldest)) + 1
            log.warning("Rate limit: TPM limit reached (~%d/%d). Wait %ds.", used, TPM_LIMIT, wait)
            raise RateLimitExceeded(
                f"I've reached the per-minute token limit (~{TPM_LIMIT:,} tokens/min).\n"
                f"Please wait about {wait} second(s) and try again."
            )

    def _check_tpd(self, now: float, new_tokens: int) -> None:
        used = self._tpd_used()
        if used + new_tokens > TPD_LIMIT:
            oldest = self._tpd_window[0][0] if self._tpd_window else now
            wait_h = int((DAY_WINDOW - (now - oldest)) / 3600) + 1
            log.warning("Rate limit: TPD limit reached (~%d/%d).", used, TPD_LIMIT)
            raise RateLimitExceeded(
                f"I've reached the daily token limit (~{TPD_LIMIT:,} tokens/day).\n"
                f"The quota resets in approximately {wait_h} hour(s). Please try again later."
            )


# ══════════════════════════════════════════════════════════════════════════════
# SELF-TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    print("RATE LIMITER UNIT TESTS")
    print("=" * 60)
    print(f"  Limits: RPM={RPM_LIMIT}  RPD={RPD_LIMIT}  TPM={TPM_LIMIT}  TPD={TPD_LIMIT}")
    print(f"  Token estimate per request: {TOKENS_PER_REQUEST_ESTIMATE}")
    print()

    # ── Test 1: Normal requests go through ───────────────────────────────────
    rl = RateLimiter()
    ok_count = 0
    for i in range(5):
        try:
            rl.check_and_record()
            ok_count += 1
        except RateLimitExceeded:
            pass
    print(f"  [{'PASS' if ok_count == 5 else 'FAIL'}] 5 normal requests accepted: {ok_count}/5")

    # ── Test 2: RPM limit triggers at 30 within a minute ─────────────────────
    rl2 = RateLimiter()
    blocked = False
    try:
        for _ in range(RPM_LIMIT + 1):
            rl2.check_and_record()
    except RateLimitExceeded as e:
        blocked = True
        print(f"  [{'PASS' if blocked else 'FAIL'}] RPM limit blocked at request {RPM_LIMIT + 1}")
        print(f"         Message: {str(e)[:80]}")

    # ── Test 3: TPM limit triggers within a minute ────────────────────────────
    rl3 = RateLimiter()
    tpm_blocked = False
    # TPM_LIMIT / TOKENS_PER_REQUEST_ESTIMATE = 12000/650 = 18.46 → blocked on 19th
    max_tpm_calls = TPM_LIMIT // TOKENS_PER_REQUEST_ESTIMATE
    try:
        for _ in range(max_tpm_calls + 1):
            rl3.check_and_record()
    except RateLimitExceeded as e:
        tpm_blocked = True
        print(f"  [{'PASS' if tpm_blocked else 'FAIL'}] TPM limit blocked at call {max_tpm_calls + 1}")
        print(f"         Message: {str(e)[:80]}")

    # ── Test 4: Status dict is correct ───────────────────────────────────────
    rl4 = RateLimiter()
    rl4.check_and_record()
    rl4.check_and_record()
    s = rl4.status()
    ok_status = s["rpm_used"] == 2 and s["tpm_used"] == 2 * TOKENS_PER_REQUEST_ESTIMATE
    print(f"  [{'PASS' if ok_status else 'FAIL'}] status() correct after 2 calls: rpm_used={s['rpm_used']}, tpm_used={s['tpm_used']}")

    print()
    print("=" * 60)
    print("  All tests complete.")
