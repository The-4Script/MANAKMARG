# AI Assistant Architecture

MANAK MARG answers from its own database with deterministic rules. Language models are an optional, bounded helper —
never the database, the search engine or the regulatory authority.

> Deterministic where facts are known. Retrieval where information must be found. AI only where language
> understanding genuinely benefits.

## Pipeline

```text
typed question ─┐
                ├─> local normalisation (Hindi/Hinglish aliases, entities: material / product / application / place)
voice ─> Whisper┘        -> deterministic router (reasoning/routing.py, explainable reason on every answer)
                         -> local services: IS resolution, listings + QCOs, schemes, Product Manuals/SIT, labs,
                            hallmarking/AHCs, HSN lookup, FAQs/documents (SQLite FTS5 + LSA listing vectors)
                         -> applicability rules and evidence builder
                         -> EN/HI template answer with evidence ids and official-source links
```

Voice input is only speech-to-text. The transcript is asked through the same `/api/assistant/query` call as typed
text, so it gets exactly the same answer path.

## When an external model is called

| Situation | External call |
|---|---|
| IS number, listing/QCO, scheme, certification steps, labs, hallmarking/AHCs, upcoming QCOs, gap analysis, invalid IS number, unknown place | **Never** |
| HSN lookup (code or product words) | **Never** — local FTS5 over `hsn_code` |
| Clearly out-of-scope question (no BIS cue, identifier, place or listed product) | **Never** |
| A repeated question | **Never** — in-process cache (256 entries) |
| An in-scope question that no local rule can route (general/unroutable) | At most one routing-hint request (larger model, then the faster model on failure) |
| Voice recording | One transcription request (`whisper-large-v3-turbo`, then `whisper-large-v3` on failure) |

A routing-hint request carries only the user's question (≤ 500 characters) and a fixed instruction — never database
rows, datasets or documents. The reply is allow-listed (`apply_model_hints`): only known intents and canonical
material/product/application values are accepted, identifiers and facts cannot be introduced, and the result goes back
through the same local router. Any timeout, rate limit or invalid reply falls back to the deterministic answer.

Calls use Groq's OpenAI-compatible HTTP API through `requests` with explicit timeouts
(`MANAKMARG_GROQ_TIMEOUT_S`, `MANAKMARG_GROQ_TRANSCRIPTION_TIMEOUT_S`); no SDK is required.

## Observability

`GET /api/meta` returns `voice_enabled` and `ai_usage` counters since process start: `understanding_calls`,
`understanding_cache_hits`, `understanding_failures`, `understanding_not_needed` (questions answered with no model),
`transcription_calls`, `transcription_failures`. Counters hold no query text, audio or credentials; logs record only
the model name, status and latency.

## Voice endpoint

`POST /api/voice/transcribe` (multipart: `file`, `language` = `auto` | `en` | `hi`)

* 503 when `GROQ_API_KEY` is not configured; 415 unsupported format (WebM, Ogg, WAV, MP3, M4A, FLAC accepted);
  400 empty/too short; 413 over `MANAKMARG_VOICE_MAX_MB`; 429 over `MANAKMARG_VOICE_REQUESTS_PER_MINUTE` per client or
  when Groq rate-limits; 504 timeout; 502 other upstream failure; 422 no speech recognised.
* Audio is held in memory for that request only, never stored or logged. `auto` lets Whisper detect the language,
  which suits mixed Hindi-English speech.

## What always stays deterministic

- IS/QCO/scheme/laboratory/AHC/HSN resolution and every legal-status decision
- FTS5, vector retrieval, entity constraints, applicability and evidence ids
- Dates, locations, source links, access-control handling and response templates

## Privacy and security

API keys are read from the server environment only (`GROQ_API_KEY`), never sent to the frontend, never logged and
never returned in errors. Uploaded gap-analysis documents and the BIS/HSN corpora are never sent to any model.
