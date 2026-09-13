# Architecture

MANAK MARG is a modular monolith: one Python package (`backend/manakmarg`) and one single-page app (`frontend/`).
The guiding rule is **evidence first**: facts come from official records with provenance; rules — not similarity
scores and not an LLM — decide legal status, dates and eligibility.

```
 React SPA (frontend/)  Navigator · Assistant · Journey · Standards · Certification & QCOs · Labs · Hallmarking
                        · Gap Analysis · Sources & Data Health          (EN / हिंदी, evidence drawer everywhere)
            │ JSON over /api
 ┌──────────┴───────────────────────────────── backend/manakmarg ─────────────────────────────────────────────┐
 │ api/        FastAPI routers: meta & sources · compliance (search, standards, listings, QCOs, assess, journey,│
 │             FAQ) · labs & hallmarking · assistant · documents                                              │
 │ reasoning/  intents · applicability · journey · labs · hallmarking · evidence · i18n templates · assistant │
 │ documents/  private upload store (TTL) · extraction · units · requirement/value extraction · comparison    │
 │ search/     resolvers (IS designations) · FTS5 BM25 · LSA vectors · curated synonyms · hybrid matcher      │
 │ ingest/     source registry · polite fetcher & cache · parsers per source · loaders · pipeline · quality    │
 │ normalize/  IS designations · dates · text · geography · listing-status rules · order references          │
 │ db/         SQLAlchemy Core schema (provenance on every domain row) · SQLite engine · FTS5                 │
 │ core/       settings · paths · injectable clock                                                           │
 └──────────────────────────────────────────────────────────────────────────────────────────────────────────┘
   data/*.xlsx (supplied, read-only) · data/raw/web (HTML/PDF cache) · data/processed/manakmarg.sqlite3
   data/indexes (LSA vectors) · data/manifests (sources.json, data_inventory.json, data_quality.json) · data/uploads (TTL)
```

## Data flow for a question

1. **Understand** (`reasoning/intents.py`): rule-based intent and entities — IS designations, AHC recognition numbers,
   S.O. numbers, state (English, abbreviations, Hindi names), district/city from a gazetteer built from official
   records, metal, and the remaining product words.
2. **Resolve and retrieve** (`search/`): identifiers resolve deterministically to published standards with an
   explicit resolution kind; product words are matched to official listing names through FTS5 BM25, LSA vectors and
   curated synonyms. Scores only order candidates.
3. **Decide** (`reasoning/applicability.py`, `labs.py`, `hallmarking.py`): applicability label, compulsory effect
   (with dates computed against the clock), laboratory status, AHC operability and district coverage by explicit
   rules over the stored official facts.
4. **Assemble evidence** (`reasoning/evidence.py`): every record used becomes an evidence item (source, authority,
   official URL, locator, retrieval time, ≤ 300-character snippet); every answer sentence cites evidence ids.
5. **Compose** (`reasoning/assistant.py`, `i18n.py`, `journey.py`): deterministic EN/HI templates word the result,
   with caveats, next actions, follow-up questions and links into the relevant pages.

## Key decisions

| Decision | Why |
|---|---|
| SQLite 3.50 with FTS5 via SQLAlchemy Core; schema portable to PostgreSQL | Self-contained, demo-safe prototype with no server; the same metadata can target PostgreSQL. |
| Structured-first hybrid retrieval (identifiers → SQL → BM25 → LSA → synonyms) | Standards, QCOs and dates are identifiers and facts; a vector store alone would blur them. |
| Deterministic reasoning; optional LLM only for wording, behind identifier and citation checks | Compliance answers must never contain invented requirements or statuses. |
| Snapshot ingestion with hashed upserts and `is_current` retirement | Re-runs show inserted/updated/unchanged/retired counts; history is kept, nothing is silently deleted. |
| Derived states (AHC operability, lab validity, upcoming effect) computed at query time | They depend on "today"; the stored data keeps only official statuses and dates. |
| Organisation contacts stored, contact-person names not | Privacy by minimisation. |
| Uploads in per-session folders with TTL, validated by type, magic bytes and size, never logged | Business documents are sensitive. |

## Repository layout

See the README table of documents. Tests mirror the package layout under `backend/tests/`; parser tests use trimmed
real snapshots in `backend/tests/fixtures/bis/`.
