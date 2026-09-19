# Weekly BIS data refresh

MANAK MARG refreshes its **published-standards metadata** and **ministry classification** from the BIS Standards
portal every Saturday, without anyone having to do anything. A new dataset replaces the working one only when every
check has passed; otherwise the previous dataset stays active and the failure is written to the refresh log.

Code: `backend/manakmarg/refresh/`. The existing standards importer (`ingest/excel_standards.py`), full-text and
vector index builders and data-bundle tools are reused, not duplicated.

## What is refreshed, and what is not

| Refreshed | Not touched |
|---|---|
| Published standards (number, title, publication date, type, degree of equivalence) from the overall list | Compulsory-certification listings, QCOs and notifications |
| Ministry classification (one node per ministry, and its standards) | Product Manuals and certification schemes |
| Full-text indexes, vector indexes and the product vocabulary built from the database | Laboratories, lab scope, hallmarking, AHCs, FAQs, HSN |

A published standard, a Product Manual, a QCO/compulsory listing, a certification scheme and a laboratory scope are
separate records. The refresh never derives compulsory status from the existence of a standard or from its ministry;
the regulatory logic keeps reading the compulsory-certification listings and orders. The regression check fails the
refresh if any of those tables changes.

## How BIS serves the files (the downloader layer)

Everything BIS-specific lives in `refresh/portal.py`. It was written from the portal's own public JavaScript
(September 2026); no endpoint is guessed.

| Source | What the page does | What the refresh does |
|---|---|---|
| **Overall standard list** — [Published Standards List](https://standards.bis.gov.in/website/published-standards/published-standards-list?selectedType=7&committeeEncId=&totalRow=1) | Its **Export** button POSTs `review-service/downloadPublishedStandardsListExcel` with the page's filters (heading "Total"); the reply names the file (`filePath`), which the page downloads | Makes the same request and downloads the same `.xlsx` file |
| **Ministry-wise classification** — [Ministry-wise page](https://standards.bis.gov.in/website/published-standards/published-standard-ministrywise?activeTab=ministry) | Lists ministries (`project-service/getWebsiteMinistries`) with counts (`review-service/getWebsiteMinistriesWisePSCount`); each ministry opens its own Published Standards List page, whose **Export** produces that ministry's Excel | Reads the ministry list, then for **every ministry with standards** requests that ministry's Export, one file per ministry |
| **Group-wise** | The page's aggregate download is shown only to signed-in users whose role the portal approves | **Not collected.** An existing group-wise export in `data/` (`2.xlsx`) is reused unchanged, so its flags are preserved |

The Ministry-wise and Group-wise pages' own aggregate "Download" buttons need a signed-in account with an approved
role; they are not used. The refresh makes only the anonymous requests the public pages make for any visitor, with
MANAK MARG's own User-Agent, robots.txt honoured and at least 2.5 s between requests to a host. HTTP 401/403, a
robots disallow or a CAPTCHA stops the refresh (`access_blocked`) and is never retried or worked around. No login,
token, CAPTCHA solving or rate-limit evasion is involved. Export files are accepted only over HTTPS from the portal's
object storage or a `bis.gov.in` host.

## The Saturday run

```
Saturday 02:30 IST (MANAKMARG_REFRESH_WEEKDAY / MANAKMARG_REFRESH_TIME_IST)
  1. download the overall standard list export               → validate the file
  2. group-wise: reuse the existing export (not collectable)
  3. read the Ministry-wise list; for every ministry with standards:
       download that ministry's export                       → validate the file
  4. validate the dataset (all ministries collected, no large shrink)
  5. stage: copy the active database, ingest the files (normalise, deduplicate, upsert, retire)
  6. rebuild the full-text indexes, vector indexes and product vocabulary; run data-quality checks
  7. regression checks: the assistant must answer a fixed set of questions the same way on the staged and active
     datasets (IS 2062 and IS-2062, IS 13688, copper wire, Packaged Pasteurized Milk, a compulsory product,
     labs in Kolkata, hallmarking in Jaipur, licence process, Scheme I, HSN, Hindi, Hinglish, out of scope);
     regulatory, lab, hallmarking and HSN tables must be unchanged; optional full test suite
  8. activate: snapshot the active dataset, swap in the staged database and indexes, verify
  9. log the result
```

It runs in a background thread of the server started with `python -m manakmarg start` (the deployment entry point).
No cron, worker or external scheduler is needed. If the server was down at the scheduled time and the log shows no
run since, one catch-up run starts about 10 minutes after the next start-up. A fresh installation with no log waits
for Saturday, so restarts never cause repeated downloads.

### File checks (every download)

Readable `.xlsx`; a header row with `Standard Number`, `Date of Publish`, `Title`, `Type of Standard` and
`Degree of Equivalence`; at least one data row; heading "Total" for the overall list, or the ministry's name for a
ministry file; at most 1 % unparseable standard numbers; a ministry file with at least 90 % of the count the portal
shows for it (smaller differences are warnings).

### Dataset checks

* Every ministry with standards was downloaded and passed its file checks. **One missing ministry fails the refresh**.
* At least one ministry was detected. None means the page changed.
* The overall list shrank by no more than 5 % against the active dataset, and the number of ministries by no more than
  5 % against the last successful refresh.
* The downloaded files were all ingested, the rebuilt full-text index finds current standards, and the product
  vocabulary is not empty.

### Deduplication and records

Standards are keyed by their canonical standard number (`IS 13688:2020`). Repeated rows are counted as duplicates,
and two different spellings of the same key are rejected for review. A standard missing from the new overall export is
marked no longer current (history is kept, nothing is deleted). A ministry node or link that is no longer listed is
retired the same way. Titles, dates and types come only from the export.

## Failure safety

The working dataset is `data/processed/manakmarg.sqlite3` plus `data/indexes/`, and it is replaced only in step 8.
Before that, the refresh works only on files under `data/refresh/<version>/`. If anything fails (a ministry download,
a corrupt file, missing columns, a changed page, validation, ingestion, indexing or a regression check) nothing is
swapped. The log records the reason.

Activation first exports the active dataset to `previous-dataset.tar.gz`. It then copies the staged files next to the
active ones, closes the server's database connections, and replaces the database and index files with `os.replace`.
If the replacement or the post-swap check fails, the previous dataset is restored from that snapshot (`rolled_back`),
and the server then reopens whichever dataset is active. Only one refresh runs at a time (`data/refresh/refresh.lock`,
stale after 6 hours).

## Versions, snapshots and the log

```
data/refresh/
  refresh_log.jsonl            one JSON line per refresh
  ACTIVE.json                  version, activation time, standards and ministry-node counts of the active dataset
  20260919T210000Z/            one folder per refresh (UTC start time)
    downloads/                 overall-total.xlsx, ministry-<id>.xlsx, groupwise-carried-2.xlsx
    downloads.json             URLs, sha256, sizes and file checks
    report.json                the full report
    data_quality.json
    previous-dataset.tar.gz    the dataset that was active before this one (data bundle format)
    dataset.tar.gz             the dataset this refresh activated
```

The newest 6 version folders are kept (`MANAKMARG_REFRESH_KEEP_VERSIONS`), and the active one is never removed. A
snapshot is a normal data bundle, so an older dataset can be restored with
`python -m manakmarg import-data data/refresh/<version>/dataset.tar.gz --force` while the server is stopped.

Each log line records:
- the refresh id, trigger, start and completion times
- the source URLs
- the active dataset version before and after
- overall export status, rows, generation time and sha256, and group-wise status
- ministries detected, with standards, downloaded and failed (with reasons)
- standards before, after, added, updated and removed, plus duplicates and rejections
- ministry nodes and links before and after
- the validation result (problems and warnings)
- regression-check and optional test-suite results
- the activation result and any error

The same summary is available read-only as `data_refresh` in `GET /api/meta`, and from
`python -m manakmarg refresh-status`. There is no admin interface.

## Running it by hand (development and testing)

```bash
python -m manakmarg refresh --no-activate      # download, validate, stage and check; keep the active dataset
python -m manakmarg refresh                    # the full refresh including activation
python -m manakmarg refresh --with-tests       # also run the backend test suite before activating (dev install)
python -m manakmarg refresh-status             # active version and the last five refreshes
python -m manakmarg serve --refresh-schedule on  # run the Saturday schedule in a development server
```

Run `refresh` with activation while the server is **stopped**, or let the server's own schedule do it. A separate
process cannot close the running server's database connections before swapping the file.

Unit tests use a fake portal and fake HTTP sessions and never contact BIS: `tests/refresh/`.

## When BIS changes its website

A changed page shows up as a failed refresh, never as silently incomplete data. Typical signs in the log are
`structure_changed` (a reply without the expected fields, no ministries, a non-Excel file), `invalid` files (a
different heading or missing columns), `access_blocked`, or a validation failure. The previous dataset stays active
and the site's weekly attempts continue.

To adapt, update only `refresh/portal.py`: request URLs, payload fields and reply fields. Re-read the portal's
current JavaScript or network requests from its public pages the same way; do not guess. Then update
`tests/refresh/test_portal.py` and run `refresh --no-activate`. If BIS starts requiring sign-in or a CAPTCHA for these
exports, the refresh must stay stopped. Do not work around it; record the access status in `ingest/sources.py`.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `MANAKMARG_REFRESH_SCHEDULE` | `auto` | `auto`: scheduled by `start`, not by `serve`; `on`; `off` |
| `MANAKMARG_REFRESH_WEEKDAY` | `5` | Monday = 0 … Saturday = 5 |
| `MANAKMARG_REFRESH_TIME_IST` | `02:30` | Time of day in IST |
| `MANAKMARG_REFRESH_CATCH_UP` | `true` | One run after start-up when a Saturday was missed |
| `MANAKMARG_REFRESH_DIR` | `data/refresh` | Downloads, versions, snapshots and log |
| `MANAKMARG_REFRESH_KEEP_VERSIONS` | `6` | Version folders kept |
| `MANAKMARG_REFRESH_MAX_SHRINK` | `0.05` | Largest accepted drop in standards or ministries |
| `MANAKMARG_REFRESH_MIN_ROW_RATIO` | `0.9` | Minimum rows in a ministry file relative to the portal's count |
| `MANAKMARG_REFRESH_EXPORT_TIMEOUT_S` | `900` | Time allowed for the portal to generate one export |
| `MANAKMARG_REFRESH_RUN_PYTEST` | `false` | Run the backend test suite before activation (needs dev dependencies) |

## Hosting notes

* The schedule needs a server process that is running on Saturday morning. A free instance that sleeps when idle
  refreshes only while awake (plus the catch-up on the next start).
* On hosts with an ephemeral disk, a restart returns to the dataset shipped in the image or bundle and loses
  `data/refresh/`. Mount `data/` on a persistent volume, or publish a refreshed `dataset.tar.gz` as the deployment
  bundle (`MANAKMARG_DATA_URL`).
