# Ingestion

`python -m manakmarg ingest [--steps …] [--offline]` runs `backend/manakmarg/ingest/pipeline.py`.

## Steps

| Step | Sources | Result |
|---|---|---|
| `standards` | `data/1.xlsx`, `data/2.xlsx`, 18 ministry exports (read-only) | Standards, aliases, ministry nodes and links |
| `schemes` | Scheme I, II, IV, X pages; upcoming-QCO page | Listings with status basis, standard links, orders |
| `pages` | Compulsory overview, apply-for-licence, certification process, 4 FAQ pages, hallmarking overview | Process steps, scheme documents, FAQs, searchable page text |
| `psg` | Product Specific Guidelines table | 1,645 guideline rows with standard resolution |
| `documents` | Product Manuals and QCO PDFs for the demo families (`ingest/demo_families.py`) | Parsed manual sections (SIT, test equipment, scope) and page-numbered chunks |
| `labs` | LIMS BIS, recognised and empanelled directories (all pages); Group-1 and Group-2 PDFs | Laboratories and list entries with derived status |
| `lab_scope` | LIMS IS-wise search for the demo standard numbers (all result pages) | Scope rows and clause-wise items |
| `hallmarking` | Manakonline AHC list and suspended/cancelled list; Gazette S.O. 4345(E); phase-wise district PDF | AHCs, events, districts with Gazette cross-check, Gazette-only districts |
| `index` | — | FTS5 rebuild and LSA vectors |
| `quality` | — | `data/manifests/data_quality.json`, `docs/DATA_QUALITY.md`, `data/manifests/sources.json` |

## Runs and provenance

Each source is one `RunRecorder` run: rows are upserted with a hash of key + values and classified as inserted,
updated or unchanged; rows of that source not seen in the run are marked `is_current = 0` (retired), never deleted.
A failure rolls the run back and records it as `failed` with the error. Every fetched response is recorded in
`raw_artifact` with its sha256.

## Polite fetching (`ingest/fetch.py`)

* User-Agent `ManakMarg-SIH2026-Prototype/0.1 (educational research; polite crawler)`; robots.txt honoured.
* At least 2.5 seconds between requests to the same host.
* Retries with backoff only for transient failures: connection errors, transfers broken mid-body, HTTP 429 and 5xx.
* **HTTP 401/403, robots disallow and CAPTCHA pages raise `AccessBlocked`: recorded, never retried, never worked
  around.** Example: `https://www.bis.gov.in/PDF/cart/PM_IS_2062.pdf` returns 403 and is shown as access-denied.
* Responses are cached under `data/raw/web/<source_id>/` keyed by URL and query; `--offline` replays the cache and
  raises on a miss.

## Parsing notes

* HTML tables are expanded cell by cell (rowspan/colspan) before parsing, so notification cells inherited across
  rows keep their meaning; illustrative sub-items keep a link to their parent listing.
* Order names printed on the line before an S.O. link become the order title and kind.
* PDF tables come from PyMuPDF `find_tables`; Product Manual SIT cells merged across rows are carried forward and
  flagged `merged_from_previous`.
* Group-1 lab remarks that continue across page breaks are re-joined; status comes only from dated remark events.
* District names are compared with the Gazette annex by exact name, curated renames (e.g. Gurgaon ↔ Gurugram) and
  spelling variants within the same state; unmatched entries on either side are reported, not dropped.

## Validation (latest run)

* 392 phase-wise districts vs 392 Gazette annex entries: 391 paired (13 via rename or spelling variant); Kakinada
  (Andhra Pradesh) is only in the phase-wise list and Jalore (Rajasthan) only in the Gazette annex — both are flagged
  "needs verification" in the product.
* AHC list vs suspended/cancelled list: 124 centres are shown as suspended.
* Data-quality findings: [DATA_QUALITY.md](DATA_QUALITY.md).
