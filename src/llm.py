"""
llm.py — Phase 7B: LLM Integration (Groq API)
-------------------------------------------------
Calls the Groq API with the assembled RAG prompt and returns the
raw LLM response text.

Model:       llama-3.3-70b-versatile (via Groq)
Temperature: 0.0  (deterministic — same query always produces same answer)
Max tokens:  200  (enforces brevity; formatter truncates to ≤ 3 sentences anyway)

Error handling:
  - Missing API key  → RuntimeError (no retry, configuration problem)
  - Groq rate-limit  → RuntimeError with wait advice
                       (pipeline's RateLimiter should prevent this in practice)
  - Transient errors → exponential back-off, up to MAX_RETRIES attempts
  - Other API errors → RuntimeError (bubble up to app.py for user-facing message)

Usage:
    from llm import call_llm
    response_text = call_llm(prompt)
"""

import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger(__name__)

# ── Load .env ─────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ── Config ────────────────────────────────────────────────────────────────────
MODEL_NAME  = "llama-3.3-70b-versatile"
TEMPERATURE = 0.0
MAX_TOKENS  = 200

# ── Retry config (transient 5xx / network errors only) ───────────────────────
MAX_RETRIES  = 3
RETRY_DELAYS = [1, 3, 7]   # seconds between attempts (exponential backoff)


def call_llm(prompt: str) -> str:
    """
    Send the prompt to the Groq API and return the response text.

    Retries up to MAX_RETRIES times on transient server errors.
    Does NOT retry on rate-limit errors (handled by RateLimiter in Phase 6C)
    or authentication errors (no point retrying without a key change).

    Args:
        prompt: The fully assembled RAG prompt from prompt_builder.build_prompt().

    Returns:
        Raw response text from the LLM (stripped of leading/trailing whitespace).

    Raises:
        RuntimeError: On missing API key, auth failure, rate-limit, or
                      exhausted retries.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY not found. "
            "Set it in .env (copy .env.example) or as an environment variable."
        )

    try:
        from groq import Groq
        from groq import RateLimitError, AuthenticationError, APIStatusError
    except ImportError as e:
        raise RuntimeError(
            f"groq package not installed. Run: pip install groq\n{e}"
        ) from e

    client = Groq(api_key=api_key)

    last_exc: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            log.info(
                "Groq API call attempt %d/%d (model=%s, temp=%.1f, max_tokens=%d)",
                attempt, MAX_RETRIES, MODEL_NAME, TEMPERATURE, MAX_TOKENS,
            )

            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
            )

            result = response.choices[0].message.content.strip()

            # Log actual token usage for quota monitoring
            usage = getattr(response, "usage", None)
            if usage:
                log.info(
                    "Token usage: prompt=%d  completion=%d  total=%d",
                    usage.prompt_tokens, usage.completion_tokens, usage.total_tokens,
                )
            log.info("LLM response received (%d chars)", len(result))

            return result

        except AuthenticationError as exc:
            # Invalid API key — no retry, it won't fix itself
            log.error("Groq authentication failed: %s", exc)
            raise RuntimeError(
                "Groq authentication failed. Check your GROQ_API_KEY in .env."
            ) from exc

        except RateLimitError as exc:
            # The in-pipeline RateLimiter (Phase 6C) should prevent reaching here.
            # If we do hit Groq's server-side limit, report it clearly.
            log.warning("Groq server-side rate limit hit (attempt %d): %s", attempt, exc)
            raise RuntimeError(
                "The Groq API rate limit was reached. "
                "The in-app quota guard should have prevented this — "
                "please wait a moment and try again."
            ) from exc

        except APIStatusError as exc:
            # 5xx server errors are transient — retry with backoff
            if exc.status_code and exc.status_code >= 500:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    delay = RETRY_DELAYS[attempt - 1]
                    log.warning(
                        "Groq server error %d (attempt %d/%d). Retrying in %ds...",
                        exc.status_code, attempt, MAX_RETRIES, delay,
                    )
                    time.sleep(delay)
                    continue
                else:
                    log.error(
                        "Groq server error %d — all %d attempts exhausted.",
                        exc.status_code, MAX_RETRIES,
                    )
                    raise RuntimeError(
                        f"Groq API returned server error {exc.status_code} "
                        f"after {MAX_RETRIES} attempts. Please try again later."
                    ) from exc
            # 4xx client errors (other than auth/rate-limit) — no retry
            log.error("Groq API client error %d: %s", exc.status_code, exc)
            raise RuntimeError(f"Groq API error {exc.status_code}: {exc}") from exc

        except Exception as exc:
            # Network errors, timeouts, etc. — retry
            last_exc = exc
            if attempt < MAX_RETRIES:
                delay = RETRY_DELAYS[attempt - 1]
                log.warning(
                    "Unexpected error (attempt %d/%d): %s. Retrying in %ds...",
                    attempt, MAX_RETRIES, exc, delay,
                )
                time.sleep(delay)
                continue
            log.error("LLM call failed after %d attempts: %s", MAX_RETRIES, exc)
            raise RuntimeError(
                f"LLM call failed after {MAX_RETRIES} attempts: {exc}"
            ) from exc

    # Should not reach here, but satisfy type checker
    raise RuntimeError(f"LLM call failed: {last_exc}")


# ══════════════════════════════════════════════════════════════════════════════
# SELF-TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    import sys

    api_key = os.getenv("GROQ_API_KEY")

    print()
    print("LLM CALLER SELF-TEST")
    print("=" * 60)

    if not api_key:
        print("  [SKIP] GROQ_API_KEY not set in .env")
        print("         Set the key and re-run this file to do a live test.")
        print("=" * 60)
        sys.exit(0)

    # Live test with a minimal probe prompt
    probe = (
        "You are a facts-only assistant. "
        "Reply with exactly: 'LLM connection verified.' "
        "Nothing else."
    )

    print(f"  Model      : {MODEL_NAME}")
    print(f"  Max tokens : {MAX_TOKENS}")
    print(f"  Retries    : {MAX_RETRIES}")
    print()

    try:
        result = call_llm(probe)
        print(f"  Response   : {result!r}")
        verified = "verified" in result.lower()
        print(f"  [{'PASS' if verified else 'WARN'}] Live Groq call {'succeeded' if verified else 'returned unexpected text'}.")
    except RuntimeError as e:
        print(f"  [FAIL] {e}")

    print("=" * 60)
