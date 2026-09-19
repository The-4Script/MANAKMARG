# AI Assistant Architecture

MANAK MARG answers from its own database with deterministic rules. Language models are an optional, bounded helper —
never the database, the search engine or the regulatory authority.

> Deterministic where facts are known. Retrieval where information must be found. AI only where language
> understanding genuinely benefits.

## Pipeline

```text
typed question ─┐
                ├─> local normalisation (Hindi/Hinglish aliases + product lexicon, entities, places, "IS" = standard)
voice ─> Whisper┘        -> deterministic router (reasoning/routing.py, explainable reason on every answer)
                         -> interpretation, only if words remain that no English record matches:
                            sound-alike recovery (offline), then a guarded English restatement by the model
                         -> local services: IS resolution, listings + QCOs, schemes, Product Manuals/SIT, labs,
                            hallmarking/AHCs, HSN lookup, FAQs/documents (SQLite FTS5 + LSA listing vectors)
                         -> applicability rules and evidence builder
                         -> EN/HI template answer with evidence ids and official-source links
```

Voice input is only speech-to-text. The transcript is asked through the same `/api/assistant/query` call as typed
text, so it gets exactly the same answer path.

## Interpreting the question (any language, typed or spoken)

The records (standards catalogue, listings, FAQs, lab scopes) are English. A question is turned into record terms in
layers, cheapest first (`reasoning/interpret.py`):

1. **Lexicon** (`normalize/lexicon.py`, offline): Hindi and romanised Hindi names of everyday goods → the words BIS
   titles use ("दूध"/"dudh" → milk, "दही" → dahi, "पानी की टंकी" → water storage tank). का/के/की forms of a phrase and
   chandrabindu/nukta spellings match automatically. "IS" without a number ("दूध का IS क्या है") asks for the standard.
2. **Sound-alike recovery** (`normalize/phonetic.py`, offline): a word no record matches is compared by sound with the
   lexicon, ignoring what speech-to-text typically gets wrong — aspiration, retroflex/dental consonants, vowel length,
   a stray "s" and a merged postposition ("geeka"/"गीका" → ghee, "डूद्स" → milk). Only unambiguous matches are used.
3. **Model restatement** (`groq.interpret_query`, only with `GROQ_API_KEY`): if unmatched words remain in a
   non-English or in-scope question, the model restates it as one short English question plus the product name
   ("दुधाचा IS काय आहे" → "What is the IS for milk?"). The restatement is accepted only if it passes validation:
   IS numbers the user did not write are removed; every product word must exist in the record vocabulary; the result
   must route in scope. The answer shows it ("Searched as: …") and stays in the language of the question.

"Which standard / what is the IS for X" is answered from the whole published catalogue (`search/catalogue.py`),
ranked so the standard whose subject *is* the product comes first ("Packaged Pasteurized Milk" before "Milk Boiler",
product specifications before test methods, "Groundnut oil" before "Groundnut oil for cosmetic industry"). A
compulsory listing stays the answer only when it is about the product itself; a listing that merely mentions it
("Square Tins … for Ghee") is shown as such.

### Hindi answers

A question in Hindi is answered in Hindi. The answer's own wording comes from the Hindi templates (`reasoning/i18n.py`);
the official English passages quoted in it — FAQ questions and answers, application steps, document excerpts, scheme
descriptions — are translated in one batched request per answer (`groq.translate_to_hindi`, cached per passage) and
checked before use (`reasoning/localize.py`): every number and amount, IS / S.O. / G.S.R. number, URL and e-mail must
appear unchanged and the text must be Hindi, otherwise the official English is shown. Names stay as the records write
them (IS numbers, standard and product titles, QCO names, laboratories, AHCs). The evidence drawer keeps the official
English text and the answer carries the `machine_translation` note. Without a key the passages stay in English.

### Keeping it from regressing

`python -m manakmarg eval-queries [--with-model]` scores the multilingual question set in `manakmarg/eval/queries.json`
against the real database (route reached and IS numbers named) and exits non-zero below `--min-accuracy` (default
1.0). Whenever a phrasing is misread, add it there (and the word to the lexicon when it is a product name), then re-run.

## When an external model is called

| Situation | External call |
|---|---|
| IS number, listing/QCO, scheme, certification steps, labs, hallmarking/AHCs, upcoming QCOs, gap analysis, invalid IS number, unknown place | **Never** |
| HSN lookup (code or product words) | **Never** — local FTS5 over `hsn_code` |
| Clearly out-of-scope question (no BIS cue, identifier, place or listed product) | **Never** |
| A repeated question | **Never** — in-process cache (256 entries) |
| A question the lexicon and sound-alike recovery fully understand ("दूध का IS क्या है") | **Never** |
| Words no record matches remain, in a non-English or in-scope question | At most one restatement request (larger model, then the faster model on failure) |
| An in-scope question that no local rule can route (general/unroutable) | At most one routing-hint request (larger model, then the faster model on failure) |
| Hindi answer quoting official English passages (FAQs, steps, excerpts) | One batched translation request per answer; cached per passage, so a repeated answer costs nothing |
| Voice recording | One transcription request (`whisper-large-v3` for accuracy, then `whisper-large-v3-turbo` on failure), with a domain-vocabulary prompt |

A routing-hint request carries only the user's question (≤ 500 characters) and a fixed instruction — never database
rows, datasets or documents. The reply is allow-listed (`apply_model_hints`): only known intents and canonical
material/product/application values are accepted, identifiers and facts cannot be introduced, and the result goes back
through the same local router. Any timeout, rate limit or invalid reply falls back to the deterministic answer.

Calls use Groq's OpenAI-compatible HTTP API through `requests` with explicit timeouts
(`MANAKMARG_GROQ_TIMEOUT_S`, `MANAKMARG_GROQ_TRANSCRIPTION_TIMEOUT_S`); no SDK is required.

## Observability

`GET /api/meta` returns `voice_enabled` and `ai_usage` counters since process start: `understanding_calls`,
`understanding_cache_hits`, `understanding_failures`, `understanding_not_needed` (questions answered with no model),
`interpretation_calls`, `interpretation_cache_hits`, `interpretation_failures`, `translation_calls`,
`translation_cache_hits`, `translation_failures`, `transcription_calls`,
`transcription_failures`. Counters hold no query text, audio or credentials; logs record only
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
never returned in errors. Uploaded gap-analysis documents and the BIS/HSN databases are never sent to any model; the only
record text that leaves the server is the handful of public official passages quoted in a Hindi answer, for translation.
