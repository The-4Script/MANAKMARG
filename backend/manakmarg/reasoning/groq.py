"""Optional Groq query understanding and transcription with a strict local fallback."""

import json
from pathlib import Path

from manakmarg.core.config import Settings

REASONING_MODEL = "openai/gpt-oss-120b"
FAST_MODEL = "openai/gpt-oss-20b"
TRANSCRIPTION_MODEL = "whisper-large-v3-turbo"
TRANSCRIPTION_FALLBACK_MODEL = "whisper-large-v3"


def _client(settings: Settings):
    if not settings.groq_api_key:
        return None
    try:
        from groq import Groq
    except ImportError:
        return None
    return Groq(api_key=settings.groq_api_key)


def understand_query(query: str, settings: Settings) -> dict | None:
    """Use 120B first for ambiguous queries, then 20B on provider/model failure."""
    client = _client(settings)
    if client is None:
        return None
    system = (
        "Extract routing hints for a BIS compliance assistant. Return JSON only with keys: intent, material, "
        "product, application, confidence. intent must be one of gap_analysis, hallmarking, lab_search, "
        "upcoming_qco, tests_required, certification_process, compulsory_status, applicable_standard, "
        "product_compliance, general_question. Use null when unknown. Never create IS numbers, QCOs, legal facts, "
        "or locations. Canonical material/product values should be ordinary English words."
    )
    for model in (settings.groq_reasoning_model or REASONING_MODEL, settings.groq_fast_model or FAST_MODEL):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": query}],
                temperature=0,
                max_completion_tokens=256,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            result = json.loads(content)
            return result if isinstance(result, dict) else None
        except Exception:
            continue
    return None


def transcribe(path: str | Path, settings: Settings) -> str | None:
    """Try the faster Whisper model first and fall back to the larger model."""
    client = _client(settings)
    if client is None:
        return None
    filename = str(path)
    for model in (settings.groq_transcription_model or TRANSCRIPTION_MODEL, settings.groq_transcription_fallback_model or TRANSCRIPTION_FALLBACK_MODEL):
        try:
            with open(filename, "rb") as audio:
                result = client.audio.transcriptions.create(file=(filename, audio.read()), model=model, temperature=0, response_format="verbose_json")
            return result.text
        except Exception:
            continue
    return None