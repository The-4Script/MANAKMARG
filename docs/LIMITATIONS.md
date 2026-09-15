# Known limitations

These are also shown in the product (Navigator and Sources & Data Health).

## Data coverage

* **Standards metadata** comes from BIS exports generated on 12 Sep 2026. Standard texts are not collected and no
  official per-standard URL is available, so the product links to the BIS published-standards portal.
* **Classification**: ministry nodes come from 18 ministry exports only; department and group classification is not
  available and is not inferred.
* **Licensed jewellers** are not listed: the official report requires a CAPTCHA.
* **IS-wise laboratory scope, Product Manual text and QCO text** are indexed for 13 demo standard families; other
  standards show metadata and link to LIMS / official PDFs. 11 Product Manuals are parsed (of 1,645 listed on the
  Product Specific Guidelines page); the rest are metadata with a link to the official PDF.
  * **IS 2062**: the manual is published at `https://www.bis.gov.in/PDF/cart/PM_IS_2062.pdf`, which returned HTTP 403.
    This is an access control and is deliberately not bypassed, so IS 2062 has no parsed SIT; its tests come from
    LIMS scope rows.
  * **IS 694 / IS 1554**: manuals are public PDFs but outside the demo families, so they were never fetched. Adding them
    means adding the families to `ingest/demo_families.py` and running an online `documents` + `lab_scope` ingestion;
    this is a post-demo improvement, not done in the accuracy pass.
* Product Manuals that do not follow the common annex template are kept as searchable text without structured SIT.

## Currency and legal status

* Web listings are **snapshots** with retrieval dates. Legal status must be verified against the latest Gazette and BIS
  notifications. Dates (upcoming enforcement, validity) are computed against today, but the underlying lists change.
* The phase-wise district list and the Gazette annex differ by one entry each (Kakinada, Jalore); both are flagged.
* A product listed on a scheme page and on the upcoming-QCO page is shown with both listings; the product cannot tell
  which one BIS intends to govern today.

## Matching and language

* Product matching is lexical/LSA over official product names plus a small curated synonym list; unusual trade names
  may not match, and ties are shown as candidates for the user to confirm. Neural embeddings are pluggable but the model
  download was deferred.
* Query understanding and routing are rule-based. Hindi and Hinglish questions pass through a curated alias list
  (`normalize/aliases.py`) of domain words and about 45 major city names (with common spelling variants) in Devanagari;
  places missing from that list must be written in Latin script, and an unrecognised place is reported rather than
  guessed (a near spelling of a listed city is only suggested).
* Answers follow the language of the question (Devanagari → Hindi, English → English); Hinglish follows the interface
  language. Record titles, place names and identifiers stay as published, so Hindi answers still contain English names.
* Speech-to-text can mishear words beyond the listed variants (in a synthetic-voice check "Jaipur" became "जेलपूर" and
  "बताइए" became "बाट ए"). Such words are not corrected: the place is reported as unrecognised, and extra words can lower
  the match confidence shown for a product.
* The BIS Scheme I page itself sometimes lists the same notification twice with two PDF links (for example S.O. 4494(E)
  for cookware); both links are kept as published.
* Answers are template-based. The optional Claude narrative is not enabled in this build.

## Weekly standards refresh

* The refresh ([DATA_REFRESH.md](DATA_REFRESH.md)) updates published-standards metadata and ministry classification
  only. Compulsory listings, QCOs, Product Manuals, labs, hallmarking and HSN data still come from the last full
  ingestion.
* Group-wise and Department-wise classification are not refreshed: the portal offers the aggregate Group-wise
  download only to signed-in users with an approved role. The supplied group-wise export is reused unchanged.
* The downloader follows the portal's request format as published in September 2026. If BIS changes it, refreshes
  fail safely (the previous dataset stays active) until `refresh/portal.py` is updated.
* The schedule runs only while the server process is running; on hosts without a persistent disk a restart returns to
  the shipped dataset.

## HSN lookup

* HSN codes come from the supplied workbook (sheet `HSN_MSTR`, 21,935 rows). The workbook states no publisher, date or
  URL, so none is shown; results are a classification lookup only — not a GST rate, customs or BIS determination.
* Text search needs every product word to appear in an official description; trade names that the descriptions do not
  use (e.g. "utensils" where the description says "household articles") return no match rather than a guess.
* The workbook's `SAC_MSTR` sheet (services) is not used. The workbook file itself is not committed to git; the HSN
  rows ship inside the data bundle.

## Voice input

* Requires `GROQ_API_KEY` on the server; without it the microphone button is disabled with an explanation.
* Recordings are capped at 30 seconds / 10 MB, sent only to Groq's transcription API, held in memory for that one
  request and never stored or logged. Transcription quality depends on the microphone and accent; the transcript is
  shown as the question so the user can see exactly what was understood.

## Gap analysis

* Compares only numeric limits written in the uploaded requirement source; text requirements (e.g. marking, visual
  inspection) are not evaluated. Scanned PDFs without a text layer are not OCR'd.
* Parameter matching is lexical; uncertain matches are never shown as a pass.
* A "non-conformity indication" is not a certification decision.

## Engineering

* SQLite is used for portability; the schema is written to move to PostgreSQL.
* The API has no authentication; it is intended for local demonstration. Upload sessions are unguessable ids with TTL.
