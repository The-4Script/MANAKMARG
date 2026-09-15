"""Machine-readable registry of every source MANAK MARG uses — and the ones it deliberately does not use.

The registry is the single place that records authority, access status and reuse notes for a source.
It is synced into the ``source`` table and exported to ``data/manifests/sources.json``.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from manakmarg.db import schema

LAST_CHECKED = "2026-09-13"
BIS = "Bureau of Indian Standards"

BIS_WEBSITE_RIGHTS = (
    "BIS Copyright Policy: material on the BIS website may be reproduced free of cost if it is reproduced "
    "accurately, not used in a derogatory manner or misleading context, and the source is prominently "
    "acknowledged; the permission does not extend to third-party copyright material. MANAK MARG stores "
    "factual metadata and short attributed snippets and links users to the official page."
)
BIS_DOCUMENT_RIGHTS = (
    "Official BIS publication. Cached locally only for text extraction and never redistributed; users are "
    "linked to the official URL and shown short attributed snippets."
)
GAZETTE_RIGHTS = (
    "Gazette of India notification hosted on the BIS website. Cached locally for text extraction only; users "
    "are linked to the official copy."
)
MANAK_RIGHTS = (
    "Public listing on the BIS Manakonline portal. Factual records reproduced with attribution and retrieval "
    "date; contact-person names are not stored."
)
LIMS_RIGHTS = (
    "Public listing on BIS LIMS. Factual laboratory and scope records reproduced with attribution and retrieval "
    "date; contact-person names are not stored."
)
STANDARD_EXPORT_RIGHTS = (
    BIS_WEBSITE_RIGHTS + " Indian Standard texts themselves are BIS copyright and are not collected; only "
    "metadata and official links are used."
)
CURATED_RIGHTS = (
    "Created by the MANAK MARG team as a matching aid. Never presented as regulatory evidence; results found "
    "through it are labelled."
)


@dataclass(frozen=True)
class SourceDef:
    source_id: str
    name: str
    publisher: str
    domain: str
    url: str
    source_type: str
    purpose: str
    ingestion_method: str
    authority: str
    access_status: str
    document_type: str
    copyright_notes: str
    access_notes: str = ""
    as_of_label: str = ""


def _bis_page(source_id, name, url, purpose, method, source_type="html_page", access_notes="", access="ok"):
    return SourceDef(
        source_id=source_id,
        name=name,
        publisher=BIS,
        domain="www.bis.gov.in",
        url=url,
        source_type=source_type,
        purpose=purpose,
        ingestion_method=method,
        authority="official_primary",
        access_status=access,
        document_type="html",
        copyright_notes=BIS_WEBSITE_RIGHTS,
        access_notes=access_notes,
    )


_SOURCES = (
    # ----------------------------------------------------------------- standards metadata (supplied exports)
    SourceDef(
        source_id="bis_std_export_total",
        name="BIS Published Standards — full export titled 'Total' (data/1.xlsx)",
        publisher=BIS,
        domain="standards.bis.gov.in",
        url="https://standards.bis.gov.in/website/published-standards/published-standard-deptwise",
        source_type="excel_export",
        purpose="Master list of published Indian Standards: designation, title, publication date, type of "
        "standard and degree of equivalence.",
        ingestion_method="Excel export downloaded by the team from the BIS Standards portal; parsed with openpyxl "
        "by manakmarg.ingest.excel_standards.",
        authority="official_primary",
        access_status="ok",
        document_type="xlsx",
        copyright_notes=STANDARD_EXPORT_RIGHTS,
        access_notes="Title cell 'Total'. 24,014 rows. No per-row Department or Group column.",
        as_of_label="Generated on 12 Sep 2026, 20:17",
    ),
    SourceDef(
        source_id="bis_std_export_second",
        name="BIS Published Standards — second full export, untitled (data/2.xlsx)",
        publisher=BIS,
        domain="standards.bis.gov.in",
        url="https://standards.bis.gov.in/website/published-standards/published-standard-groupwise?activeTab=group",
        source_type="excel_export",
        purpose="Cross-check of the master list; flags standards present in this view.",
        ingestion_method="Excel export downloaded by the team; parsed with openpyxl by "
        "manakmarg.ingest.excel_standards.",
        authority="official_primary",
        access_status="ok",
        document_type="xlsx",
        copyright_notes=STANDARD_EXPORT_RIGHTS,
        access_notes="Empty title cell. 23,883 rows (23,844 unique designations; 39 repeated rows with identical "
        "fields); 171 designations of the total export absent; 1 extra designation. Most likely the Group-wise "
        "view, but the export itself does not say so.",
        as_of_label="Generated on 12 Sep 2026, 20:32",
    ),
    SourceDef(
        source_id="bis_std_exports_ministry",
        name="BIS Published Standards — Ministry-wise exports (18 files, partial)",
        publisher=BIS,
        domain="standards.bis.gov.in",
        url="https://standards.bis.gov.in/website/published-standards/published-standard-ministrywise?activeTab=ministry",
        source_type="excel_export",
        purpose="Ministry / ministry-department classification of standards.",
        ingestion_method="Per-ministry Excel exports downloaded by the team; the title cell names the classification "
        "node. Parsed by manakmarg.ingest.excel_standards.",
        authority="official_primary",
        access_status="partial",
        document_type="xlsx",
        copyright_notes=STANDARD_EXPORT_RIGHTS,
        access_notes="Covers 18 nodes alphabetically from 'Department of Atomic Energy' to 'Ministry of "
        "Communications - Department of Telecommunications (DOT)'. The complete Ministry-wise export could not "
        "be generated by the BIS portal, so other ministries are not classified.",
        as_of_label="Generated on 12 Sep 2026, 20:34–20:38",
    ),
    SourceDef(
        source_id="bis_standards_portal_api",
        name="BIS Standards portal internal API (standards.bis.gov.in single-page app)",
        publisher=BIS,
        domain="standards.bis.gov.in",
        url="https://standards.bis.gov.in/website/published-standards/published-standard-deptwise",
        source_type="web_api",
        purpose="Would expose Department and Group classification per standard.",
        ingestion_method="Not used.",
        authority="official_primary",
        access_status="not_used",
        document_type="json",
        copyright_notes=STANDARD_EXPORT_RIGHTS,
        access_notes="Undocumented API behind an Angular app that blocks developer tools; excluded under the "
        "project rule against hidden or private APIs. Department/Group classification therefore stays empty.",
    ),
    # ----------------------------------------------------------------- compulsory certification
    _bis_page(
        "bis_compulsory_overview_page",
        "Products under Compulsory Certification — overview",
        "https://www.bis.gov.in/product-certification/products-under-compulsory-certification/?lang=en",
        "Official statement that BIS certification is voluntary except where Central Government QCOs make it "
        "compulsory; links to the scheme lists and the QCO guidance document.",
        "HTML fetched politely and main content parsed by manakmarg.ingest.bis_pages.",
    ),
    _bis_page(
        "bis_scheme_i_page",
        "Scheme I (ISI Mark Scheme) — products under compulsory certification",
        "https://www.bis.gov.in/product-certification/products-under-compulsory-certification/scheme-i-mark-scheme/?lang=en",
        "Product ↔ Indian Standard ↔ QCO/notification listings under Scheme I, including de-notified entries.",
        "Desktop copy of the HTML table (rowspans expanded) parsed by manakmarg.ingest.bis_schemes.",
        source_type="html_table",
        access_notes="The page carries a desktop and a mobile copy of the table; the desktop copy is newer and is "
        "the one parsed.",
    ),
    _bis_page(
        "bis_scheme_ii_page",
        "Scheme II (Registration Scheme) — products under compulsory registration",
        "https://www.bis.gov.in/product-certification/products-under-compulsory-certification/scheme-ii-registration-scheme/?lang=en",
        "IS, title, product category and notification history for compulsory registration.",
        "HTML section tables parsed by manakmarg.ingest.bis_schemes.",
        source_type="html_table",
    ),
    _bis_page(
        "bis_scheme_iv_page",
        "Scheme IV (Grant of Certificate of Conformity) — products",
        "https://www.bis.gov.in/product-certification/products-under-compulsory-certification/scheme-4/?lang=en",
        "Products with essential requirements referencing IS clauses and the governing QCOs.",
        "Desktop copy of the HTML table parsed by manakmarg.ingest.bis_schemes.",
        source_type="html_table",
    ),
    _bis_page(
        "bis_scheme_x_page",
        "Scheme X (Certification) — products",
        "https://www.bis.gov.in/products-under-compulsory-certification-scheme-x/?lang=en",
        "IS, title, product category, specific requirement and notifications under Scheme X.",
        "HTML tables parsed by manakmarg.ingest.bis_schemes.",
        source_type="html_table",
        access_notes="The machinery table's notification cell lists a rescission order (S.O. 239(E), "
        "16 Jan 2026); those rows are marked RESCINDED with the quoted basis.",
    ),
    _bis_page(
        "bis_upcoming_qco_page",
        "Upcoming QCOs — notified and due for implementation",
        "https://www.bis.gov.in/upcoming-qcos-notified-and-due-for-implementation/?lang=en",
        "Ministry/department, product, Indian Standard and enforcement date of notified QCOs not yet in force.",
        "HTML table (rowspans expanded, illustrative sub-lists kept) parsed by manakmarg.ingest.bis_schemes.",
        source_type="html_table",
        access_notes="Time-sensitive advance information; effectiveness is computed against today's date and "
        "never assumed.",
    ),
    SourceDef(
        source_id="bis_qco_documents",
        name="QCO orders, amendments, extensions and rescissions (Gazette PDFs linked from scheme pages)",
        publisher="Government of India (hosted by BIS)",
        domain="www.bis.gov.in",
        url="https://www.bis.gov.in/product-certification/products-under-compulsory-certification/?lang=en",
        source_type="pdf_document",
        purpose="Legal instruments behind compulsory certification; evidence with page numbers.",
        ingestion_method="Order metadata parsed from every scheme-page link; PDFs fetched for selected product "
        "families and text-extracted with page numbers by manakmarg.ingest.documents.",
        authority="official_primary",
        access_status="partial",
        document_type="pdf",
        copyright_notes=GAZETTE_RIGHTS,
        access_notes="Full text indexed for selected families only; all other orders are metadata plus official "
        "links.",
    ),
    _bis_page(
        "bis_psg_page",
        "Product Specific Guidelines (Product Manuals)",
        "https://www.bis.gov.in/product-certification/product-specific-guidelines/?lang=en",
        "IS-wise Product Manuals, which carry sampling guidelines, grouping guidelines, test equipment lists and "
        "the Scheme of Inspection and Testing as annexes.",
        "HTML table parsed by manakmarg.ingest.psg.",
        source_type="html_table",
    ),
    SourceDef(
        source_id="bis_product_manual_documents",
        name="BIS Product Manual PDFs",
        publisher=BIS,
        domain="www.bis.gov.in",
        url="https://www.bis.gov.in/product-certification/product-specific-guidelines/?lang=en",
        source_type="pdf_document",
        purpose="Sampling, grouping, test equipment, Scheme of Inspection and Testing and scope of licence per IS.",
        ingestion_method="PDFs fetched for selected product families and parsed into sections by "
        "manakmarg.ingest.product_manual.",
        authority="official_primary",
        access_status="partial",
        document_type="pdf",
        copyright_notes=BIS_DOCUMENT_RIGHTS,
        access_notes="Some manual PDFs return HTTP 403 (for example /PDF/cart/PM_IS_2062.pdf); they are recorded as "
        "access_denied and never retried.",
    ),
    _bis_page(
        "bis_cert_process_page",
        "Product Certification Process — scheme guidelines",
        "https://www.bis.gov.in/product-certification/product-certification-process/?lang=en",
        "Scheme-wise guideline documents (grant, renewal, surveillance, non-conformity, change of scope).",
        "HTML content parsed by manakmarg.ingest.bis_pages.",
    ),
    _bis_page(
        "bis_apply_licence_page",
        "Apply for Licence — official steps",
        "https://www.bis.gov.in/apply-for-a-license/?lang=en",
        "Step-by-step official process to apply for a BIS licence.",
        "HTML table parsed by manakmarg.ingest.bis_pages.",
        source_type="html_table",
    ),
    _bis_page(
        "bis_faq_product_certification",
        "Product Certification FAQs",
        "https://www.bis.gov.in/product-certification/product-certification-faq/?lang=en",
        "Official answers on licences, compulsory certification and application.",
        "Accordion question/answer pairs parsed by manakmarg.ingest.bis_pages.",
    ),
    _bis_page(
        "bis_faq_laboratory",
        "Laboratory FAQs",
        "https://www.bis.gov.in/laboratorys/laboratory-services-overview/laboratory-faq/?lang=en",
        "Official answers on product testing and laboratory recognition.",
        "Accordion question/answer pairs parsed by manakmarg.ingest.bis_pages.",
    ),
    _bis_page(
        "bis_faq_hallmarking_general",
        "Hallmarking FAQs — General",
        "https://www.bis.gov.in/hallmarking-overview/hallmarking-faqs/hallmarking-faq/?lang=en",
        "Official answers on hallmarking, grades and hallmarking standards.",
        "Accordion question/answer pairs parsed by manakmarg.ingest.bis_pages.",
    ),
    _bis_page(
        "bis_faq_hallmarking_mandatory",
        "Hallmarking FAQs — Mandatory hallmarking",
        "https://www.bis.gov.in/hallmarking-overview/hallmarking-faqs/mandatory/?lang=en",
        "Official answers on mandatory hallmarking.",
        "Accordion question/answer pairs parsed by manakmarg.ingest.bis_pages.",
    ),
    _bis_page(
        "bis_hallmarking_overview_page",
        "Hallmarking overview, orders and guidelines",
        "https://www.bis.gov.in/hallmarking-overview/?lang=en",
        "Hallmarking scheme overview and links to orders, amendments and guidelines.",
        "HTML content and sidebar links parsed by manakmarg.ingest.bis_pages.",
    ),
    _bis_page(
        "bis_policy_pages",
        "BIS Copyright Policy, Terms & Conditions and Disclaimer",
        "https://www.bis.gov.in/copyright-policy/?lang=en",
        "Reuse terms and disclaimers that govern how BIS content is used and presented.",
        "Read during design; summarised in docs/COPYRIGHT_AND_ACCESS.md.",
        access_notes="Terms: website content is not a statement of law. Disclaimer: English prevails over "
        "translations.",
    ),
    # ----------------------------------------------------------------- laboratories
    SourceDef(
        source_id="lims_recognised_labs",
        name="LIMS — BIS recognised laboratories directory",
        publisher=BIS,
        domain="lims.bis.gov.in",
        url="https://lims.bis.gov.in/home/labs/",
        source_type="html_table",
        purpose="Recognised laboratories: OSL lab code, address, organisation contact and validity.",
        ingestion_method="Paginated HTML table parsed by manakmarg.ingest.lims.",
        authority="official_primary",
        access_status="ok",
        document_type="html",
        copyright_notes=LIMS_RIGHTS,
    ),
    SourceDef(
        source_id="lims_bis_labs",
        name="LIMS — BIS laboratories directory",
        publisher=BIS,
        domain="lims.bis.gov.in",
        url="https://lims.bis.gov.in/home/bis_labs/",
        source_type="html_table",
        purpose="BIS's own laboratories with addresses and sample-cell contacts.",
        ingestion_method="HTML table parsed by manakmarg.ingest.lims.",
        authority="official_primary",
        access_status="ok",
        document_type="html",
        copyright_notes=LIMS_RIGHTS,
    ),
    SourceDef(
        source_id="lims_empanelled_labs",
        name="LIMS — empanelled laboratories directory",
        publisher=BIS,
        domain="lims.bis.gov.in",
        url="https://lims.bis.gov.in/home/empaneled_labs/",
        source_type="html_table",
        purpose="Government laboratories empanelled by BIS.",
        ingestion_method="Paginated HTML table parsed by manakmarg.ingest.lims.",
        authority="official_primary",
        access_status="ok",
        document_type="html",
        copyright_notes=LIMS_RIGHTS,
    ),
    SourceDef(
        source_id="lims_is_scope_search",
        name="LIMS — Indian Standard-wise test facilities search",
        publisher=BIS,
        domain="lims.bis.gov.in",
        url="https://lims.bis.gov.in/home/search_is_number/",
        source_type="html_table",
        purpose="Which laboratories are recognised to test a given IS: version, product, grade, charges, "
        "validity, remarks and exclusions, with clause-wise charge breakups.",
        ingestion_method="Rate-limited GET search per IS number for selected families; all result pages parsed "
        "by manakmarg.ingest.lims.",
        authority="official_primary",
        access_status="partial",
        document_type="html",
        copyright_notes=LIMS_RIGHTS,
        access_notes="Indexed for selected IS families only (result pages are 1–3 MB each, so a full crawl is "
        "avoided); other standards link to the official search.",
    ),
    SourceDef(
        source_id="bis_lab_group1_list",
        name="Group-1 list of BIS recognised laboratories (PDF)",
        publisher=BIS,
        domain="www.bis.gov.in",
        url="https://www.bis.gov.in/wp-content/uploads/2026/06/Group_1_24062026.pdf",
        source_type="pdf_document",
        purpose="Recognition validity and suspension / revocation history of recognised laboratories.",
        ingestion_method="PDF tables extracted with PyMuPDF by manakmarg.ingest.lab_lists.",
        authority="official_primary",
        access_status="ok",
        document_type="pdf",
        copyright_notes=BIS_DOCUMENT_RIGHTS,
        access_notes="Header reads 'as on 24-08-2026' while the file path is dated 2026/06; both are recorded.",
        as_of_label="As on 24-08-2026 (per document header)",
    ),
    SourceDef(
        source_id="bis_lab_group2_list",
        name="Group-2 list of laboratories empanelled by BIS (PDF)",
        publisher=BIS,
        domain="www.bis.gov.in",
        url="https://www.bis.gov.in/wp-content/uploads/2026/04/Group-2_23042026.pdf",
        source_type="pdf_document",
        purpose="Government laboratories of national repute whose facilities BIS uses.",
        ingestion_method="PDF tables extracted with PyMuPDF by manakmarg.ingest.lab_lists.",
        authority="official_primary",
        access_status="ok",
        document_type="pdf",
        copyright_notes=BIS_DOCUMENT_RIGHTS,
        as_of_label="As on 07-08-2026 (per document header)",
    ),
    # ----------------------------------------------------------------- hallmarking
    SourceDef(
        source_id="manak_ahc_list",
        name="List of Assaying & Hallmarking Centres (Manakonline)",
        publisher=BIS,
        domain="www.manakonline.in",
        url="https://www.manakonline.in/MANAK/AHCListForWebsite",
        source_type="html_table",
        purpose="AHC recognition number, validity, address, gold/silver scope and listed status.",
        ingestion_method="HTML table parsed by manakmarg.ingest.hallmarking.",
        authority="official_primary",
        access_status="ok",
        document_type="html",
        copyright_notes=MANAK_RIGHTS,
    ),
    SourceDef(
        source_id="manak_ahc_cancelled_suspended",
        name="List of cancelled / expired / suspended AHCs (Manakonline)",
        publisher=BIS,
        domain="huid.manakonline.in",
        url="https://huid.manakonline.in/MANAK/AHCSuspendCancelledAppsForWebsite",
        source_type="html_table",
        purpose="Dated cancellation and suspension status used to exclude inoperative centres.",
        ingestion_method="HTML table parsed by manakmarg.ingest.hallmarking.",
        authority="official_primary",
        access_status="ok",
        document_type="html",
        copyright_notes=MANAK_RIGHTS,
    ),
    SourceDef(
        source_id="bis_hm_districts_phasewise",
        name="Phase-wise coverage of districts under mandatory gold hallmarking (PDF)",
        publisher=BIS,
        domain="www.bis.gov.in",
        url="https://www.bis.gov.in/wp-content/uploads/2026/09/Phase-wise-coverage-of-districts-under-gold-mandatory-hallmarking.pdf",
        source_type="pdf_document",
        purpose="Districts covered by mandatory hallmarking with phase and order date.",
        ingestion_method="PDF text parsed by manakmarg.ingest.hallmarking; validated against Gazette S.O. 4345(E).",
        authority="official_primary",
        access_status="ok",
        document_type="pdf",
        copyright_notes=BIS_DOCUMENT_RIGHTS,
        as_of_label="Uploaded 2026-09; latest phase dated 03 Aug 2026",
    ),
    SourceDef(
        source_id="bis_hm_gazette_2026_08_03",
        name="Hallmarking of Gold Jewellery and Gold Artefacts (Third Amendment) Order, 2026 — S.O. 4345(E)",
        publisher="Ministry of Consumer Affairs, Food and Public Distribution (hosted by BIS)",
        domain="www.bis.gov.in",
        url="https://www.bis.gov.in/wp-content/uploads/2026/08/Notification-related-to-mandatory-Hallmarking-2.pdf",
        source_type="pdf_document",
        purpose="Legal instrument substituting the district Annexure; used to validate the phase-wise list.",
        ingestion_method="English Annexure (from page 12) parsed by manakmarg.ingest.hallmarking.",
        authority="official_primary",
        access_status="ok",
        document_type="pdf",
        copyright_notes=GAZETTE_RIGHTS,
        as_of_label="Dated 03 Aug 2026",
    ),
    SourceDef(
        source_id="bis_hm_districts_nov2024",
        name="Districts covered under hallmarking — November 2024 list (PDF)",
        publisher=BIS,
        domain="www.bis.gov.in",
        url="https://www.bis.gov.in/wp-content/uploads/2025/03/Final_Mandatory_Districts_Nov24.1.pdf",
        source_type="pdf_document",
        purpose="Historical reference only.",
        ingestion_method="Not used for current coverage.",
        authority="official_secondary",
        access_status="ok",
        document_type="pdf",
        copyright_notes=BIS_DOCUMENT_RIGHTS,
        access_notes="Superseded by amendments dated 31 Jul 2025, 02 Mar 2026, 28 Apr 2026 and 03 Aug 2026.",
    ),
    SourceDef(
        source_id="manak_jewellers_report",
        name="Licensed jewellers report (gold IS 1417 / silver IS 2112)",
        publisher=BIS,
        domain="huid.manakonline.in",
        url="https://huid.manakonline.in/MANAK/ApplicationHMLicenceRelatedrpt1?isno=1417",
        source_type="web_report",
        purpose="Registered jewellers by state and district.",
        ingestion_method="Not ingested; users are linked to the official report.",
        authority="official_primary",
        access_status="captcha_blocked",
        document_type="html",
        copyright_notes=MANAK_RIGHTS,
        access_notes="The report requires solving a CAPTCHA; automated access would bypass it, so no jeweller "
        "records are collected.",
    ),
    # ----------------------------------------------------------------- curated and derived
    SourceDef(
        source_id="curated_search_aids",
        name="MANAK MARG curated product synonyms",
        publisher="MANAK MARG team",
        domain="local",
        url="repo:backend/manakmarg/search/synonyms.json",
        source_type="curated_file",
        purpose="Map everyday product words to the product names used in official listings.",
        ingestion_method="Maintained in the repository.",
        authority="curated",
        access_status="ok",
        document_type="json",
        copyright_notes=CURATED_RIGHTS,
    ),
    SourceDef(
        source_id="curated_geography",
        name="MANAK MARG curated state names and district renames",
        publisher="MANAK MARG team",
        domain="local",
        url="repo:backend/manakmarg/normalize/geo.py",
        source_type="curated_file",
        purpose="Normalise state abbreviations (U.P., M.P.) and match renamed districts (Gurgaon/Gurugram).",
        ingestion_method="Maintained in the repository.",
        authority="curated",
        access_status="ok",
        document_type="code",
        copyright_notes=CURATED_RIGHTS,
    ),
    SourceDef(
        source_id="derived_rules",
        name="Deterministic relations derived from official records",
        publisher="MANAK MARG team",
        domain="local",
        url="repo:backend/manakmarg/ingest",
        source_type="curated_file",
        purpose="Relations computed from official data, e.g. newer versions within a standard family; always "
        "labelled as derived.",
        ingestion_method="Computed after ingestion.",
        authority="derived",
        access_status="ok",
        document_type="code",
        copyright_notes="Derived from the official records they reference; carries their provenance.",
    ),
)

HSN_RIGHTS = (
    "Supplied dataset. The workbook does not state its publisher, date or URL, so none is claimed here. HSN codes "
    "and descriptions are shown verbatim as a classification lookup only; they are not a GST, customs or BIS "
    "determination and must be verified with the competent authority."
)

_SOURCES = _SOURCES + (
    SourceDef(
        source_id="hsn_master_workbook",
        name="HSN master — supplied workbook (sheet HSN_MSTR)",
        publisher="Not stated in the workbook",
        domain="local supplied file (data/)",
        url="",
        source_type="supplied_file",
        purpose="Harmonized System of Nomenclature (HSN) codes with their descriptions, used as an additional "
        "classification lookup next to BIS information.",
        ingestion_method="Workbook supplied by the team in data/; located by its HSN_CD / HSN_Description header and "
        "read with openpyxl by manakmarg.ingest.hsn. Descriptions are stored exactly as written.",
        authority="supplied_dataset",
        access_status="ok",
        document_type="xlsx",
        copyright_notes=HSN_RIGHTS,
        access_notes="21,935 HSN rows; codes of 2, 4, 5, 6, 7 and 8 characters kept as text (two contain a space). "
        "The workbook's SAC_MSTR sheet (services) is not used.",
        as_of_label="Supplied workbook (no date stated)",
    ),
)

REGISTRY: dict[str, SourceDef] = {definition.source_id: definition for definition in _SOURCES}


def _row(definition: SourceDef) -> dict:
    return {
        "name": definition.name,
        "publisher": definition.publisher,
        "domain": definition.domain,
        "url": definition.url,
        "source_type": definition.source_type,
        "purpose": definition.purpose,
        "ingestion_method": definition.ingestion_method,
        "authority": definition.authority,
        "access_status": definition.access_status,
        "document_type": definition.document_type,
        "copyright_notes": definition.copyright_notes,
        "access_notes": definition.access_notes or None,
        "as_of_label": definition.as_of_label or None,
        "last_checked": LAST_CHECKED,
    }


def sync_registry(conn: Connection) -> None:
    table = schema.source
    existing = {row[0] for row in conn.execute(sa.select(table.c.source_id))}
    for definition in REGISTRY.values():
        values = _row(definition)
        if definition.source_id in existing:
            conn.execute(table.update().where(table.c.source_id == definition.source_id).values(**values))
        else:
            conn.execute(table.insert().values(source_id=definition.source_id, **values))


def export_manifest(path: Path) -> None:
    entries = []
    for definition in REGISTRY.values():
        notes = " ".join(part for part in (definition.copyright_notes, definition.access_notes) if part)
        entries.append(
            {
                "source_id": definition.source_id,
                "name": definition.name,
                "publisher": definition.publisher,
                "domain": definition.domain,
                "url": definition.url,
                "type": definition.source_type,
                "purpose": definition.purpose,
                "ingestion_method": definition.ingestion_method,
                "authority": definition.authority,
                "access_status": definition.access_status,
                "document_type": definition.document_type,
                "copyright_access_notes": notes,
                "as_of": definition.as_of_label or None,
                "last_checked": LAST_CHECKED,
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_by": "manakmarg.ingest.sources",
        "last_checked": LAST_CHECKED,
        "source_count": len(entries),
        "sources": entries,
    }
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
