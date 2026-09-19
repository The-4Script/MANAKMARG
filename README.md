# MANAK MARG — BIS Standards & Compliance Navigator

**Your path through Indian Standards & BIS compliance.** An independent, evidence-first prototype for
Smart India Hackathon 2026 (problem statement PS26107) by team ForgeScript. It is **not** an official
Bureau of Indian Standards (BIS) service; every answer links to the official record it comes from.

MANAK MARG answers the questions a manufacturer, importer, jeweller or consumer actually asks:

| Question | How it is answered |
|---|---|
| Which Indian Standard applies to my product, and why? | Hybrid product matching (identifiers, FTS5 BM25, LSA vectors, curated synonyms) over official compulsory-certification listings and the published-standards export; the match basis is shown. |
| Is certification compulsory? Under which QCO, scheme and enforcement date? | Deterministic status rules over BIS scheme pages and the upcoming-QCO page, with the quoted status basis, S.O./G.S.R. numbers and dates computed against today. |
| Which tests, sampling and grouping apply? | Parsed BIS Product Manuals (Scheme of Inspection and Testing, test equipment, scope of licence) with page numbers. |
| Which labs can test it near me? | LIMS IS-wise scope rows joined with lab directories and Group-1/2 list status; exclusions and remarks shown verbatim. |
| Is hallmarking mandatory in my district? Which AHCs are operative? | Phase-wise district list cross-checked against the Gazette annex; AHC operability from both Manakonline lists and validity dates. |
| Does my datasheet or test report meet the requirement? | Private gap analysis against limits written in a document you upload — requirements are never generated. |
| What is the HSN code for my product? | Local lookup (SQLite FTS5) over the supplied HSN master: exact codes, codes under a heading, or descriptions containing every product word — shown verbatim and separately from BIS answers, never as a GST/customs ruling. |
| Can I just ask by voice? | English, Hindi or mixed speech is transcribed (Groq Whisper, only when `GROQ_API_KEY` is set) and asked through exactly the same assistant pipeline as typed text. |

Answers are available in **English and हिंदी**; identifiers (IS numbers, S.O. numbers, recognition numbers,
clauses) are never translated.

## Quick start

Requirements: Python 3.12+ (built on 3.14), Node 20+ (built on 24). No database server is needed.

The repository ships a prebuilt data bundle (`deploy/data/manakmarg-data.tar.gz`: SQLite database, listing index
and manifests), so the demo runs without re-ingesting from BIS websites.

```bash
python -m venv .venv
.venv/bin/python -m pip install -e "backend[dev]"           # Windows: .venv\Scripts\python
cd frontend && npm ci && npm run build && cd ..
.venv/bin/python -m manakmarg import-data                   # restore the prebuilt database and index (seconds)
.venv/bin/python -m manakmarg serve --port 8000             # http://127.0.0.1:8000
```

Or with Docker: `docker build -t manakmarg . && docker run -p 7860:7860 manakmarg`.

**Deploying?** Read [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md): environment variables, data, Docker, free hosting,
CORS, health check and troubleshooting. To rebuild the data from official sources, run `manakmarg ingest` (polite
online ingestion, about 25 minutes). See [docs/SETUP.md](docs/SETUP.md) for development mode and
[docs/DEMO.md](docs/DEMO.md) for the four demonstration flows.

## What is indexed (ingestion of 13 Sep 2026)

| Data | Records |
|---|---:|
| Indian Standards (supplied BIS exports, 1.xlsx + 2.xlsx + 18 ministry exports) | 24,025 |
| Compulsory-certification listings (Scheme I, II, IV, X and upcoming QCOs) | 1,045 |
| QCOs, amendments and notifications linked to listings | 590 |
| Product Specific Guidelines (Product Manuals listed) / parsed for demo families | 1,645 / 11 |
| Laboratories (LIMS directories) / Group-1 and Group-2 list entries | 581 / 786 |
| LIMS IS-wise scope rows for 13 demo standard families (178,261 clause-wise charge items) | 1,576 |
| Assaying & Hallmarking Centres / suspension-cancellation events | 1,650 / 731 |
| Mandatory hallmarking districts (phase-wise list + 1 Gazette-only entry) | 393 |
| Official FAQs | 69 |

## Architecture in one paragraph

A modular monolith: `backend/manakmarg` contains source registry and polite fetcher (`ingest`), normalisation
(`normalize`), SQLite schema with provenance on every row (`db`), retrieval (`search`), deterministic reasoning
(`reasoning`), document gap analysis (`documents`) and a FastAPI API (`api`); `frontend/` is a React + TypeScript +
Vite + Tailwind SPA served by the API after build. Legal status, dates and eligibility are decided by rules over
official records — never by similarity scores or an LLM. Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Documentation

| Document | Contents |
|---|---|
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Components, data flow, decisions |
| [DATA_MODEL](docs/DATA_MODEL.md) | Tables, keys, provenance, derived status |
| [DATA_SOURCES](docs/DATA_SOURCES.md) · [DATA_INVENTORY](docs/DATA_INVENTORY.md) · [DATA_QUALITY](docs/DATA_QUALITY.md) | What was used, how it was profiled, what the checks found |
| [INGESTION](docs/INGESTION.md) | Pipeline steps, runs, caching, offline replay, access handling |
| [RETRIEVAL_AND_REASONING](docs/RETRIEVAL_AND_REASONING.md) · [COMPLIANCE_LOGIC](docs/COMPLIANCE_LOGIC.md) | Matching, labels, status rules, journey, assistant |
| [AI_ASSISTANT](docs/AI_ASSISTANT.md) | Local multilingual query understanding, routing, model and privacy decisions |
| [HALLMARKING](docs/HALLMARKING.md) · [LABS](docs/LABS.md) | Domain rules for AHCs, districts and laboratories |
| [COPYRIGHT_AND_ACCESS](docs/COPYRIGHT_AND_ACCESS.md) | Reuse terms, what is never collected, privacy |
| [DEPLOYMENT](docs/DEPLOYMENT.md) | Deploying the demo: env vars, data bundle, Docker, hosting, troubleshooting |
| [SETUP](docs/SETUP.md) · [DEMO](docs/DEMO.md) · [LIMITATIONS](docs/LIMITATIONS.md) | Running it, demo scripts, honest limits |

## Tests

```bash
cd backend && ../.venv/bin/python -m pytest            # 496 tests: parsers on real snapshots, rules, API contract
cd frontend && npm run build                           # type-check + production bundle
```

## Responsible use

Web listings are snapshots with retrieval dates. Always verify the legal position on official BIS pages and the
latest Gazette notifications. Indian Standard texts are BIS copyright and are not collected; licensed jewellers are
not listed because the official report is CAPTCHA-protected.
