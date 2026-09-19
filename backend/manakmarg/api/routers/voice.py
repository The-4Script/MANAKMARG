"""Voice input: speech → text only. The transcript is then asked through the normal assistant endpoint, so voice
questions get exactly the same deterministic, evidence-backed answers as typed ones.

Audio is held in memory for the single transcription request, sent only to the configured transcription service,
never stored and never logged.
"""

import threading
import time
from collections import defaultdict, deque
from pathlib import PurePath

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool

from manakmarg.reasoning import groq

from ..deps import get_state

router = APIRouter(prefix="/voice", tags=["voice"])

AUDIO_TYPES = {
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".mpeg": "audio/mpeg",
    ".mpga": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".flac": "audio/flac",
}
_EXTENSION_BY_TYPE = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav", "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "audio/flac": ".flac"}
MIN_AUDIO_BYTES = 1024
LANGUAGES = {"auto": None, "en": "en", "hi": "hi"}


class _RateLimiter:
    """Sliding one-minute window per client address; enough to stop accidental loops or abuse of the paid API."""

    def __init__(self):
        self._lock = threading.Lock()
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, client: str, limit: int, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits[client]
            while hits and now - hits[0] > 60:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


LIMITER = _RateLimiter()


def _audio_type(upload: UploadFile) -> tuple[str, str]:
    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    extension = PurePath(upload.filename or "").suffix.lower()
    if extension not in AUDIO_TYPES:
        extension = _EXTENSION_BY_TYPE.get(content_type, "")
    if extension not in AUDIO_TYPES:
        raise HTTPException(415, "Unsupported audio format. Use WebM, Ogg, WAV, MP3, M4A or FLAC.")
    return f"voice{extension}", AUDIO_TYPES[extension]


@router.post("/transcribe")
async def transcribe(request: Request, file: UploadFile = File(...), language: str = Form("auto")) -> dict:
    settings = get_state().settings
    if not settings.voice_enabled:
        raise HTTPException(503, "Voice input is not configured on this server.")
    if language not in LANGUAGES:
        raise HTTPException(422, "language must be one of: auto, en, hi.")
    client = request.client.host if request.client else "unknown"
    if not LIMITER.allow(client, settings.voice_requests_per_minute):
        raise HTTPException(429, "Too many voice requests. Please wait a minute and try again.")
    filename, content_type = _audio_type(file)
    limit = settings.voice_max_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"The recording is larger than {settings.voice_max_mb} MB. Please record a shorter question.")
    if len(data) < MIN_AUDIO_BYTES:
        raise HTTPException(400, "The recording is empty or too short.")
    try:
        text = await run_in_threadpool(groq.transcribe_audio, data, filename, content_type, settings, language=LANGUAGES[language])
    except groq.GroqUnavailable:
        raise HTTPException(503, "Voice input is not configured on this server.") from None
    except groq.GroqError as exc:
        status = {"timeout": 504, "rate_limited": 429}.get(exc.kind, 502)
        raise HTTPException(status, "Speech could not be transcribed right now. Please try again or type your question.") from None
    if not text:
        raise HTTPException(422, "No speech was recognised. Please speak clearly and try again.")
    return {"text": text, "language": language}
