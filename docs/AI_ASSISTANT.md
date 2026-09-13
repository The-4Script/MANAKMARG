# AI Assistant Architecture

MANAK MARG uses a local query-understanding layer on top of the existing BIS database, FTS/vector retrieval,
applicability rules and evidence builder. The goal is correct routing and entity constraints, not an LLM-generated
replacement for the knowledge base.

## Pipeline

```text
query
  -> local normalization and bilingual alias resolution
  -> intent, standard, location, material, product and application entities
  -> scope and ambiguity checks
  -> existing deterministic service (standards, QCO, labs, hallmarking, FAQ or documents)
  -> existing FTS/vector retrieval and applicability/reranking
  -> evidence-backed template response
```

The parser supports English, Hindi and common Hinglish terms. It distinguishes material from product, for example
`copper wire` becomes material `copper` and product `wire`. A material-only request receives a clarification instead
of an arbitrary standard. Clearly unrelated questions are rejected before FAQ or standards retrieval.

## Model policy

The local alias and intent classifier remains the first path because it is faster, testable offline and easier to audit
for regulatory answers. A CNN has no useful advantage for this short-text classification problem and is not used.

When a query is genuinely ambiguous and Groq is configured, the server uses only the supplied models:

1. `openai/gpt-oss-120b` for the best structured routing attempt.
2. `openai/gpt-oss-20b` if the first model fails, times out, hits a limit or returns invalid JSON.

For audio, it uses `whisper-large-v3-turbo` first and `whisper-large-v3` as the transcription fallback. These calls are
never needed for ordinary deterministic queries. Models return only routing/entity hints; they cannot create IS numbers,
QCOs, legal status or evidence. Output is allow-listed and passed through local resolvers. The application continues
normally when no key, network, SDK or model is available.

## What remains deterministic

- IS/QCO/scheme/laboratory/AHC resolution and all legal status decisions
- FTS5, vector retrieval, applicability, contradiction handling and evidence IDs
- Dates, locations, source links, document access controls and response templates
- Out-of-scope refusal and clarification behavior

## Resource and performance expectations

The local layer adds only regular-expression, token and dictionary work: no model download, GPU or persistent external
service. Its memory and startup impact is negligible relative to the existing SQLite and index loading. Normal query
latency remains bounded by the existing retrieval path. External API calls are zero for clear queries and limited to one
request plus one fallback for ambiguous text or audio.

## Privacy and security

No uploaded document or BIS corpus is sent externally by this layer. Only an ambiguous user query or explicitly requested
audio is sent to Groq. Credentials stay server-side and the cascade fails closed to the deterministic path. API keys
belong in deployment secrets, never frontend code or source control.
