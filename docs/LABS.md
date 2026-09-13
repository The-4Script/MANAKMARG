# Laboratories

## Sources

| Source | Use |
|---|---|
| LIMS directories — BIS laboratories (10), BIS recognised (431), Government empanelled (140) | Name, OSL lab code, address (city, district, state, PIN), organisation phone and e-mail, LIMS validity. Contact-person names are not stored. |
| LIMS *Search by IS number* | For each searched standard number, every result page: laboratory, OSL code, IS version, product, grade/type, testing charges, validity, remarks, exclusions and the clause-wise charge breakup |
| BIS Group-1 list of recognised laboratories (PDF, as on 24-08-2026) | Recognition valid-up-to date and dated suspension / revocation remarks |
| BIS Group-2 list of laboratories of national repute (PDF, as on 07-08-2026) | Government laboratories whose facilities BIS uses |

IS-wise scope is indexed for the 13 standard numbers of the demo families (14756, 269, 2062, 4151, 9873, 15644, 374,
2347, 14543, 302, 60947, 62368, 10613): 1,576 scope rows. For any other standard the product links to the official
LIMS search. A full crawl is avoided to limit load on BIS systems.

## Rules (`reasoning/labs.py`)

* A laboratory is shown for a standard **only** when a LIMS scope row lists it. Capability is never inferred from a
  directory entry, a Group list or a lab's name. Exclusions and remarks are shown verbatim.
* Scope rows are matched by standard number and part; a query without a part includes all parts.
* A version is marked "in published list" only when LIMS names a version present in the published-standards export.
* Status:
  * Group-1 remarks whose latest dated event is a suspension → `SUSPENDED`; a withdrawal → `WITHDRAWN`.
  * Any published validity date (LIMS scope, LIMS directory, Group list) in the past → `EXPIRED`.
  * A future validity date → `VALID` (or `NEEDS_VERIFICATION` when remarks mention a status change without a date).
  * BIS's own laboratories, which LIMS publishes without validity → `BIS_LAB`.
  * No date at all → `VALIDITY_UNKNOWN`.
* Location: district (with curated renames) > city > state; if nothing matches, laboratories elsewhere are shown under
  a clear "no labs in the chosen location" notice.
* Ranking: location match, then status (valid first, expired/suspended last), then published version, then no
  exclusions, then newer version.

## Group-1 remark parsing (`ingest/lab_lists.py::derive_lab_status`)

Remarks such as "Suspension revoked w.e.f. 23-08-2024 (Present status operative) Suspended w.e.f. 05-04-2024 …" are
read as dated events (suspended, suspension revoked, withdrawn) in the numeric and textual date formats the list uses.
The latest dated event decides the status and is quoted as the basis.
