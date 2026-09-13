# MANAK MARG — Design Specification

- **Date:** 2026-09-13
- **Team / event:** ForgeScript · Smart India Hackathon 2026 · PS26107
- **Status:** Adopted for implementation. The project brief delegates engineering and UX decisions to the build team ("You are responsible for making the engineering decisions"), so this spec records decisions rather than waiting for sign-off. It stays open for revision.

---

## 1. Purpose

MANAK MARG is a **BIS compliance navigator**: an evidence-first reasoning layer over official Bureau of Indian Standards (BIS) information. For a product, question, or uploaded document it answers **what applies, why, whether it is compulsory, what is needed, where to go, and what to do next** — always with official sources and dates, and with explicit uncertainty.

### Goals

| # | Goal |
|---|------|
| G1 | Evidence-backed answers for: applicable Indian Standard (IS), compulsory status, QCO, certification scheme, enforcement date, Product Manual / SIT / grouping guidance, tests, laboratories, process, hallmarking, next step. |
| G2 | Legal / compulsory status, dates and eligibility decided by **deterministic rules over official records** — never by semantic similarity or an LLM. |
| G3 | Every record traceable to a registered source, file/URL locator, ingestion run and retrieval time. Coverage and limitations reported honestly. |
| G4 | Four end-to-end demo flows (manufacturer journey, document gap analysis, hallmarking, lab search) in English and Hindi. |
| G5 | Re-runnable ingestion with run history, change detection and data-quality reports. |

### Non-goals (prototype)

- Mirroring the entire BIS ecosystem or crawling every document.
- Bulk downloading Indian Standard PDFs, or bypassing CAPTCHA, authentication, HTTP 403, DRM/FileOpen, anti-devtools or undocumented APIs.
- Production auth, multi-tenancy, legal advice.

---

## 2. Discovery summary

### 2.1 Supplied Excel workbooks (`data/`, untouched raw inputs)

All 20 workbooks share one layout: sheet `Published Standards`; row 1 = title cell (C1:E1 merged) + "Generated On" timestamp (F1); row 2 = headers `Sl# | Standard Number | Date of Publish | Title | Type of Standard | Degree of Equivalence`; trailing empty columns.

| File(s) | Title cell | Rows | Interpretation |
|---|---|---|---|
| `1.xlsx` (gen. 2026-09-12 20:17) | `Total` | 24,014 (all unique) | Full published list — most likely the Department-wise view's "Total" export. **Master list.** |
| `2.xlsx` (gen. 20:32) | *(empty)* | 23,883 (23,844 unique) | Full list from a second view — most likely Group-wise: 39 repeated designations with identical fields (multi-group membership); 171 designations absent (many recent amendments / type "-", i.e. not group-assigned); 1 extra designation `IS 4020 (Part 8):1998`. All shared designations have identical fields. |
| 18 × `File_Published_Standards_List_*.xlsx` (gen. 20:34–20:38) | `Department of Atomic Energy`, `Ministry of Agriculture`, … `Ministry of Communications - Department of Telecommunications (DOT)` | 1 – 1,935 each | **Ministry-wise** exports, alphabetical A → "Communications" (partial). 5,443 distinct standards; 1,010 appear under >1 node. Parent-ministry lists and "Ministry – Department" lists are largely disjoint (not subsets). |

**Not present in any supplied file:** a per-row BIS Department or Group column. Department/Group classification therefore cannot be derived from supplied data (the title cells of `1.xlsx`/`2.xlsx` are totals). The brief's statement that "Ministry-wise is unavailable" is partially superseded: 18 ministry/department nodes *are* available.

**Data-quality observations (master + group exports):**

- 386 null publish dates; `Type of Standard = "-"` ×107; `Degree of Equivalence = "-"` ×507.
- 133 distinct designation "shapes". Variants include `IS 1489 (Part 1)  : 2015`, `IS 10052 : Part 1 : Sec 6 : 2022`, `Is 18889:2024`, `IS ISO 6204:2024`, `IS/IEc 62232:2022`, `IS/IEC/IEE 63195 (Part 1):2022`, `IS/ISO/IECTR 20226:2025`, `IS/ISO 80000-9:2019`, `IS/ISO 105-E04:2013`, `IS/IEC 60371_3_9:1995`, `IS 802.15.4:2021`, `IS 504 (Part 1 To 12):2002`, `IS 4864 to 4870:1968`, `IS 6560:2017:2017`, `IS 16910 (Part 2/Sec 11)2026`, `IS 6882:2026 P`, `IS 19877T:2026`, `IS H16500:2012` (Hindi edition), `SP 25(S&T):1984`, `ISO/SAE 21434:2021`, `IEC 61000 (Part 5/Sec 2):2026`, and malformed `IS):7779 ( (Part 1/Sec 1)):1975`, `IS/IEC 60794 (Part 1):Sec):1):2023`.
- 611 numbers exist under more than one prefix (e.g. `IS 13450` vs `IS/ISO 13450`) → **prefix is part of identity**.
- ISO-style hyphen parts (`IS/ISO 80000-9`) never collide with a `(Part n)` form of the same family → safe to map for *matching*.
- 438 families list more than one version (e.g. `IS 10325:2000` and `IS 10325:2026`).
- 81 normalized titles are shared by more than one designation (revisions, indigenous vs adopted, one probable typo `IS/IEC 611196`).
- Titles carry revision / amendment markers (`(Third Revision)`, `Amendment - 1`).
- 10 designations listed under ministries are absent from both master exports (e.g. `IS 7328:2020` — superseded by `IS 7328:2026`).

### 2.2 Official web sources inspected (2026-09-12/13)

| Source | Structure found | Access |
|---|---|---|
| Scheme I page | Two copies of the table: `div.schdesktop` (current) and `div.mobile` (lags; 227 differing lines). 909 rows; notification column uses `rowspan`; category header rows (colspan); a section "Food & Related Products De-notified from compulsory BIS certification" whose product names also say "De-notified…"; an IS 302 (Part 1) row with an illustrative list of ~90 appliances; ~1,500 QCO/amendment PDF links. | OK |
| Scheme II page | 4 section tables (Electronics & IT goods CRS; Solar PV; chemicals; textiles). Notification cells with orders, "Subsequent Amendments", "Superseded by … Order, 2021". | OK |
| Scheme IV page | Desktop table: 2 products; essential requirements quoting IS clauses (e.g. "Clause 4.2.2 of IS 10613: 2023"). | OK |
| Scheme X page | Table 0: LV switchgear & controlgear (32 rows, *Specific Requirement* column; deferment S.O. 5038(E) dated 6 Nov 2025). Table 1: machinery under Omnibus Technical Regulation (20 categories); its notification cell lists **"Rescind … Order, 2024. S.O. 239(E) Dated 16 January, 2026"**. | OK |
| Upcoming QCOs | 28 numbered entries (Ministry/Department, Product, IS, Enforcement date 30 Sep 2026 → 05 Jun 2027); entry 13 (`IS 302 (Part 1) : 2024 IEC 60335-1:2020`) spans 91 rows with an illustrative appliance list. Some IS cells lack the "IS" prefix (`4003 (Part 1):1978`). | OK |
| Product Specific Guidelines | 1,646 rows `IS No. | Title | Size | Format | View/Download`. Nearly all are Product Manuals; grouping guidelines and SIT are **annexes inside PMs** (sample PM for IS 14756: sampling, Annex A grouping, B test equipment, C SIT, D scope of licence). Some PDFs return HTTP 403 (e.g. `/PDF/cart/PM_IS_2062.pdf`). | OK / some 403 |
| Certification process, Apply for licence, FAQs (certification 28, laboratory 10, hallmarking general 25, hallmarking mandatory) | WordPress content in `div.who_we_area`; FAQs as `.accordion` / `.panel` pairs; 9-step licence table. | OK |
| LIMS (`lims.bis.gov.in`) | Recognised-lab directory (22 pages × 20), BIS labs (10), empanelled labs (140), lab scope pages (30 rows/page with clause-wise charge breakup), **IS-wise search** (GET `?is_number__doc_no=2062` → 63 scope rows with lab, OSL code, IS version, grade, charges, validity, remarks such as `Exclusion: …`). Pages are 1–3 MB. | OK (no CAPTCHA) |
| Group-1 recognised labs PDF | 38 pp, header "as on 24-08-2026" (URL path 2026/06): lab, state, private/govt, OSL code, recognition validity, suspension/revocation history. | OK |
| Group-2 empanelled labs PDF | 24 pp, "as on 07-08-2026": lab, state, govt, OSL code. | OK |
| AHC list (manakonline) | 1,650 centres: recognition no., validity, name, address, scope ("Gold & Silver Both"), contact, status (Operative 1,514; Under Suspension 124; Deferred 5; Under Suspension (Gold Only) 4; Deferment Letter Generated 3). | OK |
| Cancelled/Expired/Suspended AHCs (huid.manakonline) | 731 rows: recognition no., name & address, region, type, date, current status (CANCELLED 607; UNDER SUSPENSION 124 — all 124 also flagged in the main list). | OK |
| Mandatory hallmarking districts | Nov-2024 PDF (older). **2026-09 phase-wise PDF**: 392 districts in 8 phases — 256 (23 Jun 2021), 32 (order 4 Apr 2022), 55 (6 Sep 2023), 18 (5 Nov 2024), 12 (31 Jul 2025), 7 (2 Mar 2026), 5 (28 Apr 2026), 7 (3 Aug 2026). Gazette S.O. 4345(E) dated 3 Aug 2026 substitutes the full Annexure (English from p. 12) → cross-validation source. | OK |
| Licensed jewellers report (huid.manakonline) | Form requires **CAPTCHA** + CSRF. | **Not ingested** — official link only |
| standards.bis.gov.in | Angular SPA with an anti-devtools script; data behind an undocumented API; sitemap has no per-standard URLs. | **Not used** (hidden/private API constraint) |
| BIS copyright policy | Website material may be reproduced free of cost if accurate, not misleading, and with prominent source acknowledgement; excludes third-party copyright material. Terms/Disclaimer: website content is not a statement of law; English prevails over translations. | — |

---

## 3. Decisions and alternatives considered

| ID | Decision | Alternatives and why not |
|---|---|---|
| D1 | **SQLite 3.50 (FTS5 + JSON1) via SQLAlchemy Core**, schema kept portable to PostgreSQL. | PostgreSQL (brief's preference): not installed and no Docker on the build machine; SQLite keeps the prototype self-contained and demo-safe. Migration path: same metadata; FTS5 → `tsvector`/`pg_trgm` adapter. |
| D2 | **Structured-first hybrid retrieval**: identifier resolvers + SQL filters + FTS5 BM25 + corpus-trained LSA vectors + curated synonyms; neural embeddings pluggable (GPU available, model download deferred). | Vector-DB-first RAG: poor for identifiers, dates and statuses; brief forbids vector store as source of truth. |
| D3 | **Deterministic reasoning core**; Claude (optional, via `ANTHROPIC_API_KEY`) only for intent-parsing fallback, narrative wording and Hindi phrasing, behind identifier/citation guardrails. Full functionality without a key. | LLM-first answers: hallucination risk on legal status and requirements. |
| D4 | **React + TypeScript + Vite + Tailwind SPA**, served by FastAPI after build. | Server-rendered Jinja/HTMX: simpler, but weaker for interactive journey, evidence drawers and gap-analysis views. |
| D5 | **Lab scope**: LIMS directories + Group-1/2 PDFs for all labs; IS-wise scope fetched for a curated set of demo IS families plus an incremental, rate-limited `sync` command. | Full crawl of every lab scope (hundreds of 1–3 MB pages): unnecessary load on BIS systems for a prototype. |
| D6 | **Official PDFs** downloaded only where needed (QCOs and PMs for demo families, district lists, lab lists), cached under `data/raw/` (git-ignored). UI links to official URLs; snippets ≤ 300 characters with attribution. | Re-hosting documents: redistribution rights unclear. |
| D7 | **Standard identity**: `std_key` = prefix + number + part/section + suffix + year; `family_key` drops the year; `match_key` additionally maps ISO-style hyphen parts to `(Part n)`. Prefix is never ignored. Canonical collisions are reported, never merged. | Number-only keys: would merge `IS 13450` with `IS/ISO 13450`. |
| D8 | **Classification nodes**: ministry nodes from the 18 exports (flagged partial). Department/Group dimensions nullable with an ingestion path for future official exports. | Inferring ministry/department from titles: forbidden (fabrication). |
| D9 | **Privacy by minimisation**: store organisation phone/e-mail as published; do not store contact-person names; user uploads live in per-session temp storage with TTL deletion and are never logged. | Storing full contact blocks: unnecessary personal data. |

---

## 4. Architecture

A modular monolith.

```
                      ┌──────────────────────── React SPA (frontend/) ───────────────────────┐
                      │ Navigator · Assistant · Journey · Standards · Certification · Labs  │
                      │ Hallmarking · Gap Analysis · Sources & Data Health · Report          │
                      └───────────────────────────────▲──────────────────────────────────────┘
                                                      │ JSON (REST)
┌──────────────── backend/manakmarg ──────────────────┴──────────────────────────────────────────┐
│ api/        FastAPI routers (standards, compliance, labs, hallmarking, faq, assistant,         │
│             documents, reports, sources)                                                        │
│ reasoning/  intent & entities · applicability · journey · lab matcher · hallmarking advisor ·  │
│             evidence assembler · response composer (EN/HI templates)                            │
│ llm/        optional Claude client · prompts · guardrails (identifier whitelist, citations)     │
│ documents/  upload store (TTL) · text/table extraction · requirement & value extraction ·       │
│             units · comparator · gap report                                                     │
│ search/     resolvers (IS, product, district, lab) · FTS5 · LSA vectors · hybrid ranker         │
│ ingest/     source registry · polite fetcher/cache · per-source parsers · pipeline runner ·      │
│             validation & data-quality report · inventory                                        │
│ normalize/  IS designations · dates · text · geography · notification-status rules             │
│ db/         SQLAlchemy Core schema · engine · FTS setup                                          │
│ core/       config · logging · clock · paths                                                     │
└──────────────────────────────────────────────▲─────────────────────────────────────────────────┘
                                               │
   data/*.xlsx (raw, untouched) · data/raw/web (HTML/PDF snapshots) · data/staging (JSONL)
   data/processed/manakmarg.sqlite3 · data/indexes · data/manifests (sources.json, inventory)
```

**Data flow for a question:** request → intent & entity extraction (rules; LLM fallback) → resolvers (IS numbers, districts, schemes) → candidate retrieval (coverage listings, standards, guidelines, FAQs) → deterministic applicability & status → domain lookups (orders, PM sections, labs, AHCs, districts) → evidence assembly (every claim cites evidence IDs) → composer (templates; optional LLM narrative checked against evidence) → structured response with sources, caveats and next actions.

---

## 5. Data model

Every domain table carries provenance columns: `source_id`, `run_id`, `source_locator` (file/sheet/row or URL#table/row), `retrieved_at`, plus `first_seen_run`, `last_seen_run`, `is_current` for snapshot-style sources.

### 5.1 Provenance

- **`source`** — `source_id` (slug), `name`, `publisher`, `domain`, `url`, `source_type` (excel_export · html_table · html_page · pdf_document · web_report), `purpose`, `ingestion_method`, `authority` (official_primary · official_secondary · curated · derived), `access_status` (ok · partial · captcha_blocked · access_denied · not_used · unavailable), `document_type`, `copyright_notes`, `access_notes`, `last_checked`, `as_of_label`.
- **`ingestion_run`** — `run_id`, `source_id`, `started_at`, `completed_at`, `status`, `records_seen`, `inserted`, `updated`, `unchanged`, `retired`, `rejected`, `errors_json`, `notes`, `code_version`.
- **`raw_artifact`** — `artifact_id`, `source_id`, `run_id`, `uri`, `local_path`, `retrieved_at`, `http_status`, `content_type`, `bytes`, `sha256`.
- **`document`** — `document_id`, `source_id`, `url`, `source_page_url`, `title`, `doc_type` (qco_order · qco_amendment · qco_extension · qco_deferment · qco_rescission · gazette · product_manual · certification_guideline · hallmarking_order · district_list · lab_list), `language`, `doc_date`, `retrieved_at`, `sha256`, `pages`, `text_status` (metadata_only · extracted · access_denied · failed · no_text), `local_path`.
- **`document_chunk`** — `chunk_id`, `document_id`, `page_start`, `page_end`, `section_key`, `heading`, `text`, `ordinal` (+ FTS5 mirror).

### 5.2 Standards

- **`standard`** — `standard_id`, `std_key` (unique), `family_key`, `match_key`, `number_key`, `designation_raw`, `prefix`, `number`, `part`, `section`, `subsection`, `year`, `suffix`, `title`, `title_clean`, `revision_label`, `amendment_label`, `publication_date`, `standard_type`, `degree_of_equivalence`, `listing_status` (published_export · ministry_export_only), `in_master_export`, `in_second_export`, `quality_flags` (JSON).
- **`standard_alias`** — every raw representation encountered anywhere (Excel, schemes, PSG, LIMS, QCO pages) with `context`, `resolution` and resolved `standard_id`/`family_key`.
- **`classification_node`** — `node_id`, `dimension` (ministry · department · group), `name`, `parent_node_id`, `export_label`.
- **`standard_classification`** — (`standard_id`, `node_id`) + provenance.
- **`standard_relation`** — `from_standard_id`, `to_standard_id` / `to_ref_text`, `relation_type` (newer_version_in_family · same_title_other_designation · international_equivalent · referenced_in_requirement · amendment), `basis` (official_source · deterministic_rule), `evidence_text`.

### 5.3 Compulsory certification

- **`certification_scheme`** — `scheme_id` (SCHEME_I · SCHEME_II · SCHEME_IV · SCHEME_X · HALLMARKING), `name`, `official_description` (quoted from BIS pages), `official_url`.
- **`regulatory_order`** — one row per linked order/notification: `title`, `order_kind` (qco · amendment · extension · deferment · rescission · corrigendum · superseding_order · rules · other), `so_number` / `gsr_number`, `order_date`, `issuing_authority`, `url`, `document_id`, `raw_text`.
- **`scheme_coverage`** — one row per listed product line: `scheme_id`, `section_label`, `category`, `sr_no_raw`, `product_name`, `parent_coverage_id` (illustrative sub-items), `standard_ref_raw`, `standard_title_raw`, `product_category`, `essential_requirement` (IV), `specific_requirement` (X), `notification_text_raw`, `listing_status` (LISTED_COMPULSORY · DENOTIFIED · RESCINDED · UPCOMING · NEEDS_VERIFICATION), `status_basis` (quoted text), `ministry_department`, `enforcement_date`, `enforcement_date_raw`, `notes`.
- **`coverage_standard`** — `coverage_id`, `ref_raw`, `family_key`, `standard_id`, `resolution` (exact_version · family_latest · family_ambiguous · version_not_in_master · unresolved), `role` (specified · referenced_in_requirement · type_a · type_b_c).
- **`coverage_order`** — `coverage_id`, `order_id`, `ordinal`, `relation`.
- **`product_term`** — `term`, `term_norm`, `origin` (coverage_product · coverage_category · illustrative_item · psg_title · curated_synonym), `coverage_id` / `standard_id`, `weight`.

### 5.4 Guidelines and process

- **`product_guideline`** — `is_ref_raw`, `family_key`, `standard_id`, `title`, `doc_kind` (PRODUCT_MANUAL · PRODUCT_MANUAL_WITH_SIT · OTHER), `size_text`, `url`, `document_id`, `parse_status`.
- **`guideline_section`** — `guideline_id`, `section_key` (product · sampling · raw_material · grouping · sample_size · test_equipment · sit · tests_per_day · scope_of_licence · other_guidelines · marking), `heading`, `page_start`, `page_end`, `text`, `structured_json`.
- **`process_step`** — `scheme_id`, `ordinal`, `text`, `link_url` (Apply-for-licence table).
- **`scheme_document`** — scheme guideline documents listed on the certification-process page.

### 5.5 Laboratories

- **`laboratory`** — `osl_code`, `lims_lab_id`, `name`, `lab_category` (BIS_LAB · BIS_RECOGNISED · GOVT_EMPANELLED), `address_raw`, `city`, `district`, `state`, `pincode`, `org_phone`, `org_email`, `lims_validity_date`, `recognition_valid_upto` (Group-1), `ownership` (Private/Govt.), `status_remarks_raw`, `derived_status` (OPERATIVE · SUSPENDED · UNKNOWN) with `status_basis`.
- **`lab_scope`** — `lab_id`, `lab_name_raw`, `osl_code_raw`, `is_ref_raw`, `family_key`, `standard_id`, `version_year`, `product`, `grade_type`, `charges_total`, `validity_date`, `remark_raw`, `exclusions_text`, `scope_file_url`.
- **`lab_scope_item`** — `scope_id`, `clause`, `parameter`, `exclusion`, `charge`, `remark`.

### 5.6 Hallmarking

- **`ahc`** — `recognition_no` (unique), `region_code`, `name`, `address_raw`, `district`, `area`, `state`, `pincode`, `scope_text`, `gold`, `silver`, `validity_date`, `list_status_raw`, `org_phone`, `org_email`.
- **`ahc_status_event`** — `recognition_no`, `status` (CANCELLED · UNDER SUSPENSION), `event_date`, `region`, `center_type`, `name_address_raw`.
- **`hallmarking_district`** — `sr_no`, `state_raw`, `state`, `district_raw`, `district`, `phase_no`, `phase_label`, `phase_order_date`, `gazette_validated`, `gazette_state_raw`, `gazette_district_raw`.
- **`district_alias`** — `alias`, `district_id`, `basis` (official_variant · curated_rename).
- **`jeweller`** — schema only; source `captcha_blocked`.

### 5.7 Knowledge

- **`faq`** — `category`, `question`, `answer`, `answer_links`, `ordinal`, `language`, `source_url` (+ FTS5 mirror).

### 5.8 Derived status is computed, never stored as truth

AHC operability, lab validity and upcoming-QCO effectiveness depend on "today". Stored data keeps raw statuses and dates; services compute effective status against an injectable clock and always display the source date.

---

## 6. Normalization rules

### 6.1 IS designations (`normalize/is_number.py`)

1. NFKC; unify dashes (– — ‑) to `-`; collapse whitespace; strip stray punctuation patterns (`)):`, `):)`, doubled `:YYYY:YYYY`).
2. **Multi-reference split**: `IS 13422: 2024 / ISO 10282: 2023` → primary `IS 13422:2024` + international ref `ISO 10282:2023`; `IS 14286 IS/IEC 61730 -1 IS/IEC 61730 -2` → three references (`extract_designations` scans text).
3. **Prefix**: tokens from {IS, ISO, IEC, IEEE, CISPR, QC, TS, TR, PAS, IWA, GUIDE, SAE, SP} case-insensitively; repairs flagged (`IS ISO`→`IS/ISO`, `IS/IEc`→`IS/IEC`, `IECTR`→`IEC/TR`, `IEE`→`IEEE`, `IS/IEC TS`→`IS/IEC/TS`). No prefix + digits in an IS-only context (QCO tables, upcoming list) → `IS` with flag `prefix_assumed`.
4. **Number**: `[A-Z]?\d+(?:\.\d+)*[A-Z]?` (covers `H16500`, `802.15.4`, `19877T`); ranges `4864 to 4870` kept as range flag.
5. **Part/Section**: `(Part n[/Sec m[/Sub-Sec k]])`, `(Pt n)`, `(PART n)`, `: Part n : Sec m :`, bare `Part n`, part lists/ranges (`Part 1 to 9`, `Part 1 AND 2`), ISO letter-coded parts (`Part C12`, `105-E04`), underscore parts (`60371_3_9`).
6. **Year**: `:YYYY`, ` (YYYY)` (LIMS), `)YYYY` (missing colon); year outside 1900…current+1 flagged `year_out_of_range`; raw retained.
7. **Suffix**: residue such as `P`, `T`, `Supplement`, `(S&T)` kept in the key and flagged.
8. Keys: `std_key = "PREFIX NUMBER (Part …/Sec …)SUFFIX:YEAR"`; `family_key` = without year; `match_key` = family with hyphen parts mapped to `(Part n)` and suffix removed; `number_key` = number.
9. **Resolution** (`resolve(ref)`): exact `std_key` → `match_key` + year → family (no year: latest version = `family_latest`; parts missing but family has parts = `family_ambiguous`) → prefix-insensitive number match only as a flagged candidate. Every resolution is recorded in `standard_alias`.
10. **Uniqueness guard**: two different raw master designations producing one `std_key` → both kept (`#2` disambiguator) and reported as `canonical_collision`.

### 6.2 Dates

`04 Aug 2026`, `30 September 2026`, `01 October, 2026`, `23rd June, 2021`, `31/07/2028`, `14.02.2027`, `17-11-2017`, `31 Dec, 2026`, `w.e.f.12.03.2025` → ISO dates via an explicit format list; failures keep raw text and add a data-quality entry. No locale guessing for ambiguous numeric dates: BIS sources are DD/MM/YYYY.

### 6.3 Text

Title cleanup (whitespace, dash unification) while preserving `title` raw; `revision_label` (`(Second Revision)`), `amendment_label` (`Amendment - 1`); product-name normalization for matching (lowercase, punctuation → space, singularisation of simple plurals, stop-words like "specification", "requirements").

### 6.4 Geography

Curated state map (`U.P.`→Uttar Pradesh, `M.P.`→Madhya Pradesh, `W.B.`→West Bengal, `Tamilnadu`→Tamil Nadu, `Chhattisgargh`→Chhattisgarh, `PONDICHERY`/`Pondicherry`→Puducherry, …). District names keep the official spelling; `district_alias` adds curated renames (Gurgaon↔Gurugram, Allahabad↔Prayagraj, Hissar↔Hisar, Rohatak↔Rohtak, Bangalore↔Bengaluru Urban, …) flagged as matching aids. Address parsing for AHC (`…, DISTRICT, AREA, STATE ,PIN`) and LIMS (`…, City, District, State, India - PIN`).

### 6.5 Notification status rules (`normalize/status_rules.py`)

Quoted-text rules applied to category, product and notification cells:

| Evidence text | Coverage status |
|---|---|
| category or product contains `De-notified` | DENOTIFIED |
| notification contains `Rescind` / `rescinded` | RESCINDED (verify) |
| row comes from the Upcoming-QCO page | UPCOMING (effective status computed from date) |
| otherwise on a compulsory-certification scheme page | LISTED_COMPULSORY |

Order kinds from anchor text: `Amendment`, `Extension`, `Deferment`, `Rescind`, `Corrigendum`, `Superseded by`. Dates and S.O./G.S.R. numbers extracted by regex. The status basis (quote + page + retrieval date) is stored and shown.

---

## 7. Ingestion, provenance and updates

- **Source registry** in code (`ingest/sources.py`) → exported to `data/manifests/sources.json` and the `source` table.
- **Fetcher**: identifies as `ManakMarg-SIH2026-Prototype`, respects robots.txt, ≥2.5 s between requests per host, retries with backoff for 5xx/timeouts only, **stops on 401/403/CAPTCHA** (recorded as `access_denied`), content cache keyed by URL with sha256, `--offline` mode that replays cached snapshots.
- **Stages per run**: fetch → `raw_artifact` → parse → `data/staging/<source_id>/<run_id>.jsonl` → validate → normalize → upsert with record hash (inserted/updated/unchanged) → retire records not seen in a full snapshot (`is_current = 0`, history kept) → run summary.
- **CLI** (`python -m manakmarg …`): `init-db`, `ingest <source|all> [--offline]`, `sync-lab-scope --is 2062 --is 269`, `fetch-documents --family "IS 14756"`, `build-index`, `validate`, `inventory`, `serve`.
- **Validation / data-quality report** (`data/manifests/data_quality.json` + Markdown): parse failures, designation flags, canonical collisions, unresolved references, orphan rows, FK checks, date failures, URL well-formedness, cross-source checks (AHC 124 suspensions in both lists; 392 districts vs Gazette annex; LIMS "N Results" vs rows parsed).

---

## 8. Retrieval

- **Resolvers** (exact): IS designations, scheme names, district/state, OSL code, AHC recognition number, S.O. numbers.
- **FTS5 BM25** tables: `standard_fts` (key variants, title), `coverage_fts` (product, category, requirements, standard refs, illustrative items), `guideline_fts`, `faq_fts`, `chunk_fts`, `lab_fts`, `ahc_fts`.
- **LSA vectors** (TF-IDF word + char n-grams → TruncatedSVD) per corpus, trained on the local corpus, saved under `data/indexes/`. Optional sentence-transformer embeddings behind the same interface.
- **Hybrid ranking**: `score = w_bm25·norm(bm25) + w_vec·cos + w_type·type_prior + w_listing·is_listed + w_exact·exact_hit`, weights per intent. Scores are used **only to order candidates**, never to decide status.
- **Curated synonyms** (e.g. "steel vessels / bartan" → stainless steel utensils; "LPG stove" → domestic gas stoves) stored as `product_term` with `origin = curated_synonym` and shown as "matched via synonym".

---

## 9. Reasoning

### 9.1 Applicability labels

| Label | Rule |
|---|---|
| **CONFIRMED** | User supplied an exact identifier (IS number, coverage selection, recognition no.) and an official record states the fact directly. |
| **LIKELY APPLICABLE** | Product text strongly matches an official compulsory-listing product (normalized token coverage ≥ 0.8 and top rank with margin) or a *Product Specification* standard title. The UI asks the user to confirm the product to upgrade to CONFIRMED. |
| **CANDIDATE** | Weaker lexical/semantic matches. |
| **NEEDS VERIFICATION** | Matched record is DENOTIFIED/RESCINDED, upcoming date passed, version ambiguous, or conflicting matches. |
| **UNKNOWN** | No supporting records. |

Compulsory status statements quote the listing: *"Listed under Scheme I on BIS 'Products under Compulsory Certification' (retrieved 2026-09-12)"*. When no listing matches: *"No compulsory-certification listing found in the indexed BIS pages (as of …). BIS certification is voluntary unless a QCO covers the product — verify on the official page."* Absence is never presented as proof.

### 9.2 Compliance journey builder

Steps are included only when evidence exists: Product understanding → Applicable standard(s) (versions, type, official link) → Compulsory status (listing + QCOs + amendments, enforcement date) → Certification scheme (official description, process documents) → Product Manual (sections: sampling, grouping, SIT, test equipment, scope) → Tests (PM SIT annex; LIMS clause lists labelled "tests labs are recognised for") → Laboratories → Documents & application (apply-for-licence steps, manakonline) → Next actions → Sources. Missing steps become explicit "not available in indexed data" notes.

### 9.3 Laboratory matching

IS family → LIMS scope rows (version, grade, charges, validity, remarks, exclusions) → join lab directory (address, state, district, category) and Group-1 status → filter by location (state/district; city text match; nearest-state fallback labelled) → rank: exact version > family; valid > unknown > expired; no exclusions > exclusions; BIS/Govt labs flagged. Never claims capability beyond the scope row; exclusions shown verbatim.

### 9.4 Hallmarking advisor

District resolver (official names + aliases + fuzzy with explicit "did you mean") → coverage (phase, order date, Gazette validation) → AHCs in district/state computed as **OPERATIVE only if** list status = "Operative", validity ≥ today, and no cancellation/suspension event; suspended/cancelled centres excluded by default and shown only on request with reasons → jewellers: official report link (CAPTCHA) + guidance → hallmarking FAQs.

### 9.5 Evidence assembly

`Evidence {id, kind, title, snippet ≤ 300 chars, source_id, source_name, url, document_url, page, clause, locator, retrieved_at, authority}`. Every section item lists evidence IDs; the response carries a `sources` roll-up and `caveats`.

---

## 10. AI layer (optional Claude)

- Client configured by `ANTHROPIC_API_KEY` and `MANAKMARG_LLM_MODEL`; disabled cleanly when absent.
- **Uses**: (1) intent/entity JSON when rule confidence is low; (2) narrative summary from the evidence JSON; (3) Hindi phrasing; (4) suggested parameter mappings in gap analysis (labelled "AI-suggested, verify").
- **Guardrails**: prompt forbids facts outside evidence; output identifiers (IS/S.O./recognition numbers, dates) are checked against the evidence whitelist — any unknown identifier invalidates the narrative (fallback to template); citations `[E#]` must reference provided evidence; technical identifiers protected with placeholders during translation.
- **No-key mode**: deterministic EN/HI templates produce the same structured answer.

---

## 11. Document gap analysis

1. Session upload (PDF, DOCX, TXT; ≤ 15 MB each), role per file: *requirement source* (legitimately obtained standard or specification), *product datasheet*, *test report*. Stored in `data/uploads/<session>/`, deleted after TTL (default 2 h) or on request; contents never logged.
2. Extraction with page numbers (PyMuPDF text + `find_tables`; python-docx; plain text).
3. **Requirements** (requirement sources only): normative numeric statements ("shall be not less than 50 mm", "≥ 0.5 mm", table rows with Min/Max) → `{parameter, operator, value, unit, clause, page, raw_text}`; clause = nearest preceding clause number or table/annex label.
4. **Product values** (datasheet/report): `parameter: value unit` pairs and table rows → `{parameter, value, unit, page, raw_text, doc_role}`.
5. **Matching**: normalized parameter names + synonyms + token similarity + unit-dimension compatibility; AI-suggested mappings only when enabled and labelled.
6. **Deterministic comparison** with unit conversion → **PASS**, **POTENTIAL GAP** (declared datasheet value violates, or low-confidence match), **FAIL / NON-CONFORMITY INDICATION** (measured test-report value violates), **UNKNOWN** (unit/format mismatch), **INSUFFICIENT EVIDENCE** (no product value).
7. Each row keeps requirement source (doc, page, clause, quote), product value source (doc, page, quote), comparison and explanation.
8. Demo inputs: clearly labelled *fictional* sample datasheet and test report, and a clearly labelled *demo requirement sheet (not an Indian Standard)*; users can upload a legitimately obtained standard instead. Requirements are never generated by the system.

---

## 12. API (FastAPI, `/api`)

`GET /health`, `GET /meta` (coverage counts, as-of dates, limitations) · `GET /sources`, `GET /sources/{id}`, `GET /ingestion-runs`, `GET /data-quality` · `GET /standards`, `GET /standards/resolve`, `GET /standards/{std_key}` · `GET /compliance/search` (products → listings/standards/guidelines) · `GET /schemes`, `GET /schemes/{id}/coverage`, `GET /coverage/{id}`, `GET /qco/upcoming`, `GET /orders` · `GET /guidelines`, `GET /guidelines/{id}` · `GET /labs`, `GET /labs/{id}`, `GET /labs/for-standard` · `GET /hallmarking/district-check`, `GET /hallmarking/districts`, `GET /hallmarking/ahc`, `GET /hallmarking/jewellers` · `GET /faq` · `POST /assistant/query` · `POST /journey` · `POST /documents/sessions`, `POST /documents/sessions/{id}/files`, `POST /documents/sessions/{id}/analyze`, `DELETE /documents/sessions/{id}` · `POST /reports/compliance`.

---

## 13. UI / UX

Brand: **MANAK MARG — "Your path through Indian Standards & BIS compliance"**, marked as an independent prototype (no BIS logo or imitation of BIS branding). Visual language: calm institutional navy/indigo with a saffron accent, generous whitespace, status chips with consistent semantics (green = confirmed/operative/pass, amber = likely/upcoming/potential gap, red = denotified/rescinded/fail, slate = unknown), "Evidence" drawers everywhere, source dates always visible.

Navigation: **Navigator** (home) · **Assistant** · **Compliance Journey** · **Standards** · **Certification & QCOs** · **Testing & Labs** · **Hallmarking** · **Gap Analysis** · **Sources & Data Health**.

- **Navigator**: one search box ("Describe your product, paste an IS number, or ask a question"), the four pillars DISCOVER · UNDERSTAND · CHECK · COMPLY, demo-scenario cards, live coverage panel with honest counts and as-of dates.
- **Assistant**: structured answer cards (Answer → Why → Evidence → Sources → Next step), intent/entity chips, confidence label, EN/हिं toggle, follow-up suggestions.
- **Compliance Journey**: product confirmation, vertical stepper with status per step, evidence drawers, "Download report".
- **Standards**: fast search with filters (type, equivalence, year, ministry-partial), detail with versions in family, relations, compulsory listings, product manuals, lab count, BIS link.
- **Certification & QCOs**: scheme tabs, coverage tables with status chips, order history, upcoming-QCO timeline with days-to-enforcement.
- **Testing & Labs**: IS + location search, scope cards (version, validity, charges, remarks/exclusions), lab status.
- **Hallmarking**: district checker, AHC finder (operative by default, toggle for suspended/cancelled with reasons), jeweller official link, FAQs.
- **Gap Analysis**: 3-slot upload, results table with status chips and side-by-side evidence.
- **Sources & Data Health**: registry, runs, data-quality findings, limitations.

---

## 14. Security and privacy

Secrets only via environment (`.env`, `.env.example` committed, `.env` ignored); upload validation (extension + magic bytes + size), per-session random IDs, TTL deletion, no content logging, CORS restricted to local origins, no execution of uploaded content, HTML sanitisation of scraped text (rendered as text), rate-limited outbound fetching.

---

## 15. Testing and validation

- **pytest units**: IS parsing/keys/resolution (≥80 cases from real shapes), dates, geography, status rules, order parsing, HTML grid expansion (rowspan/colspan fixtures), each page parser on saved snapshots, Excel ingestion on generated fixtures, AHC effective status, district matching, lab ranking/filtering, unit conversion and comparisons, requirement/value extraction, evidence guardrail, API contract tests with `TestClient`.
- **Integration**: full offline ingest from cached snapshots into a temp DB; count assertions; provenance completeness (no domain row without `source_id`).
- **Validation script**: cross-source checks listed in §7 and spot checks against raw snapshots.

---

## 16. Known limitations (to be shown in the product)

- Standards metadata is from exports generated 2026-09-12; no official per-standard URL is available, so the UI links to the BIS published-standards portal for lookup.
- Ministry classification covers 18 nodes (A → Communications) only; Department and Group classification not available.
- Licensed jewellers cannot be listed (official report requires CAPTCHA).
- Lab scope is indexed for selected IS families; other families link to LIMS IS-wise search.
- Product Manual and QCO text indexed for selected families; others are metadata + official links; some PM PDFs are access-restricted (HTTP 403).
- Web listings are snapshots with retrieval dates; legal status must be verified against the latest Gazette/BIS notifications.
- Gap analysis only compares against requirements present in uploaded documents.

---

## 17. Build sequence

1. Scaffold, config, schema, provenance, fetcher/cache, CLI.
2. IS normalizer + Excel standards ingestion + inventory + data-quality report.
3. HTML grid + scheme parsers (I, II, IV, X, upcoming) + orders + status + resolution.
4. PSG metadata, PM fetch/parse (demo families), process steps, scheme documents, FAQs.
5. Labs: directories, Group-1/2 PDFs, IS-wise scope sync.
6. Hallmarking: AHCs + events, districts + Gazette validation, jeweller placeholder.
7. Search indexes (FTS5, LSA) + resolvers + hybrid ranker.
8. Reasoning: intents/entities, applicability, journey, labs, hallmarking, evidence, composer (EN/HI), optional Claude.
9. Documents: upload, extraction, requirements, comparison, gap report.
10. API routers + tests.
11. Frontend.
12. Demo scenarios, documentation, validation, polish.
