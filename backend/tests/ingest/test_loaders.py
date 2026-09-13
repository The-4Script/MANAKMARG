"""Loaders for pages, guidelines, manuals, laboratories and hallmarking, on real fixture snapshots."""

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa

from manakmarg.db import schema
from manakmarg.db.engine import get_engine, init_db
from manakmarg.ingest import sources
from manakmarg.ingest.bis_pages import (
    parse_apply_licence,
    parse_certification_process_docs,
    parse_faq_page,
    parse_page_text,
)
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
    link_order_document,
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
    load_text_document,
    load_web_page,
    record_document_failure,
)
from manakmarg.ingest.product_manual import ManualPage, parse_product_manual
from manakmarg.ingest.psg import parse_psg
from manakmarg.ingest.runs import RunRecorder
from tests.standards_seed import seed_standards

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "bis"
REGISTRY = sources.REGISTRY
PSG_URL = REGISTRY["bis_psg_page"].url
SEARCH_2062 = "https://lims.bis.gov.in/home/search_is_number/?is_number__doc_no=2062"
UTENSILS_MANUAL = "https://www.bis.gov.in/wp-content/uploads/2025/01/PM-IS-14756.pdf"
STEEL_MANUAL = "https://www.bis.gov.in/PDF/cart/PM_IS_2062.pdf"


def _read(name):
    return (FIXTURES / name).read_bytes()


def _json_pages(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["pages"]


def _rows(engine, table_name, **criteria):
    table = schema.metadata.tables[table_name]
    query = sa.select(table)
    for column, value in criteria.items():
        query = query.where(table.c[column] == value)
    with engine.connect() as conn:
        return conn.execute(query).mappings().all()


def _fetched(url, tmp_path):
    return FetchResult(
        url=url,
        final_url=url,
        status=200,
        content=b"%PDF-1.7",
        content_type="application/pdf",
        sha256="0" * 64,
        local_path=tmp_path / "document.pdf",
        retrieved_at=datetime(2026, 9, 12, 14, 30, tzinfo=timezone.utc),
        from_cache=False,
    )


@pytest.fixture
def engine(tmp_path):
    eng = get_engine(tmp_path / "loaders.sqlite3")
    init_db(eng)
    with eng.begin() as conn:
        sources.sync_registry(conn)
        seed_standards(conn, ["IS 14756:2024", "IS 2062:2011", "IS 2062 (Part 1):2025", "IS 269:2015"])
    yield eng
    eng.dispose()


def test_faqs_are_stored_with_links_and_a_reload_changes_nothing(engine):
    url = REGISTRY["bis_faq_product_certification"].url
    faqs = parse_faq_page(_read("faq_product_certification.html"), "product_certification", url)
    with RunRecorder(engine, "bis_faq_product_certification") as run:
        load_faqs(run, faqs, page_url=url)
    with RunRecorder(engine, "bis_faq_product_certification") as again:
        load_faqs(again, faqs, page_url=url)

    rows = _rows(engine, "faq")
    assert len(rows) == 28
    second = next(row for row in rows if row["ordinal"] == 2)
    links = [link["url"] for link in json.loads(second["answer_links"])]
    assert "https://www.manakonline.in/MANAK/ApplicationLicenceRelatedrpt" in links
    assert second["source_locator"] == f"{url}#faq-2"
    assert (again.stats["inserted"], again.stats["updated"], again.stats["unchanged"]) == (0, 0, 28)


def test_process_steps_scheme_documents_and_page_text(engine):
    apply_url = REGISTRY["bis_apply_licence_page"].url
    process_url = REGISTRY["bis_cert_process_page"].url
    overview_url = REGISTRY["bis_compulsory_overview_page"].url
    with RunRecorder(engine, "bis_apply_licence_page") as run:
        load_process_steps(run, parse_apply_licence(_read("apply_licence.html"), apply_url), page_url=apply_url)
    with RunRecorder(engine, "bis_cert_process_page") as run:
        load_scheme_documents(
            run, parse_certification_process_docs(_read("certification_process.html"), process_url), page_url=process_url
        )
    with RunRecorder(engine, "bis_compulsory_overview_page") as run:
        page_summary = load_web_page(run, parse_page_text(_read("compulsory_overview.html"), overview_url), url=overview_url)

    steps = sorted(_rows(engine, "process_step"), key=lambda row: row["ordinal"])
    assert [row["step_label"] for row in steps] == ["1", "2", "3", "4", "5", "5", "6", "7", "8", "9"]
    assert steps[0]["scheme_id"] is None
    documents = _rows(engine, "scheme_document")
    assert len(documents) == 15
    assert {row["scheme_id"] for row in documents} == {"SCHEME_I", "SCHEME_IV"}
    assert {row["scheme_id"] for row in _rows(engine, "certification_scheme")} == {"SCHEME_I", "SCHEME_IV"}

    page = _rows(engine, "document", url=overview_url)[0]
    assert (page["doc_type"], page["doc_date"], page["title"]) == (
        "web_page",
        date(2026, 4, 15),
        "Products under Compulsory Certification",
    )
    chunks = _rows(engine, "document_chunk", document_id=page["document_id"])
    assert page_summary["chunks"] == len(chunks) >= 1
    assert "basically voluntary in nature" in chunks[0]["text"]


def test_guidelines_resolve_standards_and_manual_sections_attach(engine, tmp_path):
    records = parse_psg(_read("psg.html"), PSG_URL)
    with RunRecorder(engine, "bis_psg_page") as run:
        summary = load_guidelines(run, records, page_url=PSG_URL)
    assert summary["guidelines"] == 54

    pages = [ManualPage(page["page"], page["text"], page.get("tables", [])) for page in _json_pages("pm_is_14756_pages.json")]
    with RunRecorder(engine, "bis_product_manual_documents") as run:
        result = load_product_manual(
            run,
            url=UTENSILS_MANUAL,
            title="STAINLESS STEEL UTENSILS",
            manual=parse_product_manual(pages),
            fetched=_fetched(UTENSILS_MANUAL, tmp_path),
            page_count=len(pages),
            source_page_url=PSG_URL,
        )
        record_document_failure(
            run,
            url=STEEL_MANUAL,
            doc_type="product_manual",
            title="Structural steel",
            source_page_url=PSG_URL,
            text_status="access_denied",
            http_status=403,
            reason="access blocked (http_403); not retried",
        )

    utensils = _rows(engine, "product_guideline", url=UTENSILS_MANUAL)[0]
    assert (utensils["family_key"], utensils["resolution"], utensils["parse_status"]) == ("IS 14756", "exact_version", "parsed")
    assert utensils["standard_id"] is not None
    assert utensils["document_id"] == result["document_id"]
    sections = sorted(_rows(engine, "guideline_section", guideline_id=utensils["guideline_id"]), key=lambda row: row["ordinal"])
    assert [row["section_key"] for row in sections][:2] == ["summary", "grouping"]
    sit = next(row for row in sections if row["section_key"] == "sit")
    assert any(item["requirement"] == "Staining Test" for item in json.loads(sit["structured_json"])["rows"])
    assert result["chunks"] == len(_rows(engine, "document_chunk", document_id=result["document_id"])) > 0

    steel = _rows(engine, "product_guideline", url=STEEL_MANUAL)[0]
    assert (steel["family_key"], steel["parse_status"]) == ("IS 2062", "access_denied")
    denied = _rows(engine, "document", url=STEEL_MANUAL)[0]
    assert (denied["text_status"], denied["http_status"]) == ("access_denied", 403)

    terms = {(row["term_norm"], row["origin"]) for row in _rows(engine, "product_term")}
    assert ("stainless steel utensils", "guideline_title") in terms


def test_text_documents_keep_page_ranges_and_link_to_their_order(engine, tmp_path):
    order_url = "https://www.bis.gov.in/wp-content/uploads/2023/08/cookware-qco.pdf"
    with engine.begin() as conn:
        conn.execute(
            schema.regulatory_order.insert().values(
                order_key=order_url,
                title="Cookware and Utensils (Quality Control) Order, 2023",
                url=order_url,
                order_kind="qco",
                source_id="bis_scheme_i_page",
                source_locator="test",
                retrieved_at="2026-09-12T00:00:00+00:00",
            )
        )
    texts = [(page["page"], page["text"]) for page in _json_pages("qco_cookware_2023_pages.json")]
    with RunRecorder(engine, "bis_qco_documents") as run:
        result = load_text_document(
            run,
            url=order_url,
            doc_type="regulatory_order",
            title="Cookware QCO",
            page_texts=texts,
            fetched=_fetched(order_url, tmp_path),
            source_page_url=None,
        )
        linked = link_order_document(run, order_url=order_url, document_id=result["document_id"])

    assert linked == 1
    assert _rows(engine, "regulatory_order", order_key=order_url)[0]["document_id"] == result["document_id"]
    chunks = sorted(_rows(engine, "document_chunk", document_id=result["document_id"]), key=lambda row: row["ordinal"])
    assert chunks and all(row["page_start"] <= row["page_end"] for row in chunks)
    assert chunks[0]["page_start"] == texts[0][0]
    assert _rows(engine, "document", url=order_url)[0]["text_status"] == "text_extracted"


def test_labs_and_scope_rows_link_by_osl_code_name_and_published_version(engine):
    recognised_url = REGISTRY["lims_recognised_labs"].url
    bis_url = REGISTRY["lims_bis_labs"].url
    with RunRecorder(engine, "lims_recognised_labs") as run:
        load_labs(
            run,
            parse_lims_directory(_read("lims_recognised_labs_page1.html"), "BIS_RECOGNISED", recognised_url).labs,
            directory_url=recognised_url,
        )
    with RunRecorder(engine, "lims_bis_labs") as run:
        load_labs(run, parse_lims_directory(_read("lims_bis_labs.html"), "BIS_LAB", bis_url).labs, directory_url=bis_url)
    scope_rows = parse_lims_scope_search(_read("lims_scope_search_2062_page1.html"), SEARCH_2062).rows
    with RunRecorder(engine, "lims_is_scope_search") as run:
        summary = load_lab_scope(run, scope_rows, query_doc_no="2062", search_url=SEARCH_2062)

    assert len(_rows(engine, "laboratory")) == 30
    lab = _rows(engine, "laboratory", lab_key="lims:15")[0]
    assert (lab["osl_code"], lab["city"], lab["state"], lab["lims_validity_date"]) == ("8102006", "Delhi", "Delhi", date(2026, 12, 31))
    assert "contact_person" not in lab

    rows = _rows(engine, "lab_scope")
    assert (len(rows), summary["labs_linked"], summary["standards_linked"]) == (6, 2, 4)
    unique = next(row for row in rows if row["osl_code_raw"] == "9134536")
    assert unique["lab_id"] == _rows(engine, "laboratory", osl_code="9134536")[0]["lab_id"]
    assert (unique["family_key"], unique["version_year"]) == ("IS 2062 (Part 1)", 2025)
    assert unique["standard_id"] is not None
    erl = next(row for row in rows if row["lab_name_raw"] == "BIS, Eastern Regional Laboratory (ERL)")
    assert erl["lab_id"] == _rows(engine, "laboratory", name="BIS, Eastern Regional Laboratory (ERL)")[0]["lab_id"]
    assert (erl["standard_id"], erl["family_key"]) == (None, "IS 2062 (Part 2)")
    items = sorted(_rows(engine, "lab_scope_item", scope_id=unique["scope_id"]), key=lambda row: row["ordinal"])
    assert len(items) == 98
    assert (items[0]["clause"], items[0]["parameter"], items[0]["charge"]) == ("Cl-6", "MANUFACTURE", 100.0)

    with RunRecorder(engine, "lims_is_scope_search") as again:
        load_lab_scope(again, scope_rows[:3], query_doc_no="2062", search_url=SEARCH_2062)
    assert (again.stats["inserted"], again.stats["updated"], again.stats["retired"]) == (0, 0, 3)
    assert len([row for row in _rows(engine, "lab_scope") if row["is_current"]]) == 3


def test_group_list_entries_keep_their_status_basis(engine):
    url = REGISTRY["bis_lab_group1_list"].url
    group = parse_group_list(_json_pages("lab_group1_tables.json"), group=1)
    with RunRecorder(engine, "bis_lab_group1_list") as run:
        summary = load_group_list(run, group, document_url=url)

    assert len(_rows(engine, "lab_list_entry")) == 18
    assert summary["statuses"] == {"LISTED": 18}
    atharva = _rows(engine, "lab_list_entry", entry_key="group1:osl:8134206")[0]
    assert "09-03-2026" in atharva["status_basis"]
    assert atharva["list_as_of"] == "2026-08-24"
    assert atharva["source_locator"].startswith(f"{url}#page-2/")


def test_hallmarking_centres_events_and_gazette_checked_districts(engine):
    ahc_url = REGISTRY["manak_ahc_list"].url
    events_url = REGISTRY["manak_ahc_cancelled_suspended"].url
    districts_url = REGISTRY["bis_hm_districts_phasewise"].url
    with RunRecorder(engine, "manak_ahc_list") as run:
        ahc_summary = load_ahcs(run, parse_ahc_list(_read("ahc_list.html"), ahc_url), page_url=ahc_url)
    with RunRecorder(engine, "manak_ahc_cancelled_suspended") as run:
        load_ahc_events(run, parse_ahc_events(_read("ahc_cancelled_suspended.html"), events_url), page_url=events_url)
    records = parse_phasewise_districts([page["text"] for page in _json_pages("hm_districts_phasewise_2026_09.json")])
    annex = parse_gazette_annex([page["text"] for page in _json_pages("hm_gazette_so4345_2026_08_03_english.json")])
    validation = validate_against_gazette(records, annex)
    with RunRecorder(engine, "bis_hm_districts_phasewise") as district_run:
        district_summary = load_districts(district_run, records, validation, document_url=districts_url)
    gazette_url = REGISTRY["bis_hm_gazette_2026_08_03"].url
    with RunRecorder(engine, "bis_hm_gazette_2026_08_03") as gazette_run:
        gazette_summary = load_gazette_only_districts(
            gazette_run, list(validation.extra_in_gazette), document_url=gazette_url, note="Listed in the Gazette annex only; verify."
        )

    assert ahc_summary["ahcs"] == 31
    durgapur = _rows(engine, "ahc", recognition_no="ERO/RAHC/R-700060")[0]
    assert (durgapur["district"], durgapur["area"], durgapur["state"], durgapur["gold"], durgapur["silver"]) == (
        "Bardhaman",
        None,
        "West Bengal",
        True,
        False,
    )
    assert len(_rows(engine, "ahc_status_event")) == 15

    assert (district_summary["districts"], district_summary["not_in_gazette"], district_summary["gazette_annex_only"]) == (392, 1, 1)
    kakinada = _rows(engine, "hallmarking_district", district_key="Andhra Pradesh|kakinada")[0]
    assert (kakinada["gazette_validated"], kakinada["phase_no"]) == (False, 3)
    gurgaon = _rows(engine, "hallmarking_district", district_key="Haryana|gurgaon")[0]
    assert gurgaon["gazette_validated"] is True
    assert "Gurugram" in gurgaon["gazette_note"]
    assert {"gurgaon", "gurugram"} <= {row["alias_norm"] for row in _rows(engine, "district_alias", district_id=gurgaon["district_id"])}
    run_row = _rows(engine, "ingestion_run", run_id=district_run.run_id)[0]
    assert "gazette_annex_only: Rajasthan / Jalore" in run_row["errors_json"]

    assert gazette_summary["districts"] == 1
    jalore = _rows(engine, "hallmarking_district", district_key="Rajasthan|jalore")[0]
    assert (jalore["phase_no"], jalore["gazette_validated"], jalore["source_id"]) == (None, True, "bis_hm_gazette_2026_08_03")
    assert jalore["source_locator"].startswith(gazette_url)
