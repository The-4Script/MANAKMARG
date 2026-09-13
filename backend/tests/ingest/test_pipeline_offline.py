"""Pipeline wiring, run against fixture snapshots served by a fake HTTP session (no network)."""

from pathlib import Path

import pytest
import sqlalchemy as sa

from manakmarg.db import schema
from manakmarg.db.engine import get_engine
from manakmarg.ingest.fetch import Fetcher, request_url
from manakmarg.ingest.pipeline import run_pipeline
from manakmarg.ingest.sources import REGISTRY

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "bis"
EMPTY_LIMS_PAGE = b"<html><body><table id='dataTable'><thead><tr><th>S.No.</th></tr></thead><tbody></tbody></table></body></html>"
SEARCH = "https://lims.bis.gov.in/home/search_is_number/?is_number__doc_no="

ROUTES = {
    REGISTRY["bis_scheme_i_page"].url: "scheme_i.html",
    REGISTRY["bis_scheme_ii_page"].url: "scheme_ii.html",
    REGISTRY["bis_scheme_iv_page"].url: "scheme_iv.html",
    REGISTRY["bis_scheme_x_page"].url: "scheme_x.html",
    REGISTRY["bis_upcoming_qco_page"].url: "upcoming_qcos.html",
    REGISTRY["bis_compulsory_overview_page"].url: "compulsory_overview.html",
    REGISTRY["bis_apply_licence_page"].url: "apply_licence.html",
    REGISTRY["bis_cert_process_page"].url: "certification_process.html",
    REGISTRY["bis_faq_product_certification"].url: "faq_product_certification.html",
    REGISTRY["bis_faq_laboratory"].url: "faq_laboratory.html",
    REGISTRY["bis_faq_hallmarking_general"].url: "faq_hallmarking_general.html",
    REGISTRY["bis_faq_hallmarking_mandatory"].url: "faq_hallmarking_mandatory.html",
    REGISTRY["bis_psg_page"].url: "psg.html",
    REGISTRY["lims_recognised_labs"].url: "lims_recognised_labs_page1.html",
    REGISTRY["lims_bis_labs"].url: "lims_bis_labs.html",
    REGISTRY["lims_empanelled_labs"].url: "lims_empanelled_labs_page1.html",
    SEARCH + "2062": "lims_scope_search_2062_page1.html",
    SEARCH + "269": "lims_scope_search_269_page1.html",
    REGISTRY["manak_ahc_list"].url: "ahc_list.html",
    REGISTRY["manak_ahc_cancelled_suspended"].url: "ahc_cancelled_suspended.html",
}


class _Response:
    def __init__(self, url, status, content, content_type):
        self.url = url
        self.status_code = status
        self.content = content
        self.headers = {"content-type": content_type}


class FixtureSession:
    def __init__(self):
        self.requested: list[str] = []

    def get(self, url, params=None, headers=None, timeout=None, allow_redirects=True):
        full = request_url(url, params)
        self.requested.append(full)
        if "lims.bis.gov.in" in full and "page=" in full:
            return _Response(full, 200, EMPTY_LIMS_PAGE, "text/html")
        name = ROUTES.get(full)
        if name is None:
            return _Response(full, 404, b"not found", "text/html")
        return _Response(full, 200, (FIXTURES / name).read_bytes(), "text/html; charset=utf-8")


def _count(engine, table_name, **criteria):
    table = schema.metadata.tables[table_name]
    query = sa.select(sa.func.count()).select_from(table)
    for column, value in criteria.items():
        query = query.where(table.c[column] == value)
    with engine.connect() as conn:
        return conn.execute(query).scalar()


@pytest.fixture(scope="module")
def pipeline_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("pipeline")
    engine = get_engine(root / "pipeline.sqlite3")
    session = FixtureSession()
    fetcher = Fetcher(root / "cache", min_delay_s=0, user_agent="test-agent", session=session, sleep=lambda _: None)
    report = run_pipeline(
        engine,
        fetcher,
        steps=["schemes", "pages", "psg", "labs", "lab_scope", "hallmarking", "index", "quality"],
        data_dir=root,
        manifest_dir=root / "manifests",
        docs_dir=root / "docs",
        index_dir=root / "indexes",
    )
    yield root, engine, report, session
    engine.dispose()


def test_every_selected_source_is_loaded_or_reported(pipeline_run):
    _, _, report, _ = pipeline_run
    assert report["schemes"]["bis_scheme_i_page"]["coverage_rows"] > 0
    assert report["pages"]["bis_faq_product_certification"]["faqs"] == 28
    assert report["pages"]["bis_hallmarking_overview_page"]["status"] == "fetch_failed"
    assert report["psg"]["guidelines"] == 54
    assert (report["labs"]["lims_recognised_labs"]["labs"], report["labs"]["lims_recognised_labs"]["pages"]) == (20, 22)
    assert report["labs"]["bis_lab_group1_list"]["status"] == "fetch_failed"
    assert report["lab_scope"]["2062"]["rows"] == 6
    assert report["lab_scope"]["374"]["status"] == "fetch_failed"
    assert report["hallmarking"]["manak_ahc_list"]["ahcs"] == 31
    assert report["hallmarking"]["bis_hm_districts_phasewise"]["status"] == "fetch_failed"


def test_database_contents_and_indexes(pipeline_run):
    _, engine, report, _ = pipeline_run
    assert _count(engine, "faq") == 28 + 10 + 25 + 6
    assert _count(engine, "laboratory") == 20 + 10 + 20
    assert _count(engine, "lab_scope") == 6 + 4
    assert _count(engine, "ahc") == 31
    assert _count(engine, "ahc_status_event") == 15
    assert report["index"]["faq_fts"] == 69
    assert report["index"]["vectors"]["faq"] == 69
    assert (pipeline_run[0] / "indexes" / "coverage.joblib").exists()
    with engine.connect() as conn:
        hits = conn.exec_driver_sql("SELECT count(*) FROM faq_fts WHERE faq_fts MATCH 'hallmarking'").scalar()
    assert hits > 0


def test_failed_sources_are_recorded_as_failed_runs(pipeline_run):
    _, engine, _, _ = pipeline_run
    assert _count(engine, "ingestion_run", source_id="bis_hm_districts_phasewise", status="failed") == 1
    assert _count(engine, "ingestion_run", source_id="manak_ahc_list", status="success") == 1


def test_reports_are_written_outside_the_repository(pipeline_run):
    root, _, _, _ = pipeline_run
    assert (root / "manifests" / "data_quality.json").exists()
    assert (root / "docs" / "DATA_QUALITY.md").exists()
    assert (root / "manifests" / "sources.json").exists()


def test_cached_snapshots_replay_offline_without_changes(pipeline_run):
    root, engine, _, session = pipeline_run
    requests_before = len(session.requested)
    offline = Fetcher(root / "cache", min_delay_s=0, user_agent="test-agent", offline=True, session=session, sleep=lambda _: None)
    report = run_pipeline(engine, offline, steps=["pages"], data_dir=root, manifest_dir=root / "manifests", docs_dir=root / "docs")
    assert len(session.requested) == requests_before
    assert report["pages"]["bis_faq_laboratory"]["faqs"] == 10
    assert report["pages"]["bis_hallmarking_overview_page"]["status"] == "fetch_failed"
    with engine.connect() as conn:
        latest = conn.execute(
            sa.select(schema.ingestion_run)
            .where(schema.ingestion_run.c.source_id == "bis_faq_laboratory")
            .order_by(schema.ingestion_run.c.run_id.desc())
        ).mappings().first()
    assert (latest["inserted"], latest["updated"], latest["unchanged"]) == (0, 0, 10)
