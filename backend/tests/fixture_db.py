"""Test helper: a small database built from the real fixture snapshots, shared by reasoning and API tests.

The seeded standards deliberately publish IS 14756 only in parts, so listings that cite the undivided standard
resolve as family-ambiguous — the situation real data shows for IS 2062.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import Engine

from manakmarg.db import fts
from manakmarg.db.engine import get_engine, init_db
from manakmarg.ingest import sources
from manakmarg.ingest.bis_pages import parse_apply_licence, parse_certification_process_docs, parse_faq_page, parse_page_text
from manakmarg.ingest.bis_schemes import parse_scheme_i, parse_upcoming_qcos
from manakmarg.ingest.compliance_loader import load_scheme_records
from manakmarg.ingest.fetch import FetchResult
from manakmarg.ingest.hallmarking import (
    parse_ahc_events,
    parse_ahc_list,
    parse_gazette_annex,
    parse_phasewise_districts,
    validate_against_gazette,
)
from manakmarg.ingest.lab_lists import parse_group_list
from manakmarg.ingest.lims import parse_lims_directory, parse_lims_scope_search
from manakmarg.ingest.loaders import (
    load_ahc_events,
    load_ahcs,
    load_districts,
    load_faqs,
    load_gazette_only_districts,
    load_group_list,
    load_guidelines,
    load_lab_scope,
    load_labs,
    load_process_steps,
    load_product_manual,
    load_scheme_documents,
    load_web_page,
)
from manakmarg.ingest.product_manual import ManualPage, parse_product_manual
from manakmarg.ingest.psg import parse_psg
from manakmarg.ingest.runs import RunRecorder
from tests.standards_seed import seed_standards

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bis"
REGISTRY = sources.REGISTRY
SEEDED_STANDARDS = [
    "IS 269:2015",
    "IS 14756 (Part 1):2025",
    "IS 14756 (Part 2):2025",
    "IS 14543:2024",
    "IS 2062 (Part 1):2025",
    "IS 1417:2016",
]
UTENSILS_MANUAL = "https://www.bis.gov.in/wp-content/uploads/2025/01/PM-IS-14756.pdf"
FAQ_PAGES = (
    ("bis_faq_product_certification", "faq_product_certification.html", "product_certification"),
    ("bis_faq_laboratory", "faq_laboratory.html", "laboratory"),
    ("bis_faq_hallmarking_general", "faq_hallmarking_general.html", "hallmarking_general"),
    ("bis_faq_hallmarking_mandatory", "faq_hallmarking_mandatory.html", "hallmarking_mandatory"),
)
DIRECTORIES = (
    ("lims_recognised_labs", "lims_recognised_labs_page1.html", "BIS_RECOGNISED"),
    ("lims_bis_labs", "lims_bis_labs.html", "BIS_LAB"),
    ("lims_empanelled_labs", "lims_empanelled_labs_page1.html", "GOVT_EMPANELLED"),
)


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _pages(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["pages"]


def build_fixture_db(path: Path) -> Engine:
    engine = get_engine(path)
    init_db(engine)
    with engine.begin() as conn:
        sources.sync_registry(conn)
        seed_standards(conn, SEEDED_STANDARDS)

    def run(source_id: str, action, notes: str = "") -> None:
        with RunRecorder(engine, source_id, notes=notes) as recorder:
            action(recorder)

    url = REGISTRY["bis_scheme_i_page"].url
    run("bis_scheme_i_page", lambda r: load_scheme_records(r, parse_scheme_i(_read("scheme_i.html"), url), scheme_id="SCHEME_I", page_url=url))
    upcoming = REGISTRY["bis_upcoming_qco_page"].url
    run("bis_upcoming_qco_page", lambda r: load_scheme_records(r, parse_upcoming_qcos(_read("upcoming_qcos.html"), upcoming), scheme_id=None, page_url=upcoming))

    apply_url = REGISTRY["bis_apply_licence_page"].url
    run("bis_apply_licence_page", lambda r: load_process_steps(r, parse_apply_licence(_read("apply_licence.html"), apply_url), page_url=apply_url))
    process_url = REGISTRY["bis_cert_process_page"].url
    run("bis_cert_process_page", lambda r: load_scheme_documents(r, parse_certification_process_docs(_read("certification_process.html"), process_url), page_url=process_url))
    overview_url = REGISTRY["bis_compulsory_overview_page"].url
    run("bis_compulsory_overview_page", lambda r: load_web_page(r, parse_page_text(_read("compulsory_overview.html"), overview_url), url=overview_url))
    for source_id, fixture, category in FAQ_PAGES:
        faq_url = REGISTRY[source_id].url
        run(source_id, lambda r, fixture=fixture, category=category, faq_url=faq_url: load_faqs(r, parse_faq_page(_read(fixture), category, faq_url), page_url=faq_url))

    psg_url = REGISTRY["bis_psg_page"].url
    run("bis_psg_page", lambda r: load_guidelines(r, parse_psg(_read("psg.html"), psg_url), page_url=psg_url))
    manual_pages = [ManualPage(page["page"], page["text"], page.get("tables", [])) for page in _pages("pm_is_14756_pages.json")]
    fetched = FetchResult(
        url=UTENSILS_MANUAL,
        final_url=UTENSILS_MANUAL,
        status=200,
        content=b"%PDF",
        content_type="application/pdf",
        sha256="0" * 64,
        local_path=path.parent / "pm.pdf",
        retrieved_at=datetime(2026, 9, 12, 14, 30, tzinfo=timezone.utc),
        from_cache=False,
    )
    run(
        "bis_product_manual_documents",
        lambda r: load_product_manual(
            r, url=UTENSILS_MANUAL, title="STAINLESS STEEL UTENSILS", manual=parse_product_manual(manual_pages), fetched=fetched, page_count=len(manual_pages), source_page_url=psg_url
        ),
    )

    for source_id, fixture, category in DIRECTORIES:
        directory_url = REGISTRY[source_id].url
        run(source_id, lambda r, fixture=fixture, category=category, directory_url=directory_url: load_labs(r, parse_lims_directory(_read(fixture), category, directory_url).labs, directory_url=directory_url))
    group_url = REGISTRY["bis_lab_group1_list"].url
    run("bis_lab_group1_list", lambda r: load_group_list(r, parse_group_list(_pages("lab_group1_tables.json"), group=1), document_url=group_url))
    for doc_no, fixture in (("2062", "lims_scope_search_2062_page1.html"), ("269", "lims_scope_search_269_page1.html")):
        search_url = f"https://lims.bis.gov.in/home/search_is_number/?is_number__doc_no={doc_no}"
        run(
            "lims_is_scope_search",
            lambda r, fixture=fixture, doc_no=doc_no, search_url=search_url: load_lab_scope(r, parse_lims_scope_search(_read(fixture), search_url).rows, query_doc_no=doc_no, search_url=search_url),
            notes=f"is_number__doc_no={doc_no}",
        )

    ahc_url = REGISTRY["manak_ahc_list"].url
    run("manak_ahc_list", lambda r: load_ahcs(r, parse_ahc_list(_read("ahc_list.html"), ahc_url), page_url=ahc_url))
    events_url = REGISTRY["manak_ahc_cancelled_suspended"].url
    run("manak_ahc_cancelled_suspended", lambda r: load_ahc_events(r, parse_ahc_events(_read("ahc_cancelled_suspended.html"), events_url), page_url=events_url))
    records = parse_phasewise_districts([page["text"] for page in _pages("hm_districts_phasewise_2026_09.json")])
    annex = parse_gazette_annex([page["text"] for page in _pages("hm_gazette_so4345_2026_08_03_english.json")])
    validation = validate_against_gazette(records, annex)
    run("bis_hm_districts_phasewise", lambda r: load_districts(r, records, validation, document_url=REGISTRY["bis_hm_districts_phasewise"].url))
    run(
        "bis_hm_gazette_2026_08_03",
        lambda r: load_gazette_only_districts(r, list(validation.extra_in_gazette), document_url=REGISTRY["bis_hm_gazette_2026_08_03"].url, note="Listed in the Gazette annex only; verify."),
    )
    with engine.begin() as conn:
        fts.rebuild_fts(conn)
    return engine
