# Copyright, access and privacy

## What the prototype collects, and on what terms

| Material | Treatment |
|---|---|
| BIS website pages (scheme listings, QCO links, process pages, FAQs, PSG table) | Factual records and short attributed snippets (≤ 300 characters) with retrieval dates; users are linked to the official page. The BIS Copyright Policy permits reproduction when accurate, not misleading and prominently acknowledged; it does not extend to third-party material. |
| Official PDFs (Product Manuals, QCO Gazette copies, lab lists, district list, hallmarking order) | Downloaded only for the demo families and validation, cached locally for text extraction, never redistributed; the UI links to the official copy. |
| LIMS and Manakonline public listings | Factual laboratory, scope and AHC records with attribution; organisation phone/e-mail as published; **contact-person names are not stored**. |
| Supplied Excel exports (`data/*.xlsx`) | Read-only inputs, never modified. |

## What is never collected or bypassed

* **Indian Standard texts** (BIS copyright): never downloaded; the product links to the BIS standards portal.
* **CAPTCHA-protected** Manakonline jeweller report: not accessed; users receive the official link.
* **HTTP 401/403 and robots.txt disallows**: recorded as access-denied and not retried — for example one Product Manual
  PDF (`PM_IS_2062.pdf`) returns 403.
* No private APIs and no sign-in-only data. The weekly standards refresh ([DATA_REFRESH.md](DATA_REFRESH.md)) makes only
  the anonymous export and ministry-list requests that the public Published Standards pages make for any visitor.
  The Ministry-wise and Group-wise aggregate downloads, which need a signed-in account with an approved role, are not
  used, and the portal's Department/Group API stays registered as not used. No DRM/FileOpen circumvention, no
  rate-limit evasion. Requests are spaced ≥ 2.5 s per host with a clear User-Agent.

## Presentation rules

* The product is an **independent prototype**: no BIS logo, branding or imitation; every page carries a notice to verify
  on official BIS pages.
* Every fact shown has an evidence item with source, authority, URL, locator and retrieval time. Items produced by
  MANAK MARG's own checks are labelled "Derived cross-check"; curated synonyms and renames are labelled matching aids.
* Website content is not a statement of law (BIS Terms); the English text prevails over translations (BIS Disclaimer).
  Hindi answers are generated from templates; identifiers are never translated.

## Uploaded documents

* Stored only in a random per-session folder under `data/uploads/`, validated by extension, magic bytes and size
  (≤ 15 MB), deleted after 120 minutes or when the user ends the session.
* Contents are never logged; the session manifest holds only file ids, roles, sizes and hashes.
* Requirements are taken only from the user's own requirement-source document. Demo files are clearly labelled
  fictional; the demo requirement sheet is not an Indian Standard.

## Secrets

API keys only via environment variables (`.env`, ignored by git; `.env.example` documents the names).
