# Data-quality report

Checked on 2026-09-15 by `manakmarg.ingest.quality`. Counts of zero are listed to show what was verified.

| Check | Severity | Count | Examples | What it means |
|---|---|---:|---|---|
| canonical_collisions | error | 0 |  | Different raw designations normalising to the same key inside one source; rejected for review, never merged. |
| failed_runs | error | 0 |  | Sources whose latest ingestion run failed and was rolled back. |
| missing_provenance | error | 0 |  | Rows without a source, locator or retrieval time. Every record must be traceable to its source. |
| designation_flag:malformed_repaired | warning | 9 | IS/IEC 60794 (Part 1/Sec 1):2023; IS 5887 (Part 5/Sec 1):2023; IS/IEEE 1523 Tm:2018 | Malformed designation punctuation repaired (e.g. 'IS):7779 ( (Part 1/Sec 1)):1975'). |
| designation_flag:unparsed | warning | 1 | ISIHB MMAW:1965 | Designation that could not be parsed; stored under its whitespace-normalised text. |
| future_publication_dates | warning | 0 |  | Publication dates later than the check date. |
| missing_publication_date | warning | 387 | IS 16125 (Part 2):2013; IS/ISO 20022 (Part 2):2013; IS/IEC 60793 (Part 1/Sec 42):2013 | Standards whose export row has no publication date. |
| orphan_classification_links | warning | 0 |  | Current classification links pointing to a retired standard or node. |
| rejected_records | warning | 0 |  | Records rejected by the latest run of each source. |
| designation_flag:duplicate_year | info | 4 | IS 6560:2017; IS/ISO 7130:2013; IS/ISO 14790:2005 | Year written twice (e.g. ':2017:2017'). |
| designation_flag:missing_year_colon | info | 2 | IS 16910 (Part 2/Sec 33):2026; IS 16910 (Part 2/Sec 11):2026 | Year not separated by a colon (e.g. '(Part 2/Sec 11)2026'). |
| designation_flag:number_range | info | 2 | IS 4864 to 4870:1968; IS 1201 to 1220:1978 | Designation covering a range of numbers (e.g. 'IS 4864 to 4870'). |
| designation_flag:prefix_case | info | 17 | IS/IEC 62232:2022; IS/IEC/IEEE 63195 (Part 2):2022; IS 14661 (Part 2):2025 | Designation prefix written with irregular letter case (e.g. 'Is'); normalised. |
| designation_flag:prefix_repaired | info | 30 | IS/ISO/IEC/TR 20226:2025; IS/ISO/IEC/TS 12791:2024; IS/ISO/IEC/TR 24027:2021 | Designation prefix with irregular separators or a known typo (e.g. 'IS ISO', 'IEE'); normalised. |
| designation_flag:suffix | info | 19 | IS 9374 P:2026; IS 19877 T:2026; IS 8376 P:2026 | Designation carries a suffix such as P, T, Supplement or (S&T); kept as part of its identity. |
| equivalence_unspecified | info | 507 | SP 74:2025; IS 3097:2025; IS 12823:2025 | Standards whose 'Degree of Equivalence' is '-' in the export; stored as unknown. |
| families_with_multiple_versions | info | 442 | IS 10009; IS 10045; IS 10058 | Standard families with more than one version in the published list; references without a year resolve to the latest version and show the others. |
| ministry_only_standards | info | 10 | IS 1007:1984; IS 302 (Part 1):2008; IS 302 (Part 2/Sec 201):2008 | Designations listed in a ministry export but absent from both full exports (often superseded versions); kept with listing_status 'ministry_export_only' and never shown as current. |
| titles_shared_by_multiple_standards | info | 81 | IS 14990 (Part 5):2024 / IS 14990 (Part 5):2026; IS 7762:1975 / IS 7762:2026; IS 7758:1975 / IS 7758:2026 | Identical normalised titles under different designations (revisions, indigenous vs adopted standards, possible typos). Records are kept separate. |
| type_unspecified | info | 107 | IS 17550 (Part 3):2025; IS 13489:2025; IS 14756:2024 | Standards whose 'Type of Standard' is '-' in the export; stored as unknown. |
