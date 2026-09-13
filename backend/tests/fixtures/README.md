# Test fixtures from official sources

These files are compact extracts of public official web pages and documents. They were retrieved on
12–13 September 2026 during data discovery so that parser tests can run offline and deterministically.

The content belongs to the Bureau of Indian Standards (BIS) or the Government of India. It is reproduced
here only for automated testing, with attribution, under the
[BIS Copyright Policy](https://www.bis.gov.in/copyright-policy/?lang=en). Navigation, scripts and most
repeated rows were removed; the structure of every parsed table is kept intact. Nothing here is served
by the application — users are always sent to the official URLs.

| Fixture | Official source |
|---|---|
| `bis/scheme_i.html` | https://www.bis.gov.in/product-certification/products-under-compulsory-certification/scheme-i-mark-scheme/?lang=en (mobile copy of the table trimmed) |
| `bis/scheme_ii.html` | https://www.bis.gov.in/product-certification/products-under-compulsory-certification/scheme-ii-registration-scheme/?lang=en |
| `bis/scheme_iv.html` | https://www.bis.gov.in/product-certification/products-under-compulsory-certification/scheme-4/?lang=en |
| `bis/scheme_x.html` | https://www.bis.gov.in/products-under-compulsory-certification-scheme-x/?lang=en |
| `bis/upcoming_qcos.html` | https://www.bis.gov.in/upcoming-qcos-notified-and-due-for-implementation/?lang=en |
| `bis/compulsory_overview.html` | https://www.bis.gov.in/product-certification/products-under-compulsory-certification/?lang=en |
| `bis/psg.html` | https://www.bis.gov.in/product-certification/product-specific-guidelines/?lang=en (55 of 1,647 rows kept) |
| `bis/apply_licence.html` | https://www.bis.gov.in/apply-for-a-license/?lang=en |
| `bis/certification_process.html` | https://www.bis.gov.in/product-certification/product-certification-process/?lang=en |
| `bis/faq_product_certification.html` | https://www.bis.gov.in/product-certification/product-certification-faq/?lang=en |
| `bis/faq_laboratory.html` | https://www.bis.gov.in/laboratorys/laboratory-services-overview/laboratory-faq/?lang=en |
| `bis/faq_hallmarking_general.html` | https://www.bis.gov.in/hallmarking-overview/hallmarking-faqs/hallmarking-faq/?lang=en |
| `bis/faq_hallmarking_mandatory.html` | https://www.bis.gov.in/hallmarking-overview/hallmarking-faqs/mandatory/?lang=en |
| `bis/lims_recognised_labs_page1.html` | https://lims.bis.gov.in/home/labs/ |
| `bis/lims_bis_labs.html` | https://lims.bis.gov.in/home/bis_labs/ |
| `bis/lims_empanelled_labs_page1.html` | https://lims.bis.gov.in/home/empaneled_labs/ |
| `bis/lims_scope_search_2062_page1.html` | https://lims.bis.gov.in/home/search_is_number/?is_number__doc_no=2062 (first 6 rows kept) |
| `bis/lims_scope_search_269_page1.html` | https://lims.bis.gov.in/home/search_is_number/?is_number__doc_no=269 (first 4 rows kept) |
| `bis/lims_lab_scope_15.html` | https://lims.bis.gov.in/home_lab_scope/15/ (first 3 rows kept) |
| `bis/ahc_list.html` | https://www.manakonline.in/MANAK/AHCListForWebsite (first 20 rows plus sampled non-operative rows) |
| `bis/ahc_cancelled_suspended.html` | https://huid.manakonline.in/MANAK/AHCSuspendCancelledAppsForWebsite (first 15 rows plus rows matching the AHC fixture) |
| `bis/hm_districts_phasewise_2026_09.json` | Page text of https://www.bis.gov.in/wp-content/uploads/2026/09/Phase-wise-coverage-of-districts-under-gold-mandatory-hallmarking.pdf |
| `bis/hm_gazette_so4345_2026_08_03_english.json` | English pages (12 onwards) of https://www.bis.gov.in/wp-content/uploads/2026/08/Notification-related-to-mandatory-Hallmarking-2.pdf |
| `bis/pm_is_14756_pages.json` | Page text of https://www.bis.gov.in/wp-content/uploads/2025/01/PM-IS-14756.pdf |
| `bis/qco_cookware_2023_pages.json` | Page text of https://bis.gov.in/wp-content/uploads/2023/08/Cookwareand-Utensils-QCO-2023.pdf |
| `bis/lab_group1_tables.json` | First 3 pages (text and PyMuPDF tables) of https://www.bis.gov.in/wp-content/uploads/2026/06/Group_1_24062026.pdf |
| `bis/lab_group2_tables.json` | First 2 pages (text and PyMuPDF tables) of https://www.bis.gov.in/wp-content/uploads/2026/04/Group-2_23042026.pdf |
