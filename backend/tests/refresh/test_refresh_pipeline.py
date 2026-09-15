"""The weekly refresh activates a new dataset only when every step passes, and otherwise keeps the active one."""

import json
import shutil
import sqlite3

import pytest
import sqlalchemy as sa

from manakmarg.core.config import Settings
from manakmarg.db import schema
from manakmarg.db.engine import get_engine
from manakmarg.refresh import log as refresh_log
from manakmarg.refresh import pipeline
from manakmarg.refresh.pipeline import RefreshPaths, run_refresh
from manakmarg.refresh.portal import Ministry, PortalChanged
from manakmarg.refresh.smoke import SmokeResult
from manakmarg.search import fts_search
from manakmarg.search.vectors import RUNTIME_CORPORA, build_vector_indexes
from tests.fixture_db import SEEDED_STANDARDS, build_fixture_db
from tests.refresh.exports import FakePortal, rows_for, write_export

FOOD = Ministry(11, "Ministry of Consumer Affairs, Food and Public Distribution", "enc-11", 2)
NITI = Ministry(42, "NITI Aayog", "enc-42", 1)
COAL = Ministry(77, "Ministry of Coal", "enc-77", 0)  # no standards: hidden on the portal, not downloaded
MINISTRIES = {FOOD: ["IS 13688:2020", "IS 14543:2024"], NITI: ["IS 269:2015"], COAL: []}
TOTAL = [*SEEDED_STANDARDS, "IS 13688:2020"]
QUERIES = (("What is IS 2062?", "en"), ("Is hallmarking mandatory in Jaipur?", "en"), ("capital of France", "en"))
REQUIRED_LOG_FIELDS = {
    "refresh_id", "started_at", "completed_at", "source_urls", "dataset_version", "overall_export", "groupwise_export",
    "ministries_detected", "ministry_files_downloaded", "failed_ministries", "records", "validation", "tests", "activation", "status",
}


def _copy_db(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    origin, destination = sqlite3.connect(source), sqlite3.connect(target)
    try:
        origin.backup(destination)
    finally:
        destination.close()
        origin.close()


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    root = tmp_path_factory.mktemp("refresh_template")
    engine = build_fixture_db(root / "active.sqlite3")
    with engine.connect() as conn:
        build_vector_indexes(conn, root / "indexes", corpora=RUNTIME_CORPORA)
    engine.dispose()
    return root


@pytest.fixture
def env(template, tmp_path):
    db = tmp_path / "processed" / "manakmarg.sqlite3"
    _copy_db(template / "active.sqlite3", db)
    shutil.copytree(template / "indexes", tmp_path / "indexes")
    (tmp_path / "manifests").mkdir()
    data_dir = tmp_path / "data"
    write_export(data_dir / "2.xlsx", None, rows_for(SEEDED_STANDARDS))  # the supplied group-wise export, carried over
    rp = RefreshPaths(db, tmp_path / "indexes", tmp_path / "manifests", data_dir, tmp_path / "refresh")
    settings = Settings(_env_file=None, db_path=db, refresh_dir=tmp_path / "refresh", fetch_min_delay_s=0)
    return settings, rp


def _refresh(env, portal, **kwargs):
    settings, rp = env
    kwargs.setdefault("smoke_queries", QUERIES)
    return run_refresh(settings, portal=portal, refresh_paths=rp, **kwargs)


def _current_keys(db):
    engine = get_engine(db)
    try:
        with engine.connect() as conn:
            return set(conn.execute(sa.select(schema.standard.c.std_key).where(schema.standard.c.is_current.is_(True))).scalars())
    finally:
        engine.dispose()


def _count(db, table):
    engine = get_engine(db)
    try:
        with engine.connect() as conn:
            return conn.execute(sa.select(sa.func.count()).select_from(schema.metadata.tables[table])).scalar()
    finally:
        engine.dispose()


def _assert_active_unchanged(env, keys_before):
    settings, rp = env
    assert _current_keys(rp.db_path) == keys_before
    assert refresh_log.read_active(rp.refresh_dir) is None
    assert not list(rp.db_path.parent.glob("*.incoming")) and not list(rp.index_dir.glob("*.incoming"))


def test_successful_refresh_updates_standards_and_ministries_and_activates(env):
    settings, rp = env
    listings_before = _count(rp.db_path, "scheme_coverage")
    swaps = []
    report = _refresh(env, FakePortal(TOTAL, MINISTRIES), before_swap=lambda: swaps.append("before"), after_swap=lambda: swaps.append("after"))

    assert report["status"] == "success" and report["activation"]["status"] == "activated", report["error"]
    assert swaps == ["before", "after"]
    assert report["ministries_detected"] == 3 and report["ministries_with_standards"] == 2 and report["ministry_files_downloaded"] == 2
    assert report["failed_ministries"] == [] and report["groupwise_export"]["status"] == "not_collected"
    assert report["groupwise_export"]["carried_files"] == ["groupwise-carried-2.xlsx"]
    assert report["records"]["added"] >= 1 and "IS 13688:2020" in report["records"]["examples"]["added"]
    assert report["classification"]["ministry_nodes_after"] == 2 and report["tests"]["smoke"]["passed"]

    engine = get_engine(rp.db_path)
    try:
        with engine.connect() as conn:
            node = schema.classification_node
            names = set(conn.execute(sa.select(node.c.name).where(node.c.is_current.is_(True))).scalars())
            assert {FOOD.name, NITI.name} <= names  # NITI Aayog is classified although its heading is not "Ministry of …"
            assert fts_search.search_standards(conn, "Pasteurized")  # rebuilt full-text index
    finally:
        engine.dispose()
    assert _count(rp.db_path, "scheme_coverage") == listings_before  # compulsory listings untouched

    active = refresh_log.read_active(rp.refresh_dir)
    assert active["version"] == report["refresh_id"] == report["dataset_version"]
    version_dir = rp.refresh_dir / report["refresh_id"]
    assert (version_dir / "dataset.tar.gz").exists() and (version_dir / "previous-dataset.tar.gz").exists()
    assert (version_dir / "report.json").exists() and not (version_dir / "staging").exists()
    entry = refresh_log.read_entries(rp.refresh_dir)[-1]
    assert REQUIRED_LOG_FIELDS <= set(entry) and entry["overall_export"]["rows"] == len(TOTAL)


def test_a_failed_ministry_download_keeps_the_previous_dataset(env):
    keys = _current_keys(env[1].db_path)
    report = _refresh(env, FakePortal(TOTAL, MINISTRIES, fail={11}))
    assert report["status"] == "failed" and report["activation"]["status"] == "not_activated"
    assert report["failed_ministries"][0]["name"] == FOOD.name and report["failed_ministries"][0]["status"] == "download_failed"
    _assert_active_unchanged(env, keys)
    assert refresh_log.read_entries(env[1].refresh_dir)[-1]["status"] == "failed"


def test_an_access_refusal_stops_further_downloads(env):
    portal = FakePortal(TOTAL, MINISTRIES, blocked={11})
    report = _refresh(env, portal)
    assert report["status"] == "failed"
    assert [item["status"] for item in report["failed_ministries"]] == ["access_blocked", "not_attempted"]
    assert NITI.name not in portal.requested


@pytest.mark.parametrize(
    "portal, reason",
    [
        (FakePortal(TOTAL, MINISTRIES, corrupt={42}), "ministry export"),
        (FakePortal(TOTAL, MINISTRIES, total_headers=["Sl#", "Standard Number", "Date of Publish", "Title"]), "missing columns"),
        (FakePortal(TOTAL, MINISTRIES, total_title="Ministry of Coal"), "expected 'Total'"),
        (FakePortal(TOTAL, MINISTRIES, list_error=PortalChanged("the Ministry-wise page lists no ministries")), "Ministry-wise list"),
        (FakePortal(SEEDED_STANDARDS[:2], MINISTRIES), "below"),
    ],
)
def test_invalid_downloads_or_changed_pages_keep_the_previous_dataset(env, portal, reason):
    keys = _current_keys(env[1].db_path)
    report = _refresh(env, portal)
    assert report["status"] == "failed" and reason in report["error"], report["error"]
    _assert_active_unchanged(env, keys)


def test_failing_regression_checks_block_activation(env, monkeypatch):
    keys = _current_keys(env[1].db_path)
    monkeypatch.setattr(pipeline, "compare_datasets", lambda *args, **kwargs: SmokeResult(passed=False, checked=1, failures=[{"query": "q", "field": "route"}]))
    report = _refresh(env, FakePortal(TOTAL, MINISTRIES))
    assert report["status"] == "failed" and "regression" in report["error"] and report["tests"]["smoke"]["status"] == "failed"
    _assert_active_unchanged(env, keys)


def test_a_failed_swap_leaves_the_previous_dataset(env, monkeypatch):
    keys = _current_keys(env[1].db_path)

    def refuse(source, target):
        raise PermissionError("database file is in use")

    monkeypatch.setattr(pipeline, "_replace_file", refuse)
    report = _refresh(env, FakePortal(TOTAL, MINISTRIES))
    assert report["status"] == "failed" and report["activation"]["status"] == "failed"
    _assert_active_unchanged(env, keys)


def test_an_unusable_activated_dataset_is_rolled_back(env, monkeypatch):
    keys = _current_keys(env[1].db_path)

    def unusable(db_path):
        raise RuntimeError("the activated database is not usable")

    monkeypatch.setattr(pipeline, "_verify_activated", unusable)
    report = _refresh(env, FakePortal(TOTAL, MINISTRIES))
    assert report["activation"]["status"] == "rolled_back" and report["status"] == "failed"
    _assert_active_unchanged(env, keys)


def test_dry_run_stages_without_activating(env):
    keys = _current_keys(env[1].db_path)
    report = _refresh(env, FakePortal(TOTAL, MINISTRIES), activate=False)
    assert report["status"] == "staged" and report["activation"]["status"] == "not_activated"
    assert "IS 13688:2020" in _current_keys(report["activation"]["staged_database"])
    _assert_active_unchanged(env, keys)


def test_a_second_refresh_is_skipped_while_one_runs_and_offline_mode_refuses(env):
    settings, rp = env
    rp.refresh_dir.mkdir(parents=True)
    (rp.refresh_dir / pipeline.LOCK_NAME).write_text(json.dumps({"pid": 1}))
    assert _refresh(env, FakePortal(TOTAL, MINISTRIES))["status"] == "skipped"
    (rp.refresh_dir / pipeline.LOCK_NAME).unlink()
    offline = run_refresh(settings.model_copy(update={"offline": True}), portal=FakePortal(TOTAL, MINISTRIES), refresh_paths=rp, smoke_queries=QUERIES)
    assert offline["status"] == "failed" and "offline" in offline["error"]
    assert [entry["status"] for entry in refresh_log.read_entries(rp.refresh_dir)] == ["skipped", "failed"]


def test_status_summarises_the_log(env):
    settings, rp = env
    assert refresh_log.read_status(rp.refresh_dir)["state"] == "never_run"
    report = _refresh(env, FakePortal(TOTAL, MINISTRIES))
    status = refresh_log.read_status(rp.refresh_dir)
    assert status["state"] == "success" and status["active_version"] == report["refresh_id"]
    assert status["last_refresh"]["activation"] == "activated" and status["last_success_at"]
