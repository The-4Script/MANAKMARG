# Compliance logic

All rules live in code with tests; nothing in this document is decided by similarity scores or by an LLM.

## Listing status (from the BIS page itself) — `normalize/status_rules.py`

Precedence, with the quoted phrase stored as `status_basis`:

1. Category or product text contains "De-notified" → `DENOTIFIED`.
2. Notification text mentions rescission → `RESCINDED` (verify).
3. Notification text mentions a deferment → `NEEDS_VERIFICATION`.
4. Row from the upcoming-QCO page → `UPCOMING`.
5. Otherwise, a row on a compulsory-certification scheme page → `LISTED_COMPULSORY`.

## Compulsory effect (computed against today) — `reasoning/applicability.py`

| Listing status | Effect |
|---|---|
| `LISTED_COMPULSORY` | `COMPULSORY` |
| `UPCOMING` with enforcement date after today | `UPCOMING` (days to enforcement shown) |
| `UPCOMING` with enforcement date reached | `ENFORCEMENT_DATE_REACHED` (verify) |
| `UPCOMING` without a date | `NEEDS_VERIFICATION` |
| `DENOTIFIED` / `RESCINDED` / `NEEDS_VERIFICATION` | same, shown as needing verification |

When a product is listed on a scheme page **and** on the upcoming-QCO page with a future enforcement date, the upcoming
listing leads (the enforcement date is the actionable fact) and a caveat explains that both pages list it.

## Applicability labels

| Label | Rule |
|---|---|
| `CONFIRMED` | The user named an IS number (resolved to published standards, including standards now published only in parts) or selected a listing, and the lead listing's effect is compulsory or upcoming without conflicting listings. |
| `LIKELY_APPLICABLE` | Product words cover ≥ 80 % of the official product name's words and the top match leads the next different product by ≥ 0.1. |
| `CANDIDATE` | Weaker or tied matches (e.g. "pressure cooker" ties "Domestic Pressure Cooker" and "Rubber Gaskets for Pressure Cookers"). The user is asked to confirm. |
| `NEEDS_VERIFICATION` | Lead listing is de-notified, rescinded, marked for verification or past its upcoming date, or strong matches conflict (compulsory vs withdrawn). |
| `UNKNOWN` | No supporting record. |

If no listing matches, the answer says so and adds: *"BIS certification is voluntary unless a QCO covers the product —
this is not proof that none applies."* Absence is never presented as proof.

## Standard resolution — `search/resolvers.py`

`exact_version` → `match_key_version` (same version in another notation) → `family_latest` (no year given) →
`family_ambiguous` (no part given, only parts published) → `version_not_in_master` → `international_reference` →
`prefix_mismatch_candidate` (never treated as a match) → `unresolved`. The prefix is part of identity:
`IS 13450` is not `IS/ISO 13450`.

## Compliance journey — `reasoning/journey.py`

Product understanding → applicable standard (versions, type, publication date, ministry classification where
available, portal link) → compulsory status and QCOs → certification scheme (official description and documents) →
Product Manual (parsed summary, sections with pages; access-denied recorded) → tests (Scheme of Inspection and Testing
from the manual; otherwise tests a LIMS-listed lab is recognised for, clearly labelled) → laboratories → official
application steps → next actions. A step without evidence is returned as `missing` with a note.

## Gap analysis — `documents/`

Requirements are read only from documents the user marks as a requirement source, only where a numeric limit is
written ("not less than", "shall not exceed", "between … and …", Min/Max table columns). Values come from datasheets
(declared) and test reports (measured). Parameters are matched by token overlap; units are converted within one
dimension only.

| Status | Rule |
|---|---|
| `PASS` | Confidently matched value (similarity ≥ 0.75) satisfies the limit. |
| `POTENTIAL_GAP` | Declared value violates the limit, or the match is uncertain (0.5–0.75). |
| `FAIL` (non-conformity indication) | Measured value violates the limit. Not a certification decision. |
| `UNKNOWN` | Units are not comparable (e.g. HV vs HRC). |
| `INSUFFICIENT_EVIDENCE` | No matching product value. |

When both a measured and a declared value match, the measured value is used.
