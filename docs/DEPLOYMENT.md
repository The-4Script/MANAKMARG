# Deploying MANAK MARG

This guide is for the team member deploying the demo. MANAK MARG is **one process**: a FastAPI server that serves
the JSON API under `/api` and the built React app at `/`. Data lives in a local SQLite file. There is no database
server, message queue, background worker, scheduled job or external API to set up, and nothing is scraped at startup.

> The fastest path is the Docker image (section 6). Without Docker, follow sections 3–5.

## 1. Prerequisites

| Need | Version | Notes |
|---|---|---|
| Python | 3.12 or newer | Developed on 3.14; the Docker image uses 3.12. |
| Node.js + npm | 20 or newer | Only to build the frontend (developed on Node 24). Not needed at runtime. |
| Disk | ~400 MB | Code + dependencies ~300 MB, database 58 MB, runtime index 49 MB. |
| RAM | 512 MB minimum, 1 GB recommended | Measured figures are in section 11. |
| Network | none at runtime | Only `pip`/`npm` installs, and downloading the data bundle if you use `MANAKMARG_DATA_URL`. |

No API keys are required. The optional Claude narrative is disabled unless `ANTHROPIC_API_KEY` and
`MANAKMARG_LLM_MODEL` are both set, and the demo does not need it.

## 2. Environment variables

All of them are optional. Copy `.env.example` to `.env` for local runs, or set them in the hosting platform.
Never commit `.env`.

| Variable | Default | When to set it |
|---|---|---|
| `HOST` | `127.0.0.1` | **Set `0.0.0.0` in any container or cloud VM** (the Dockerfile already does). |
| `PORT` | `8000` (Docker image: `7860`) | Most platforms inject it; the server reads it automatically. |
| `MANAKMARG_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Only when the frontend is hosted on a different origin from the API (section 7). |
| `MANAKMARG_DB_PATH` | `data/processed/manakmarg.sqlite3` | To keep the database on a mounted volume. Relative paths are resolved from the repository root. |
| `MANAKMARG_DATA_URL` | empty | An `https://` URL of the data bundle, if it is not shipped inside the repository or image. |
| `MANAKMARG_HOME` | repository root | Only if the backend package is installed outside the repository (non-editable install). |
| `MANAKMARG_UPLOAD_TTL_MINUTES` | `120` | How long uploaded gap-analysis files are kept before deletion. |
| `MANAKMARG_UPLOAD_MAX_MB` | `15` | Upload size limit. |
| `MANAKMARG_LOG_LEVEL` | `INFO` | |
| `MANAKMARG_FETCH_MIN_DELAY_S`, `MANAKMARG_OFFLINE` | `2.5`, `false` | Only for re-running ingestion. |
| `ANTHROPIC_API_KEY`, `MANAKMARG_LLM_MODEL` | empty | Optional narrative; leave empty for the demo. |
| `VITE_API_BASE_URL` | empty | **Frontend build time only**, when the frontend is hosted separately. |

## 3. Installation (without Docker)

```bash
git clone https://github.com/The-4Script/MANAKMARG.git
cd MANAKMARG
python3 -m venv .venv
.venv/bin/python -m pip install -e backend          # Windows: .venv\Scripts\python -m pip install -e backend
cd frontend && npm ci && npm run build && cd ..      # writes frontend/dist, which the API serves
```

Install `backend[dev]` instead of `backend` if you also want to run the tests.

## 4. Database and index setup

The app needs a **populated** SQLite database and the listing vector index. They are produced by a ~25-minute
online ingestion from BIS websites. For deployment, **do not re-ingest**: restore the prebuilt bundle that is
committed in the repository.

```bash
.venv/bin/python -m manakmarg import-data            # restores deploy/data/manakmarg-data.tar.gz
```

This writes `data/processed/manakmarg.sqlite3`, `data/indexes/coverage.joblib` and `data/manifests/*.json`, after
verifying the SHA-256 checksum of every file. It does nothing if a populated database is already there; add
`--force` to replace it. To restore from somewhere else, run `import-data https://…/manakmarg-data.tar.gz` or set
`MANAKMARG_DATA_URL`.

`python -m manakmarg start` does this automatically: it restores the bundle if the database is missing, rebuilds
the listing index if it is missing, then starts the server.

### What data goes where

| Category | What | Where |
|---|---|---|
| **A. Committed to GitHub** | Code, tests (with contact-person names redacted from HTML fixtures), docs, the 20 supplied BIS Excel exports (`data/*.xlsx`, 3.8 MB), `data/manifests/*.json`, demo sample documents, and the runtime data bundle `deploy/data/manakmarg-data.tar.gz` (41.7 MB) | Repository |
| **B. Stored externally (optional)** | The same data bundle, if you would rather not keep it in git. Host it privately and set `MANAKMARG_DATA_URL`. | Private storage |
| **C. Generated during ingestion** | `data/processed/manakmarg.sqlite3` (58 MB), `data/raw/` fetch cache (235 MB, never committed) | `manakmarg ingest` |
| **D. Regenerable** | `data/indexes/coverage.joblib` (`manakmarg build-index --runtime-only`), FTS tables inside the database, `frontend/dist` (`npm run build`), `docs/DATA_QUALITY.md` (`manakmarg validate`) | Commands |
| **E. Not needed at runtime** | `data/indexes/standards.joblib` (455 MB) and `faq.joblib` (analysis only), `data/raw/`, `data/staging/`, `node_modules`, `.venv`, `docs/superpowers/` | Not deployed |

**Keep the repository private.** The database includes text extracted from BIS Product Manuals and QCO
notifications for the demo product families. These are public documents on BIS websites, but the reuse terms for
redistribution are not clear (see [COPYRIGHT_AND_ACCESS.md](COPYRIGHT_AND_ACCESS.md)).

### Rebuilding data from official sources (not needed for deployment)

```bash
.venv/bin/python -m manakmarg init-db
.venv/bin/python -m manakmarg ingest          # online, polite: ~25 minutes, needs an Indian network path to BIS sites
.venv/bin/python -m manakmarg export-data     # rewrite the bundle
```

Run ingestion on a laptop, not on a cloud host. BIS sites may block or rate-limit data-centre IPs, and the fetcher
deliberately stops on 401, 403, robots.txt or CAPTCHA responses instead of working around them.

## 5. Running the backend (serves the frontend too)

```bash
HOST=0.0.0.0 PORT=8000 .venv/bin/python -m manakmarg start
```

- `start` is the deployment entry point: restore data if needed, then serve.
- `serve` only serves. It exits with code 2 and a clear message if the database is missing or empty.
- There are no migrations to run. The schema is created by `init-db` or comes with the bundle.
- Workers: use a single process. SQLite is only read by requests; uploads are stored per session on local disk.

Systemd example for a VM:

```ini
[Unit]
Description=MANAK MARG
After=network.target

[Service]
WorkingDirectory=/opt/MANAKMARG
Environment=HOST=0.0.0.0
Environment=PORT=8000
ExecStart=/opt/MANAKMARG/.venv/bin/python -m manakmarg start
Restart=on-failure
User=manakmarg

[Install]
WantedBy=multi-user.target
```

The `User` must be able to write `data/` (SQLite WAL files and temporary uploads). Put Nginx or Caddy in front of
it for HTTPS if needed. The app has no authentication, so treat it as a public demo.

## 6. Docker (recommended)

```bash
docker build -t manakmarg .
docker run --rm -p 7860:7860 manakmarg
# open http://localhost:7860
```

The image builds the frontend, installs the backend on Python 3.12, restores the data bundle at build time, runs as
uid 1000, listens on `0.0.0.0:$PORT` (default 7860) and has a `HEALTHCHECK` on `/api/health`.

### Free deployment choices

**Render free Docker web service** is the simplest single-host option. It supports custom Docker containers at no
compute charge, sleeps when idle and provides HTTPS. The free service has 512 MB RAM and 0.1 CPU; this app has been
measured at about 290 MB after warm-up, so it may work but is not a guaranteed capacity fit. Set the health check to
`/api/health` and do not deploy the optional large indexes. Uploaded documents and generated SQLite files are
ephemeral.

The repository includes [`render.yaml`](../render.yaml), so Render can configure this automatically:

1. Push the repository to GitHub, including `Dockerfile`, `deploy/data/manakmarg-data.tar.gz` and `render.yaml`.
2. In Render, choose **New +** → **Blueprint** and select the GitHub repository.
3. Confirm the `manak-marg` web service is set to the **Free** plan, then apply the blueprint.
4. Wait for the Docker build to finish. Render injects `PORT`; the image defaults to `7860` locally and reads the
  injected Render port at runtime.
5. Open the generated `onrender.com` URL and verify `/api/health` returns `data_ready: true`.

If the bundle is kept outside Git, add `MANAKMARG_DATA_URL` under the service's Environment settings. Keep the
service private or add authentication before using uploaded documents; the application itself has no authentication.

**Google Cloud Run** is the stronger container option when a billing account is acceptable. Its request-based free
tier includes 2 million requests, 180,000 vCPU-seconds and 360,000 GiB-seconds of RAM per month in eligible regions.
It can run this Dockerfile unchanged, scales to zero, and requires billing to be enabled; usage beyond the free tier
is billable.

**Hugging Face Static Space** is free, but it can host only `frontend/dist`, not this FastAPI backend. Use it only as
a split deployment: build with `VITE_API_BASE_URL=https://your-api.example.com`, publish `frontend/dist` as the
static Space, and host the API on Render or Cloud Run with `MANAKMARG_CORS_ORIGINS` set to the Space origin.

Hugging Face **Docker** and ordinary **Gradio** Spaces require a paid plan. Gradio is not a drop-in alternative for
this project because the existing React application and FastAPI API would need a wrapper or rewrite. The prepared
Docker metadata remains in [`deploy/huggingface/README.md`](../deploy/huggingface/README.md) for paid-plan use.

For any public deployment, review the bundled BIS-derived data terms first. The app has no authentication.

**Laptop + Cloudflare quick tunnel** (no account needed): run section 5 locally, then
`cloudflared tunnel --url http://localhost:8000` and share the printed `trycloudflare.com` URL.

## 7. Frontend deployment

**Default (recommended):** no separate frontend deployment. `npm run build` writes `frontend/dist`, and the API
serves it with a single-page-app fallback, so any path such as `/journey` loads the app. Frontend and API share an
origin, so no CORS setup is needed.

**Split hosting** (for example, frontend on Netlify/Vercel/Cloudflare Pages and API elsewhere):

```bash
cd frontend
VITE_API_BASE_URL=https://your-api.example.com npm run build     # publish frontend/dist
```

Configure the static host to rewrite every path to `/index.html`. On the API, set
`MANAKMARG_CORS_ORIGINS=https://your-frontend.example.com`.

For local frontend development, run `npm run dev` (port 5173). It proxies `/api` to `127.0.0.1:8000`.

## 8. CORS

- Same origin (default and Docker): nothing to configure.
- Split origins: list every frontend origin, comma-separated, with no trailing slash, in `MANAKMARG_CORS_ORIGINS`.
  Credentials are not used.

## 9. Health check and smoke test

```bash
curl -s http://localhost:8000/api/health
# {"status":"ok","version":"0.1.0","data_ready":true}   (HTTP 503 with "no_data" if the database is missing)

curl -s http://localhost:8000/api/meta | head -c 300
curl -s -X POST http://localhost:8000/api/journey -H 'Content-Type: application/json' \
     -d '{"text":"stainless steel utensils"}' | head -c 300
curl -s -X POST http://localhost:8000/api/assistant/query -H 'Content-Type: application/json' \
     -d '{"query":"Is hallmarking mandatory in Jaipur?","lang":"en"}' | head -c 300
```

Then open the site and walk through the four flows in [DEMO.md](DEMO.md): Product journey, Hallmarking,
Laboratories and Document gap analysis (use "Load demo documents"). Interactive API docs are at `/api/docs`.

Run the automated checks:

```bash
.venv/bin/python -m pip install -e "backend[dev]"
cd backend && ../.venv/bin/python -m pytest -q
cd ../frontend && npm run build
```

## 10. Common problems

| Symptom | Cause and fix |
|---|---|
| `serve` exits with "No processed data" / `/api/health` returns 503 `no_data` | The database is not restored. Run `python -m manakmarg import-data` (or use `start`). |
| Site unreachable from outside a container or VM | Server bound to `127.0.0.1`. Set `HOST=0.0.0.0`. |
| `/` returns 404 but `/api/docs` works | Frontend not built. Run `cd frontend && npm ci && npm run build` (the Docker image does this). |
| Browser console shows CORS errors | Split hosting without `MANAKMARG_CORS_ORIGINS`, or `VITE_API_BASE_URL` points to the wrong URL. |
| `sqlite3.OperationalError: unable to open database file` or `readonly database` | `data/` is not writable by the service user (SQLite needs to create `-wal`/`-shm` files next to the database). |
| Container killed / out of memory on a 512 MB plan | Use a 1 GB instance or Hugging Face Spaces. Do not copy `standards.joblib`; it is not used at runtime. |
| First product or assistant query is slower | The listing index loads lazily on first use (a few seconds); later requests are fast. |
| Uploaded documents disappear after a restart | Expected: uploads are temporary, and platform disks are usually ephemeral. |
| Hugging Face push rejected for a large file | Track the bundle with Git LFS in the Space repo, or use `MANAKMARG_DATA_URL` (section 6). |
| `import-data` reports "checksum mismatch" | The bundle is corrupted or truncated; download it again. With Git LFS, check that `git lfs pull` fetched the real file rather than a pointer. |
| Ingestion in the cloud fails with 403 or CAPTCHA | Expected. Ingest on a laptop and export a bundle; the fetcher never bypasses access controls. |
| `pip install` fails on Python 3.11 or older | Python 3.12+ is required. |

## 11. Measured footprint

Measured on the development machine (Windows 11, Python 3.14), running from a clean clone with the section 9 commands:

- `import-data` restores the bundle in about 4 seconds.
- A journey request takes about 0.5 seconds once the index is loaded.
- Only the listing vector index is loaded into memory.
- Server working set after warm-up (journey, assistant, hallmarking, labs and gap-analysis requests) is about
  290 MB. Windows reports more committed (private) memory because of numerical-library allocations, and this was
  not measured on Linux.
- Plan for **1 GB RAM**. A 512 MB instance may work, but it has not been verified.
