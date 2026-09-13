# Hallmarking

## Sources

| Source | Use |
|---|---|
| Manakonline *List of Assaying & Hallmarking Centres* | Recognition number, validity, name, address, gold/silver scope, listed status, organisation phone/e-mail (1,650 centres) |
| Manakonline *Suspended/Cancelled AHC list* | Current status (`CANCELLED`, `UNDER SUSPENSION`) with dates (731 records) |
| BIS *Phase-wise coverage of districts under mandatory gold hallmarking* (PDF) | 392 districts in 8 phases with order dates (23 Jun 2021 … 03 Aug 2026) |
| Gazette S.O. 4345(E), 03 Aug 2026 — Hallmarking of Gold Jewellery and Gold Artefacts (Third Amendment) Order, 2026 | District annex (26 states/UTs, 392 districts) used to validate the phase-wise list |
| BIS hallmarking FAQs (general and mandatory) | Official answers (HUID, grades, standards, complaints) |
| Manakonline licensed-jewellers report | **Not collected** — the report requires a CAPTCHA; users get the official link |

## AHC operability (`ingest/hallmarking.py::effective_ahc_status`)

A centre is **OPERATIVE only if** all hold, checked against today's date:

1. the AHC list status is "Operative";
2. the recognition validity date is published and not in the past;
3. neither official list records a cancellation or suspension.

Otherwise, in order: any cancellation event → `CANCELLED`; list status "Under Suspension" → `SUSPENDED`, "Under
Suspension(Gold Only)" → `SUSPENDED_GOLD_ONLY`, "Deferred" / "Deferment Letter Generated" → `NOT_OPERATIVE`; a
suspension event → `SUSPENDED`; unrecognised status → `UNKNOWN`; missing validity → `VALIDITY_UNKNOWN`; past validity →
`EXPIRED_VALIDITY`. When the two lists disagree, the more restrictive status wins and the disagreement is stated.
Inactive centres are hidden by default and shown on request with their reasons.

On 13 Sep 2026: 1,376 operative, 138 expired validity, 124 suspended, 8 not operative, 4 suspended (gold only).

## District coverage (`reasoning/hallmarking.py::check_district`)

* Names match the official spelling, compact spellings, Gazette spellings and curated renames (Gurgaon ↔ Gurugram,
  Allahabad ↔ Prayagraj, Belgaum ↔ Belagavi, Bangalore ↔ Bengaluru, …). The basis of the match is shown.
* `COVERED` — in the phase-wise list and confirmed by the Gazette annex (phase, order date and both sources shown).
* `COVERED_NEEDS_VERIFICATION` — in only one of the two official documents: Kakinada (only in the phase-wise list) and
  Jalore (only in the Gazette annex).
* `AMBIGUOUS` — the same district name exists in two states (e.g. Bilaspur: Himachal Pradesh and Chhattisgarh); the
  user is asked to choose.
* `NOT_IN_LIST` — not found; typos get "did you mean" suggestions. The message says mandatory hallmarking applies only in
  notified districts and asks the user to verify with BIS.
