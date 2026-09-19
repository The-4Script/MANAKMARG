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
import re
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
# large-v3 is the primary model: it has a measurably lower word-error-rate than the turbo build, especially on
# non-English and code-switched (Hindi/English) speech, which is the common case for this assistant's voice
# questions. Turbo is the fast fallback so one failed call doesn't fail the whole request.
TRANSCRIPTION_MODEL = "whisper-large-v3"
TRANSCRIPTION_FALLBACK_MODEL = "whisper-large-v3-turbo"
# Whisper's optional "prompt" field biases the decoder's spelling/word choice toward the given vocabulary — it
# cannot add facts that were not spoken, only nudge ambiguous audio toward known terms. Kept short (well under
# Whisper's ~224-token prompt window) so every term still gets meaningful weight, and mixes scripts because the
# audio itself is often Hindi/English code-switched. Override with MANAKMARG_GROQ_TRANSCRIPTION_PROMPT.
TRANSCRIPTION_PROMPT = (
    "BIS compliance questions. Terms: BIS, ISI, hallmarking, QCO, HSN, LIMS, AHC, IS 2062, IS 1500, Scheme I, "
    "Scheme II, Scheme IV, Scheme X, compulsory registration, upcoming QCOs, gap analysis, stainless steel, "
    "Jaipur, Kolkata, Mumbai, Chennai, Hyderabad, Ahmedabad, Ghaziabad, Lucknow, Surat. "
    "भारतीय मानक ब्यूरो, आईएसआई, हॉलमार्किंग, अनिवार्य प्रमाणन, जयपुर, कोलकाता।"
)
MAX_QUERY_CHARS = 500
CACHE_SIZE = 256
TRANSCRIPT_LIMIT = 1000
# Standard Whisper hallucination heuristic: a segment reporting both a high probability of no speech and a poor
# average log-probability means the model invented words over silence or noise rather than transcribing anything.
SILENCE_NO_SPEECH_PROB = 0.6
SILENCE_AVG_LOGPROB = -1.0
# The other common Whisper failure mode on noisy/silent audio: looping the same short phrase over and over.
_REPEATED_PHRASE = re.compile(r"\b(\w+(?:\s+\w+){0,4})\b(?:\s+\1\b){3,}", re.IGNORECASE)

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Extract routing hints for a BIS compliance assistant. Return JSON only with keys: intent, material, "
    "product, application, confidence. intent must be one of gap_analysis, hallmarking, lab_search, "
    "upcoming_qco, tests_required, certification_process, compulsory_status, applicable_standard, "
    "product_compliance, general_question. Use null when unknown. Never create IS numbers, QCOs, legal facts, "
    "or locations. Canonical material/product values should be ordinary English words."
)


_INTERPRET_PROMPT = (
    "You restate questions for a search engine over Bureau of Indian Standards (BIS) records, which are written in "
    "English. The user may write in Hindi (Devanagari), romanised Hindi, another Indian language or English, and the "
    "text may come from speech-to-text with misheard words: similar sounds are confused and a word may be merged with a "
    "following postposition (\"geeka\" is \"ghee ka\"); restate what the user most plausibly meant. Return JSON only with keys: english, product, intent. "
    "english: the question restated as one short, plain English question. product: the product or material asked "
    "about, in the Indian English wording Indian Standard titles use (for example milk, ghee, paneer, groundnut oil "
    "rather than peanut oil, water storage tank, electric iron), without describing words the question does not "
    "need, or null. intent: one of applicable_standard, compulsory_status, certification_process, "
    "tests_required, lab_search, hallmarking, upcoming_qco, general_question, out_of_scope. Keep IS numbers, place "
    "names and other identifiers exactly as written. Never add IS numbers, dates, statuses or any fact that is not in "
    "the question."
)
INTERPRET_LIMIT = 300


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
        "interpretation_calls",
        "interpretation_cache_hits",
        "interpretation_failures",
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


def _cache_key(query: str, namespace: str = "") -> str:
    return hashlib.sha256(f"{namespace}{norm_match(query)}".encode("utf-8")).hexdigest()


def understand_query(query: str, settings: Settings) -> dict | None:
    """Routing hints for a query the local rules could not route; ``None`` without a key or on any failure.

    The larger model is tried first, then the faster one. A result (including a failure) is cached per normalised
    query, so the same question never costs a second call in this process.
    """
    return _json_completion(query, settings, prompt=_SYSTEM_PROMPT, counter="understanding", namespace="")


def interpret_query(query: str, settings: Settings) -> dict | None:
    """The question restated as plain English for retrieval (``english``, ``product``, ``intent``); ``None`` without a
    key or on any failure. Only the question text is sent. The caller validates the result against the records
    (``manakmarg.reasoning.interpret``): the model supplies wording, never facts."""
    result = _json_completion(query, settings, prompt=_INTERPRET_PROMPT, counter="interpretation", namespace="interpret:")
    if not result or not isinstance(result.get("english"), str) or not result["english"].strip():
        return None
    return {
        "english": result["english"].strip()[:INTERPRET_LIMIT],
        "product": result["product"].strip()[:120] if isinstance(result.get("product"), str) and result["product"].strip() else None,
        "intent": result.get("intent") if isinstance(result.get("intent"), str) else None,
    }


def _json_completion(query: str, settings: Settings, *, prompt: str, counter: str, namespace: str) -> dict | None:
    if not settings.groq_api_key:
        return None
    query = (query or "")[:MAX_QUERY_CHARS]
    key = _cache_key(query, namespace)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            USAGE.add(f"{counter}_cache_hits")
            return _cache[key]
    result = None
    for model in (settings.groq_reasoning_model or REASONING_MODEL, settings.groq_fast_model or FAST_MODEL):
        USAGE.add(f"{counter}_calls")
        started = time.monotonic()
        try:
            response = requests.post(
                f"{API_BASE}/chat/completions",
                headers=_headers(settings),
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": query}],
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
            log.info("groq %s ok model=%s ms=%d", counter, model, (time.monotonic() - started) * 1000)
            break
        except (requests.RequestException, GroqError, ValueError, KeyError, IndexError, TypeError) as exc:
            USAGE.add(f"{counter}_failures")
            log.warning("groq %s failed model=%s error=%s", counter, model, type(exc).__name__)
    with _cache_lock:
        _cache[key] = result
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return result


def _sounds_hallucinated(text: str, segments: object) -> bool:
    """True when the transcript looks invented rather than heard: every segment reads as silence/noise by the
    standard no-speech-probability heuristic, or the text is the classic same-phrase-on-a-loop failure."""
    rows = [row for row in segments if isinstance(row, dict)] if isinstance(segments, list) else []
    if rows and all(
        row.get("no_speech_prob", 0) > SILENCE_NO_SPEECH_PROB and row.get("avg_logprob", 0) < SILENCE_AVG_LOGPROB
        for row in rows
    ):
        return True
    return bool(_REPEATED_PHRASE.search(text))


def transcribe_audio(data: bytes, filename: str, content_type: str | None, settings: Settings, *, language: str | None = None) -> str:
    """Transcript of recorded speech (Whisper large-v3 first for accuracy, then the faster turbo model).

    ``language`` is ``"en"``, ``"hi"`` or ``None`` for automatic detection (best for mixed Hindi-English speech).
    A domain-vocabulary prompt is sent with every call to bias Whisper's spelling toward BIS/standards terms and
    common city names (it cannot introduce words that were not spoken). A result that looks hallucinated (silence
    or noise transcribed as text, or a looping phrase) is treated as no speech rather than returned as-is.
    Raises ``GroqUnavailable`` without a key and ``GroqError`` when every model fails outright.
    """
    if not settings.groq_api_key:
        raise GroqUnavailable("voice transcription is not configured")
    prompt = settings.groq_transcription_prompt if settings.groq_transcription_prompt is not None else TRANSCRIPTION_PROMPT
    last: GroqError | None = None
    saw_hallucination = False
    for model in (settings.groq_transcription_model or TRANSCRIPTION_MODEL, settings.groq_transcription_fallback_model or TRANSCRIPTION_FALLBACK_MODEL):
        USAGE.add("transcription_calls")
        fields = {"model": model, "temperature": "0", "response_format": "verbose_json"}
        if language:
            fields["language"] = language
        if prompt:
            fields["prompt"] = prompt
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
            body = response.json()
            text = body.get("text")
            if not isinstance(text, str):
                raise GroqError("bad_response", "transcription response had no text")
            text = text.strip()
            if text and _sounds_hallucinated(text, body.get("segments")):
                saw_hallucination = True
                log.info("groq transcription looked hallucinated model=%s", model)
                continue
            return text[:TRANSCRIPT_LIMIT]
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
    if saw_hallucination:
        return ""
    raise last or GroqError("upstream", "transcription failed")


def transcribe(path: str | Path, settings: Settings) -> str | None:
    """Compatibility wrapper: transcript of an audio file, or ``None`` when unavailable or failed."""
    try:
        return transcribe_audio(Path(path).read_bytes(), Path(path).name, None, settings)
    except (GroqUnavailable, GroqError, OSError):
        return None
