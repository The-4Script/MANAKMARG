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

## Model recommendation

No neural model is required for the current success criteria. A transparent alias and intent classifier is faster,
smaller, testable offline and easier to audit for regulatory answers. A CNN has no useful advantage for this short-text
classification problem and is not used.

An optional future model may rerank or parse only low-confidence queries after local candidate filtering. It must return
structured entities, receive no full BIS corpus or private documents, and never decide legal status. Its output must be
validated against the same local resolvers. The application must continue normally when no API key, network or model is
available.

## What remains deterministic

- IS/QCO/scheme/laboratory/AHC resolution and all legal status decisions
- FTS5, vector retrieval, applicability, contradiction handling and evidence IDs
- Dates, locations, source links, document access controls and response templates
- Out-of-scope refusal and clarification behavior

## Resource and performance expectations

The local layer adds only regular-expression, token and dictionary work: no model download, GPU or persistent external
service. Its memory and startup impact is negligible relative to the existing SQLite and index loading. Normal query
latency remains bounded by the existing retrieval path. External API calls are zero by default and are not needed for
the demo flows.

## Privacy and security

No user query, uploaded document or BIS corpus is sent externally by this layer. If an optional provider is added,
the integration must explicitly redact private documents, send only retrieved public context, keep credentials server-side,
and fail closed to the deterministic path. API keys belong in deployment secrets, never frontend code or source control.
