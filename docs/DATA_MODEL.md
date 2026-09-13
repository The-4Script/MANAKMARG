# Data model

Defined in `backend/manakmarg/db/schema.py` (SQLAlchemy Core). Every domain table carries **provenance columns**:
`source_id` (FK to `source`), `run_id` (FK to `ingestion_run`), `source_locator` (file/sheet/row or
`URL#table/row`), `retrieved_at`, `record_hash`, `first_seen_run`, `last_seen_run`, `is_current`.

## Provenance

| Table | Purpose |
|---|---|
| `source` | Registry of every source used or deliberately not used: publisher, URL, type, authority (`official_primary`, `official_secondary`, `curated`, `derived`), access status (`ok`, `partial`, `captcha_blocked`, …), reuse notes, as-of label. Exported to `data/manifests/sources.json`. |
| `ingestion_run` | One row per source per run: status, records seen, inserted/updated/unchanged/retired/rejected, errors, notes, code version. |
| `raw_artifact` | Every fetched response: URL, local cache path, HTTP status, content type, bytes, sha256, cache hit. |
| `document`, `document_chunk` | Official documents (Product Manuals, QCO PDFs, Gazette order, lab lists, web pages) with text status (`parsed`, `text_extracted`, `access_denied`, `fetch_failed`, `no_text_layer`, …) and page-ranged chunks (FTS5 `chunk_fts`). |

## Standards

| Table | Key / notes |
|---|---|
| `standard` | `std_key` unique (prefix + number + part/section + suffix + `:year`); `family_key` (no year), `match_key` (hyphen parts as `(Part n)`), `number_key`; title and cleaned title, revision/amendment labels, publication date, type, degree of equivalence, `listing_status` (`published_export`, `ministry_export_only`), quality flags. |
| `standard_alias` | Every raw designation seen (Excel, scheme pages) with context, resolution kind and resolved standard. |
| `classification_node`, `standard_classification` | Ministry nodes from the 18 ministry exports (parent/child split on " - "). Department and group dimensions exist but are empty: no official data was supplied, and nothing is inferred. |
| `standard_relation` | Reserved for deterministic relations (e.g. newer version in family). |

## Compulsory certification

| Table | Key / notes |
|---|---|
| `certification_scheme` | `SCHEME_I`, `SCHEME_II`, `SCHEME_IV`, `SCHEME_X` with descriptions quoted from BIS pages. |
| `scheme_coverage` | One row per listed product line (`coverage_key` hash). `page_kind`, section, category, product, parent (illustrative items), standard reference as printed, requirement text (Scheme IV/X), `listing_status` (`LISTED_COMPULSORY`, `DENOTIFIED`, `RESCINDED`, `UPCOMING`, `NEEDS_VERIFICATION`) with quoted `status_basis`, ministry/department (upcoming page), enforcement date. |
| `coverage_standard` | Resolved links: `ref_raw`, `family_key`, `standard_id`, `resolution` (`exact_version`, `match_key_version`, `family_latest`, `family_ambiguous`, `version_not_in_master`, `international_reference`, `prefix_mismatch_candidate`, `unresolved`), role. |
| `regulatory_order`, `coverage_order` | Orders keyed by URL: kind (qco, amendment, extension, deferment, rescission, …), S.O./G.S.R. number, date, linked document. |
| `product_term` | Search terms from product names, categories, illustrative items and guideline titles. |

## Guidelines and process

`product_guideline` (PSG rows with resolution and `parse_status`), `guideline_section` (summary, grouping, test
equipment, SIT, scope of licence, other guidelines — with pages and structured JSON), `process_step` (apply-for-licence
steps), `scheme_document` (certification-process documents).

## Laboratories

`laboratory` (LIMS directories; organisation phone/e-mail, no contact names), `lab_list_entry` (Group-1/2 PDF lists
with remarks and `derived_status` + quoted basis), `lab_scope` (LIMS IS-wise rows: version year, product, grade,
charges, validity, remarks, exclusions, query document number) and `lab_scope_item` (clause-wise charge breakup).

## Hallmarking

`ahc` (Manakonline AHC list; recognition number unique; gold/silver scope; list status as published; validity),
`ahc_status_event` (suspended/cancelled list), `hallmarking_district` (phase-wise list plus Gazette-only entries;
`gazette_validated`, `gazette_note`) and `district_alias` (official, Gazette and compact spellings). `jeweller` exists
but is empty because the official report is CAPTCHA-protected.

## Knowledge

`faq` (official FAQ pages, category, question, answer, links) with FTS5 `faq_fts`.

## Derived status is computed, never stored as truth

AHC operability, laboratory validity and upcoming-QCO effect depend on the date. The database stores the official
statuses and dates; services compute effective status against an injectable clock and always show the source date.

## Indexes

FTS5 tables (`standard_fts`, `coverage_fts`, `guideline_fts`, `faq_fts`, `chunk_fts`, `lab_fts`, `ahc_fts`) use the
`unicode61 remove_diacritics 2` tokenizer and are rebuilt after ingestion. LSA vector indexes for listings, standards
and FAQs are saved under `data/indexes/`.
