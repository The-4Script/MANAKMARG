"""Optional Groq calls: bounded query understanding and speech transcription. Local first, fail closed.

* Nothing here is needed for deterministic answers; every function returns ``None`` (or raises ``GroqUnavailable``)
  when ``GROQ_API_KEY`` is not configured.
* Only the user's own short query or recorded audio is sent — never datasets, database rows or documents.
* Calls use Groq's OpenAI-compatible HTTP API with explicit timeouts (no SDK needed), a model cascade, and a small
  in-process cache so a repeated query never triggers a second call.
* Usage counters record how many calls were made, cached, skipped or failed. They hold no query text and no secrets.
"""

import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from pathlib import Path

import requests

from manakmarg.core.config import Settings
from manakmarg.normalize.text import norm_match

API_BASE = "https://api.groq.com/openai/v1"
REASONING_MODEL = "openai/gpt-oss-120b"
FAST_MODEL = "openai/gpt-oss-20b"
TRANSCRIPTION_MODEL = "whisper-large-v3-turbo"
TRANSCRIPTION_FALLBACK_MODEL = "whisper-large-v3"
MAX_QUERY_CHARS = 500
CACHE_SIZE = 256
TRANSCRIPT_LIMIT = 1000

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Extract routing hints for a BIS compliance assistant. Return JSON only with keys: intent, material, "
    "product, application, confidence. intent must be one of gap_analysis, hallmarking, lab_search, "
    "upcoming_qco, tests_required, certification_process, compulsory_status, applicable_standard, "
    "product_compliance, general_question. Use null when unknown. Never create IS numbers, QCOs, legal facts, "
    "or locations. Canonical material/product values should be ordinary English words."
)


class GroqUnavailable(Exception):
    """No Groq API key is configured on the server."""


class GroqError(Exception):
    """A Groq call failed. ``kind`` is one of: timeout, rate_limited, upstream, bad_response."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class _Usage:
    FIELDS = (
        "understanding_calls",
        "understanding_cache_hits",
        "understanding_failures",
        "understanding_not_needed",
        "transcription_calls",
        "transcription_failures",
    )

    def __init__(self):
        self._lock = threading.Lock()
        self._counts = dict.fromkeys(self.FIELDS, 0)

    def add(self, field: str, amount: int = 1) -> None:
        with self._lock:
            self._counts[field] += amount

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def reset(self) -> None:
        with self._lock:
            self._counts = dict.fromkeys(self.FIELDS, 0)


USAGE = _Usage()
_cache: OrderedDict[str, dict | None] = OrderedDict()
_cache_lock = threading.Lock()


def usage_snapshot() -> dict[str, int]:
    return USAGE.snapshot()


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _headers(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.groq_api_key}"}


def _cache_key(query: str) -> str:
    return hashlib.sha256(norm_match(query).encode("utf-8")).hexdigest()


def understand_query(query: str, settings: Settings) -> dict | None:
    """Routing hints for a query the local rules could not route; ``None`` without a key or on any failure.

    The larger model is tried first, then the faster one. A result (including a failure) is cached per normalised
    query, so the same question never costs a second call in this process.
    """
    if not settings.groq_api_key:
        return None
    query = (query or "")[:MAX_QUERY_CHARS]
    key = _cache_key(query)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            USAGE.add("understanding_cache_hits")
            return _cache[key]
    result = None
    for model in (settings.groq_reasoning_model or REASONING_MODEL, settings.groq_fast_model or FAST_MODEL):
        USAGE.add("understanding_calls")
        started = time.monotonic()
        try:
            response = requests.post(
                f"{API_BASE}/chat/completions",
                headers=_headers(settings),
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": query}],
                    "temperature": 0,
                    "max_completion_tokens": 256,
                    "response_format": {"type": "json_object"},
                },
                timeout=settings.groq_timeout_s,
            )
            if response.status_code != 200:
                raise GroqError("rate_limited" if response.status_code == 429 else "upstream", f"HTTP {response.status_code}")
            content = response.json()["choices"][0]["message"]["content"] or "{}"
            parsed = json.loads(content)
            result = parsed if isinstance(parsed, dict) else None
            log.info("groq understanding ok model=%s ms=%d", model, (time.monotonic() - started) * 1000)
            break
        except (requests.RequestException, GroqError, ValueError, KeyError, IndexError, TypeError) as exc:
            USAGE.add("understanding_failures")
            log.warning("groq understanding failed model=%s error=%s", model, type(exc).__name__)
    with _cache_lock:
        _cache[key] = result
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return result


def transcribe_audio(data: bytes, filename: str, content_type: str | None, settings: Settings, *, language: str | None = None) -> str:
    """Transcript of recorded speech (Whisper turbo first, then the larger model).

    ``language`` is ``"en"``, ``"hi"`` or ``None`` for automatic detection (best for mixed Hindi-English speech).
    Raises ``GroqUnavailable`` without a key and ``GroqError`` when both models fail.
    """
    if not settings.groq_api_key:
        raise GroqUnavailable("voice transcription is not configured")
    last: GroqError | None = None
    for model in (settings.groq_transcription_model or TRANSCRIPTION_MODEL, settings.groq_transcription_fallback_model or TRANSCRIPTION_FALLBACK_MODEL):
        USAGE.add("transcription_calls")
        fields = {"model": model, "temperature": "0", "response_format": "json"}
        if language:
            fields["language"] = language
        try:
            response = requests.post(
                f"{API_BASE}/audio/transcriptions",
                headers=_headers(settings),
                data=fields,
                files={"file": (filename, data, content_type or "application/octet-stream")},
                timeout=settings.groq_transcription_timeout_s,
            )
            if response.status_code == 429:
                raise GroqError("rate_limited", "transcription rate limit reached")
            if response.status_code != 200:
                raise GroqError("upstream", f"transcription failed (HTTP {response.status_code})")
            text = response.json().get("text")
            if not isinstance(text, str):
                raise GroqError("bad_response", "transcription response had no text")
            return text.strip()[:TRANSCRIPT_LIMIT]
        except requests.Timeout:
            last = GroqError("timeout", "transcription timed out")
        except requests.RequestException:
            last = GroqError("upstream", "transcription service unreachable")
        except ValueError:
            last = GroqError("bad_response", "transcription response was not JSON")
        except GroqError as exc:
            last = exc
        USAGE.add("transcription_failures")
        log.warning("groq transcription failed model=%s kind=%s", model, last.kind)
    raise last or GroqError("upstream", "transcription failed")


def transcribe(path: str | Path, settings: Settings) -> str | None:
    """Compatibility wrapper: transcript of an audio file, or ``None`` when unavailable or failed."""
    try:
        return transcribe_audio(Path(path).read_bytes(), Path(path).name, None, settings)
    except (GroqUnavailable, GroqError, OSError):
        return None
