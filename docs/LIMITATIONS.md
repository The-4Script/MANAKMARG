# Known limitations

These are also shown in the product (Navigator and Sources & Data Health).

## Data coverage

* **Standards metadata** comes from BIS exports generated on 12 Sep 2026. Standard texts are not collected and no
  official per-standard URL is available, so the product links to the BIS published-standards portal.
* **Classification**: ministry nodes come from 18 ministry exports only; department and group classification is not
  available and is not inferred.
* **Licensed jewellers** are not listed: the official report requires a CAPTCHA.
* **IS-wise laboratory scope, Product Manual text and QCO text** are indexed for 13 demo standard families; other
  standards show metadata and link to LIMS / official PDFs. 11 Product Manuals are parsed; one (`PM_IS_2062.pdf`)
  refused access (HTTP 403).
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
* Query understanding is rule-based. Hindi questions are routed by Hindi keywords and state names; Hindi district names
  are not in the gazetteer (Latin spellings work).
* Answers are template-based. The optional Claude narrative is not enabled in this build.

## Gap analysis

* Compares only numeric limits written in the uploaded requirement source; text requirements (e.g. marking, visual
  inspection) are not evaluated. Scanned PDFs without a text layer are not OCR'd.
* Parameter matching is lexical; uncertain matches are never shown as a pass.
* A "non-conformity indication" is not a certification decision.

## Engineering

* SQLite is used for portability; the schema is written to move to PostgreSQL.
* The API has no authentication; it is intended for local demonstration. Upload sessions are unguessable ids with TTL.
