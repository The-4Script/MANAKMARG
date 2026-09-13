# MANAK MARG Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. **This session executes inline** (session policy: no subagents unless the user asks) with superpowers:test-driven-development per task. Steps use checkbox (`- [ ]`) syntax for tracking. Code lives in the repository, written test-first; this plan fixes file layout, interfaces, and verification so modules stay consistent across a long build.

**Goal:** Build an evidence-first BIS compliance navigator (data pipeline → normalized SQLite → hybrid retrieval → deterministic reasoning → optional Claude narrative → FastAPI → React UI) that demonstrates four end-to-end flows with official provenance.

**Architecture:** Modular monolith. `backend/manakmarg` (Python 3.14) holds ingestion, normalization, search, reasoning, documents and API; `frontend/` is a React + TypeScript + Vite + Tailwind SPA. Legal/compulsory status, dates and eligibility come only from deterministic rules over official records. Spec: `docs/superpowers/specs/2026-09-13-manak-marg-design.md`.

**Tech Stack:** Python 3.14 · SQLite 3.50 (FTS5, JSON1) · SQLAlchemy 2 Core · FastAPI · pydantic 2 · requests + BeautifulSoup/lxml · openpyxl · PyMuPDF · python-docx · scikit-learn (TF-IDF/LSA) · optional `anthropic` · pytest · React · TypeScript · Vite · Tailwind CSS.

## Global Constraints

- Supplied workbooks in `data/*.xlsx` are read-only raw inputs — never modified, moved or renamed.
- Never bypass CAPTCHA, authentication, HTTP 401/403, DRM/FileOpen, anti-devtools or undocumented APIs; a 401/403/CAPTCHA response is recorded as `access_denied` and not retried.
- Outbound requests: User-Agent `ManakMarg-SIH2026-Prototype/0.1 (educational research; polite crawler)`, ≥ 2.5 s between requests per host, cached by URL + sha256, `--offline` replay supported.
- No fabricated standards, QCOs, schemes, labs, AHCs, jewellers, enforcement dates, tests, clauses or requirements; missing data is shown as unavailable/unknown.
- Compulsory status, enforcement effectiveness, lab validity and AHC operability are computed by deterministic rules from official records against an injectable clock — never from similarity scores or LLM output.
- Every domain row carries `source_id`, `run_id`, `source_locator`, `retrieved_at`.
- Standard identity: prefix is part of identity; `std_key`/`family_key`/`match_key` as defined in spec §6.1; canonical collisions are reported, never merged.
- Secrets only via environment variables (`.env` ignored, `.env.example` committed).
- Uploads: ≤ 15 MB per file, per-session storage, TTL 120 minutes, contents never logged.
- Quoted snippets from sources ≤ 300 characters with source attribution; UI links to official URLs.
- UI languages English and Hindi; IS numbers, S.O./G.S.R. numbers, clause references and recognition numbers are never translated.
- Contact-person names from LIMS/AHC listings are not stored; organisation phone/e-mail as published are.
- No git commits unless the user asks.

---

## File Structure

```
.gitignore · .env.example · README.md
backend/pyproject.toml
backend/manakmarg/
  __init__.py · __main__.py                     CLI (argparse): init-db, ingest, sync-lab-scope, fetch-documents,
                                                  build-index, validate, inventory, serve
  core/   paths.py · config.py · clock.py · log.py
  db/     schema.py · engine.py · fts.py
  normalize/ is_number.py · dates.py · text.py · geo.py · status_rules.py · orders.py
  ingest/ sources.py · fetch.py · runs.py · html_grid.py
          excel_standards.py · bis_schemes.py · compliance_loader.py
          psg.py · product_manual.py · documents.py · bis_pages.py (process steps, scheme docs, FAQs)
          lims.py · lab_lists.py · hallmarking.py (AHC list, AHC events, districts, Gazette annex)
          demo_families.py · pipeline.py · inventory.py · quality.py
  search/ resolvers.py · fts_search.py · vectors.py · hybrid.py · synonyms.json
  reasoning/ evidence.py · intents.py · applicability.py · journey.py · labs.py · hallmarking.py
             i18n.py · composer.py · assistant.py
  llm/    client.py · guardrails.py · prompts.py
  documents/ store.py · extract.py · units.py · requirements.py · values.py · compare.py · gap.py
  reports/ compliance_report.py
  api/    app.py · deps.py · schemas.py · routers/{meta,sources,standards,compliance,labs,hallmarking,faq,
          assistant,journey,documents,reports}.py
backend/tests/  mirrors package layout; fixtures/ holds small HTML/PDF/XLSX fixtures
frontend/       Vite React TS app (src/api, src/components, src/pages, src/i18n)
docs/           ARCHITECTURE.md, DATA_MODEL.md, DATA_SOURCES.md, DATA_INVENTORY.md, DATA_QUALITY.md,
                INGESTION.md, RETRIEVAL_AND_REASONING.md, COMPLIANCE_LOGIC.md, HALLMARKING.md, LABS.md,
                COPYRIGHT_AND_ACCESS.md, SETUP.md, DEMO.md, LIMITATIONS.md
data/manifests/ sources.json · data_inventory.json · data_quality.json
```

---

## Milestone 1 — Foundation

### Task 1.1: Scaffold, configuration, clock, paths

**Files:** Create `.gitignore`, `.env.example`, `backend/pyproject.toml`, `backend/manakmarg/{__init__,__main__}.py`, `backend/manakmarg/core/{__init__,paths,config,clock,log}.py`, `backend/tests/conftest.py`, `backend/tests/core/test_core.py`.

**Interfaces — Produces:**
- `manakmarg.core.paths`: `PROJECT_ROOT`, `DATA_DIR`, `RAW_WEB_DIR`, `RAW_DOCS_DIR`, `STAGING_DIR`, `PROCESSED_DIR`, `INDEX_DIR`, `MANIFEST_DIR`, `UPLOAD_DIR`, `DOCS_DIR` (all `Path`); `ensure_dirs() -> None`.
- `manakmarg.core.config`: `class Settings(BaseSettings)` with `db_path: Path`, `anthropic_api_key: str | None`, `llm_model: str | None`, `fetch_min_delay_s: float = 2.5`, `user_agent: str`, `offline: bool = False`, `upload_ttl_minutes: int = 120`, `upload_max_mb: int = 15`, `cors_origins: list[str]`, `log_level: str = "INFO"`; property `llm_enabled: bool`; `get_settings() -> Settings` (cached; env prefix `MANAKMARG_`, plus `ANTHROPIC_API_KEY`).
- `manakmarg.core.clock`: `today() -> date`, `now_utc() -> datetime`, `freeze(d: date | None) -> None`.
- `manakmarg.core.log`: `get_logger(name: str) -> logging.Logger`.

- [ ] Write tests: paths resolve under project root; settings defaults and env override; `freeze()` controls `today()`.
- [ ] Run `python -m pytest backend/tests/core -q` → fails (modules missing).
- [ ] Implement modules; create `.venv` (`python -m venv --system-site-packages .venv`), `pip install -e backend[dev]`.
- [ ] Re-run → pass.

### Task 1.2: Database schema, engine, FTS helpers

**Files:** Create `backend/manakmarg/db/{__init__,schema,engine,fts}.py`, `backend/tests/db/test_schema.py`.

**Interfaces — Produces:**
- `manakmarg.db.schema.metadata` containing tables named exactly as spec §5 (`source`, `ingestion_run`, `raw_artifact`, `document`, `document_chunk`, `standard`, `standard_alias`, `classification_node`, `standard_classification`, `standard_relation`, `certification_scheme`, `regulatory_order`, `scheme_coverage`, `coverage_standard`, `coverage_order`, `product_term`, `product_guideline`, `guideline_section`, `process_step`, `scheme_document`, `laboratory`, `lab_scope`, `lab_scope_item`, `ahc`, `ahc_status_event`, `hallmarking_district`, `district_alias`, `jeweller`, `faq`). Domain tables include provenance columns `source_id`, `run_id`, `source_locator`, `retrieved_at`, `record_hash`, `first_seen_run`, `last_seen_run`, `is_current`.
- `manakmarg.db.engine.get_engine(db_path: Path | str | None = None) -> Engine` (foreign keys on, WAL), `init_db(engine: Engine) -> None`.
- `manakmarg.db.fts`: `FTS_SPECS: dict[str, FtsSpec]`, `create_fts(conn) -> None`, `rebuild_fts(conn, name: str | None = None) -> None`.

- [ ] Tests: `init_db` on temp file creates all tables; FTS5 table accepts insert and MATCH; every domain table has provenance columns.
- [ ] Implement; tests pass.

### Task 1.3: Source registry, polite fetcher, run recorder

**Files:** Create `backend/manakmarg/ingest/{__init__,sources,fetch,runs}.py`, tests `backend/tests/ingest/{test_sources,test_fetch,test_runs}.py`.

**Interfaces — Produces:**
- `sources.SourceDef` (dataclass mirroring `source` columns); `sources.REGISTRY: dict[str, SourceDef]`; `sync_registry(conn) -> None`; `export_manifest(path: Path) -> None`.
- `fetch.FetchResult(url, final_url, status, content: bytes, content_type, sha256, local_path: Path, retrieved_at: datetime, from_cache: bool)`; `fetch.AccessBlocked(Exception)`; `fetch.Fetcher(cache_root: Path, *, min_delay_s: float, user_agent: str, offline: bool = False, session=None)` with `.get(url: str, *, source_id: str, params: dict | None = None, refresh: bool = False) -> FetchResult`.
- `runs.RunRecorder(conn, source_id: str, notes: str = "")` (context manager) with `.run_id`, `.upsert(table: str, key: dict, values: dict, locator: str, retrieved_at: datetime | None = None) -> str` returning `"inserted" | "updated" | "unchanged"`, `.retire_unseen(table: str, where: dict | None = None) -> int`, `.reject(locator: str, reason: str) -> None`, `.artifact(result: FetchResult) -> None`, `.stats: dict`.

- [ ] Tests: registry entries have required fields and unique ids; fetcher uses cache in offline mode, raises `AccessBlocked` on 403 (mocked session), enforces delay (fake sleep); recorder counts inserted/updated/unchanged, retires unseen rows, writes `ingestion_run`.
- [ ] Implement; tests pass.

---

## Milestone 2 — Standards master data

### Task 2.1: IS designation parser and keys

**Files:** Create `backend/manakmarg/normalize/{__init__,is_number}.py`, `backend/tests/normalize/test_is_number.py`.

**Interfaces — Produces:** `@dataclass(frozen=True) Designation(raw, prefix, number, part, section, subsection, year, suffix, flags: tuple[str, ...])` with properties `std_key`, `family_key`, `match_key`, `number_key`; `parse_designation(text: str, *, assume_is_prefix: bool = False) -> Designation | None`; `extract_designations(text: str, *, assume_is_prefix: bool = False) -> list[Designation]`.

- [ ] Tests from real shapes (spec §2.1, §6.1): whitespace/colon variants collapse to one key; `Is`/`IS ISO`/`IS/IEc`/`IECTR`/`IEE` repairs flagged; `(Part n/Sec m/Sub-Sec k)`, colon-part, bare `Part`, `(Pt n)`, part ranges, letter parts, hyphen and underscore parts; LIMS `IS 2062 (Part 2) (2026)`; missing colon; duplicated year; suffixes `P`/`T`/`Supplement`/`(S&T)`; malformed `IS):7779 ( (Part 1/Sec 1)):1975` → `IS 7779 (Part 1/Sec 1):1975` flagged; `IS 13450` ≠ `IS/ISO 13450`; `IS/ISO 80000-9:2019` match key equals `IS/ISO 80000 (Part 9)`; multi-reference extraction (`IS 13422: 2024 / ISO 10282: 2023`, `IS 14286 IS/IEC 61730 -1 IS/IEC 61730 -2`, `IS 302 (Part 1) : 2024 IEC 60335-1:2020`); prefix assumption only when requested.
- [ ] Implement; tests pass; run parser over both master exports and assert zero unparsed except whitelisted oddities.

### Task 2.2: Dates, text, geography, status and order helpers

**Files:** Create `backend/manakmarg/normalize/{dates,text,geo,status_rules,orders}.py`, tests in `backend/tests/normalize/`.

**Interfaces — Produces:**
- `dates.parse_date(text: str | None) -> date | None`; `dates.find_dates(text: str) -> list[date]`.
- `text.clean_ws(s) -> str`; `text.norm_match(s) -> str`; `text.split_title(title) -> TitleParts(title_clean, revision_label, amendment_label)`; `text.snippet(s, limit=300) -> str`.
- `geo.normalize_state(s) -> str | None`; `geo.norm_district(s) -> str`; `geo.parse_ahc_address(s) -> Address`; `geo.parse_lims_address(s) -> Address` where `Address(lines, area, city, district, state, pincode)`.
- `status_rules.classify_listing(page_kind: str, category: str, product: str, notification: str) -> ListingDecision(status, basis)`.
- `orders.OrderRef(title, url, kind, so_number, gsr_number, order_date, raw_text)`; `orders.parse_order_links(links: list[tuple[str, str]], cell_text: str) -> list[OrderRef]`; `orders.classify_order_kind(text: str) -> str`.

- [ ] Tests: all date formats from spec §6.2; state map incl. `U.P.`, `Chhattisgargh`, `PONDICHERY`; AHC and LIMS address samples from snapshots; De-notified / Rescind / upcoming / default rules; S.O./G.S.R./date extraction from real anchor texts (e.g. `S.O. 3583(E), dated 9th August 2023`, `G.S.R. No. 1081(E) Dt. 22-11-2016`).
- [ ] Implement; tests pass.

### Task 2.3: Excel standards ingestion

**Files:** Create `backend/manakmarg/ingest/excel_standards.py`, tests `backend/tests/ingest/test_excel_standards.py` (fixtures generated with openpyxl in `tmp_path`).

**Interfaces:**
- Consumes: `parse_designation`, `split_title`, `parse_date`, `RunRecorder`.
- Produces: `read_export(path: Path) -> ExportFile(path, title_cell, generated_on, rows: list[ExportRow])`; `ExportRow(sheet_row, sl_no, designation_raw, publish_date_raw, title, standard_type, degree)`; `classify_export(ef: ExportFile) -> str` (`master_total` · `second_total` · `ministry_node` · `unknown`); `ingest_standard_exports(conn, data_dir: Path) -> dict` (stats per file).

- [ ] Tests: header detection; title-cell classification; "-" → NULL; dates parsed; duplicate rows in second export do not duplicate standards; extra designation from second export inserted; ministry "Ministry – Department" → child node with parent; ministry-only designation inserted with `listing_status='ministry_export_only'`; aliases recorded; provenance populated; re-run → all `unchanged`.
- [ ] Implement; run on real `data/` into a scratch DB and check counts (24,015 published + ministry-only; 18 nodes).

### Task 2.4: Inventory and data-quality report

**Files:** Create `backend/manakmarg/ingest/{inventory,quality}.py`, tests.

**Interfaces — Produces:** `build_inventory(data_dir: Path) -> dict` (per workbook/sheet: domain, description, row_count, column_count, important_columns, candidate_key, duplicate_characteristics, relationship_to_other_data, data_quality_issues, source_type, authority_level, notes); `write_inventory(inv, json_path, md_path) -> None`; `run_quality_checks(conn) -> list[Finding]` with `Finding(check, severity, count, examples, note)`; `write_quality_report(findings, json_path, md_path) -> None`.

- [ ] Tests on fixture workbooks and a small DB; implement; generate `data/manifests/data_inventory.json`, `docs/DATA_INVENTORY.md`.

---

## Milestone 3 — Compulsory certification

### Task 3.1: HTML table grid expansion

**Files:** Create `backend/manakmarg/ingest/html_grid.py`, tests with inline HTML fixtures.

**Interfaces — Produces:** `Link(text, href)`; `GridCell(text, links, origin_row, origin_col, rowspan, colspan, is_origin)`; `table_to_grid(table: bs4.Tag) -> list[list[GridCell | None]]`; `origin_cells(grid, row_index) -> list[GridCell]`.

- [ ] Tests: rowspan fill, colspan fill, combined `colspan=2 rowspan=91`, `th` cells, links preserved, ragged rows.

### Task 3.2: Scheme page parsers

**Files:** Create `backend/manakmarg/ingest/bis_schemes.py`, tests `backend/tests/ingest/test_bis_schemes.py` (fixtures: trimmed real snapshots saved under `backend/tests/fixtures/bis/`).

**Interfaces — Produces:** `CoverageRecord` dataclass (fields per spec §5.3 `scheme_coverage` + `orders: list[OrderRef]`, `standard_refs: list[str]`, `children: list[str]`, `locator`); `parse_scheme_i(html: bytes, url: str) -> list[CoverageRecord]`; `parse_scheme_ii(...)`; `parse_scheme_iv(...)`; `parse_scheme_x(...)`; `parse_upcoming_qcos(...)`.

- [ ] Tests: Scheme I uses `div.schdesktop`; category rows vs illustrative sub-items; notification rowspans inherited; De-notified rows → DENOTIFIED; Scheme II section labels; Scheme IV essential requirement; Scheme X table 1 → RESCINDED with basis quote; upcoming entry 13 yields parent + 90 illustrative children with inherited IS/date; prefix-less IS refs parsed with `assume_is_prefix`.

### Task 3.3: Coverage loading and standard resolution

**Files:** Create `backend/manakmarg/search/{__init__,resolvers}.py`, `backend/manakmarg/ingest/compliance_loader.py`, tests.

**Interfaces — Produces:** `Resolution(kind, standard_ids: list[int], family_key: str | None, designation: Designation | None)`; `StandardResolver(conn).resolve(ref: str, *, assume_is_prefix: bool = False) -> list[Resolution]`; `load_scheme_records(conn, recorder, records: list[CoverageRecord], scheme_id: str) -> dict`; `seed_schemes(conn) -> None`.

- [ ] Tests: exact version, family latest, family ambiguous, version not in master, unresolved; orders deduplicated by URL; coverage ↔ standards ↔ orders rows created; product terms seeded.

---

## Milestone 4 — Guidelines, documents, process, FAQs

### Task 4.1: PSG metadata + Product Manual parsing

**Files:** Create `backend/manakmarg/ingest/{psg,product_manual,documents,demo_families}.py`, tests (PM fixture: text of the IS 14756 manual pages as `.txt` fixture plus parser unit tests on page text).

**Interfaces — Produces:** `parse_psg(html: bytes, url: str) -> list[GuidelineRecord]`; `parse_product_manual_pages(pages: list[str]) -> list[ManualSection]` with `ManualSection(section_key, heading, page_start, page_end, text, structured: dict)`; `documents.fetch_and_register(conn, fetcher, recorder, url, doc_type, source_page_url, title) -> int | None`; `documents.chunk_pdf(path: Path) -> list[Chunk]`; `demo_families.DEMO_FAMILIES: list[DemoFamily(label, is_refs, pm_refs, lims_doc_nos)]`.

### Task 4.2: Process pages and FAQs

**Files:** Create `backend/manakmarg/ingest/bis_pages.py`, tests with snapshot fixtures.

**Interfaces — Produces:** `parse_apply_licence(html) -> list[ProcessStepRecord]`; `parse_certification_process_docs(html) -> list[SchemeDocRecord]`; `parse_faq_page(html, category: str, url: str) -> list[FaqRecord]`; `parse_scheme_intro(html) -> str | None`.

---

## Milestone 5 — Laboratories

### Task 5.1: LIMS directories, Group-1/2 lists, IS-wise scope

**Files:** Create `backend/manakmarg/ingest/{lims,lab_lists}.py`, tests with snapshot fixtures.

**Interfaces — Produces:** `parse_lims_directory(html: bytes, category: str) -> LimsPage(labs: list[LabRecord], page_urls: list[str])`; `parse_lims_scope_search(html: bytes) -> ScopePage(rows: list[ScopeRecord], total: int | None, page_urls: list[str])` (breakup items included); `parse_group_list_pdf(path: Path, group: int) -> list[LabListRecord]`; `derive_lab_status(remarks: str) -> tuple[str, str]`; `sync_lab_scope(conn, fetcher, doc_nos: list[str]) -> dict`.

- [ ] Tests: 20 rows + pagination from directory snapshot; OSL code, address parts, validity; scope search rows (63 total for 2062 snapshot page 1 → 30 rows, breakup items, remarks/exclusions); Group-1 status derivation ("Suspension revoked … (Present status operative)" → OPERATIVE; latest "Suspended w.e.f." without later revocation → SUSPENDED).

---

## Milestone 6 — Hallmarking

### Task 6.1: AHCs, events, districts, Gazette validation

**Files:** Create `backend/manakmarg/ingest/hallmarking.py`, `backend/manakmarg/reasoning/hallmarking.py` (effective status only in this task), tests.

**Interfaces — Produces:** `parse_ahc_list(html) -> list[AhcRecord]`; `parse_ahc_events(html) -> list[AhcEventRecord]`; `parse_phasewise_districts(pdf_path) -> list[DistrictRecord]`; `parse_gazette_annex(pdf_path) -> list[tuple[str, str]]`; `validate_against_gazette(records, annex) -> GazetteValidation`; `effective_ahc_status(list_status: str, validity: date | None, events: list[AhcEventRecord], today: date) -> tuple[str, list[str]]`.

- [ ] Tests: label-structured details parsing; scope gold/silver flags; 124 suspensions cross-list; phase headers incl. "Order Dated 4th April, 2022"; 392 rows; state normalization; Gazette annex parsing; effective status matrix (Operative+valid+no event → OPERATIVE; expired validity → EXPIRED_VALIDITY; event CANCELLED → CANCELLED; "Under Suspension(Gold Only)" → SUSPENDED_GOLD_ONLY; Deferred → NOT_OPERATIVE).

---

## Milestone 7 — Pipeline and search indexes

### Task 7.1: Pipeline orchestration + CLI

**Files:** Create `backend/manakmarg/ingest/pipeline.py`, extend `__main__.py`, test `backend/tests/ingest/test_pipeline_offline.py` (fixtures).

**Interfaces — Produces:** `run_pipeline(conn, fetcher, steps: list[str] | None = None) -> dict`; step names: `standards`, `schemes`, `psg`, `documents`, `pages`, `labs`, `lab_scope`, `hallmarking`, `quality`.

### Task 7.2: FTS search, LSA vectors, hybrid product matching

**Files:** Create `backend/manakmarg/search/{fts_search,vectors,hybrid}.py`, `backend/manakmarg/search/synonyms.json`, tests.

**Interfaces — Produces:** `fts_search.fts_query(text: str) -> str`; `search_standards(conn, q, *, types=None, limit=20) -> list[Hit]`; `search_coverage(conn, q, limit=20) -> list[Hit]`; `search_guidelines(...)`; `search_faq(...)`; `search_chunks(...)`; `vectors.VectorIndex.build(ids, texts) / .save(dir, name) / .load(dir, name) / .query(text, k) -> list[tuple[str, float]]`; `hybrid.find_product_matches(conn, text: str, *, limit=10) -> ProductMatches(coverage, standards, guidelines, synonyms_used)`.

---

## Milestone 8 — Reasoning and AI layer

### Task 8.1: Evidence, intents, applicability

**Files:** Create `backend/manakmarg/reasoning/{__init__,evidence,intents,applicability}.py`, tests.

**Interfaces — Produces:** `Evidence` model + `EvidenceBuilder.add(**fields) -> str`; `QueryUnderstanding(intent, intents, is_refs, location, scheme_ids, product_text, language)`; `understand(query: str) -> QueryUnderstanding`; `assess(conn, *, product_text: str | None, std_key: str | None, coverage_id: int | None, today: date) -> Assessment(label, standards, listings, compulsory, evidence, caveats)`.

### Task 8.2: Journey, labs, hallmarking services

**Files:** Create `backend/manakmarg/reasoning/{journey,labs}.py`, complete `reasoning/hallmarking.py`, tests.

**Interfaces — Produces:** `build_journey(conn, *, product_text=None, std_key=None, coverage_id=None, location=None, lang="en", today=None) -> Journey(steps: list[JourneyStep], evidence, sources, next_actions, caveats)`; `find_labs(conn, ref: str, *, state=None, district=None, city=None, today=None) -> LabSearchResult`; `check_district(conn, district: str, state: str | None = None) -> DistrictCheck`; `find_ahcs(conn, *, state=None, district=None, include_inactive=False, today=None) -> AhcSearchResult`.

### Task 8.3: Composer, i18n, assistant, optional Claude

**Files:** Create `backend/manakmarg/reasoning/{i18n,composer,assistant}.py`, `backend/manakmarg/llm/{__init__,client,guardrails,prompts}.py`, tests (LLM mocked). Read the `claude-api` skill before writing `llm/`.

**Interfaces — Produces:** `answer(conn, query: str, *, lang: str = "en", today=None, llm=None) -> AssistantResponse`; `LLMClient.from_settings(settings) -> LLMClient` with `.enabled`, `.narrate(payload: dict, lang: str) -> str | None`, `.parse_query(query: str) -> dict | None`; `guardrails.validate_narrative(text: str, evidence_ids: set[str], allowed_identifiers: set[str]) -> GuardrailResult(ok, problems)`.

---

## Milestone 9 — Document gap analysis

### Task 9.1: Store, extraction, units, requirement/value extraction, comparison

**Files:** Create `backend/manakmarg/documents/{__init__,store,extract,units,requirements,values,compare,gap}.py`, `backend/manakmarg/demo/samples/` generator, tests.

**Interfaces — Produces:** `SessionStore(root: Path, ttl_minutes: int, max_bytes: int)` with `.create() -> str`, `.add_file(session_id, filename, data: bytes, role: str) -> StoredFile`, `.files(session_id) -> list[StoredFile]`, `.delete(session_id) -> None`, `.purge_expired() -> int`; `extract_document(path: Path) -> ExtractedDoc(pages: list[PageText], tables: list[TableRows])`; `units.parse_quantity(text) -> Quantity | None`, `units.to_base(value, unit) -> tuple[float, str]`; `extract_requirements(doc) -> list[Requirement]`; `extract_values(doc, role) -> list[ProductValue]`; `compare_all(requirements, values) -> list[GapRow]`; `analyze_session(store, session_id) -> GapReport`.

- [ ] Tests: operator/number/unit parsing ("not less than 50 mm", "≥ 0.5 mm", "Min 2.5 %", table Min/Max), unit conversions (cm→mm, kg→g, MPa↔N/mm²), status matrix (datasheet vs test report, unmatched → INSUFFICIENT EVIDENCE, unit mismatch → UNKNOWN), TTL purge, size/extension validation.

---

## Milestone 10 — API

### Task 10.1: FastAPI app and routers

**Files:** Create `backend/manakmarg/api/{__init__,app,deps,schemas}.py`, `backend/manakmarg/api/routers/*.py`, `backend/manakmarg/reports/compliance_report.py`, tests `backend/tests/api/test_api.py` (fixture DB built from test fixtures).

**Interfaces — Produces:** `create_app(settings: Settings | None = None) -> FastAPI` exposing the endpoints in spec §12; static serving of `frontend/dist` when present.

---

## Milestone 11 — Frontend

### Task 11.1: App shell, API client, i18n, design system
### Task 11.2: Navigator + Assistant
### Task 11.3: Compliance Journey + printable report
### Task 11.4: Standards explorer + Certification & QCOs
### Task 11.5: Testing & Labs + Hallmarking
### Task 11.6: Gap Analysis + Sources & Data Health

Each: build passes (`npm run build`), type-check passes, page verified in the in-app browser against the running API.

---

## Milestone 12 — Data run, demo, documentation, verification

### Task 12.1: Full ingestion + validation report (online once, then `--offline` reproducible)
### Task 12.2: Demo scenarios verified end-to-end (manufacturer, gap analysis, hallmarking, lab search; EN + HI)
### Task 12.3: Documentation set (see File Structure) + README
### Task 12.4: Final verification — full pytest run, frontend build, API smoke tests, UI walkthrough

---

## Self-review

- Spec coverage: §5 tables → Tasks 1.2/2.3/3.3/4.x/5.1/6.1; §6 rules → 2.1/2.2; §7 ingestion → 1.3/7.1/2.4; §8 retrieval → 3.3/7.2; §9 reasoning → 8.x; §10 AI → 8.3; §11 gap analysis → 9.1; §12 API → 10.1; §13 UI → 11.x; §14 security → 1.1/9.1/10.1; §15 tests → every task; §16 limitations → 12.3 + UI Sources page.
- Interface names are used consistently across tasks (`RunRecorder.upsert`, `parse_designation`, `StandardResolver.resolve`, `find_product_matches`, `build_journey`, `analyze_session`).
