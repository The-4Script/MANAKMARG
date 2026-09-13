# Setup

## Prerequisites

* Python 3.12 or newer (developed on CPython 3.14.5, Windows 11).
* Node.js 20+ and npm (developed on Node 24.14, npm 11.9) — only to build the frontend.
* Internet access for the first ingestion. Afterwards everything runs offline from the cache.

No database server is required: data lives in SQLite (`data/processed/manakmarg.sqlite3`) with FTS5 indexes.

## Install

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e "backend[dev]"        # add ",llm" to enable the optional Claude narrative
cd frontend
npm install
npm run build                                              # writes frontend/dist, served by the API
```

On Linux/macOS use `.venv/bin/python`.

## Configure

Copy `.env.example` to `.env` (never commit `.env`). All settings are optional:

| Variable | Default | Meaning |
|---|---|---|
| `MANAKMARG_DB_PATH` | `data/processed/manakmarg.sqlite3` | Database file (relative paths are anchored to the project root) |
| `MANAKMARG_FETCH_MIN_DELAY_S` | `2.5` | Minimum seconds between requests to the same host |
| `MANAKMARG_OFFLINE` | `false` | Never use the network; replay cached snapshots |
| `MANAKMARG_UPLOAD_TTL_MINUTES` | `120` | Lifetime of gap-analysis upload sessions |
| `MANAKMARG_UPLOAD_MAX_MB` | `15` | Maximum size of one uploaded file |
| `MANAKMARG_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Origins allowed during frontend development |
| `MANAKMARG_LOG_LEVEL` | `INFO` | Log level |
| `HOST`, `PORT` | `127.0.0.1`, `8000` | Server bind address and port (use `HOST=0.0.0.0` in containers) |
| `MANAKMARG_DATA_URL` | unset | URL of the data bundle for `import-data`/`start` when it is not in the repository |
| `ANTHROPIC_API_KEY`, `MANAKMARG_LLM_MODEL` | unset | Optional Claude narrative; the product is fully functional without them |

## Build the data

**Quickest:** restore the prebuilt bundle with `python -m manakmarg import-data` (see
[DEPLOYMENT.md](DEPLOYMENT.md)). After re-ingesting, run `python -m manakmarg export-data` to refresh the bundle.

To rebuild from official sources instead: the supplied Excel workbooks stay untouched in `data/`. From `backend/`:

```bash
../.venv/Scripts/python -m manakmarg ingest                  # all steps, polite online fetching, ≈25 minutes
../.venv/Scripts/python -m manakmarg ingest --steps labs lab_scope   # selected steps
../.venv/Scripts/python -m manakmarg ingest --offline        # replay the cache in data/raw/web
../.venv/Scripts/python -m manakmarg build-index             # FTS5 + LSA vectors only
../.venv/Scripts/python -m manakmarg validate                 # data-quality report → docs/DATA_QUALITY.md
../.venv/Scripts/python -m manakmarg inventory               # workbook profile → docs/DATA_INVENTORY.md
```

## Run

```bash
../.venv/Scripts/python -m manakmarg serve --port 8000
```

Open http://127.0.0.1:8000. API documentation is at http://127.0.0.1:8000/api/docs.

For frontend development with hot reload, keep the API running and start `npm run dev` in `frontend/`
(Vite proxies `/api` to port 8000) — then open http://localhost:5173.

## Test

```bash
cd backend && ../.venv/Scripts/python -m pytest
cd frontend && npm run build
```

Parser tests run on trimmed real snapshots in `backend/tests/fixtures/bis/` (see its README for attribution);
API and reasoning tests build a small database from those fixtures, so no network is used.
