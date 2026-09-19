"""Weekly BIS standards refresh: download → validate → stage → index → regression-check → activate.

The active dataset (``settings.db_path`` and ``data/indexes``) is replaced only when every step has passed. A refresh
works in ``data/refresh/<version>/``: the downloaded files, a staged copy of the database, its indexes and a report.
Any failure — a download, a corrupt or unexpected file, validation, ingestion, indexing, the regression checks or the
swap itself — leaves the active files in place (a failed swap is rolled back from the snapshot taken just before it)
and is written to ``data/refresh/refresh_log.jsonl``. See docs/DATA_REFRESH.md.

Only published-standards metadata and ministry classification are refreshed. Compulsory-certification listings,
QCOs, Product Manuals, laboratories, hallmarking and HSN data are not touched, and nothing here derives a
certification requirement from the existence of a standard or its ministry.
"""

import importlib.util
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import sqlalchemy as sa

from manakmarg.core import clock, paths
from manakmarg.core.config import Settings
from manakmarg.core.data_bundle import BundleError, data_status, export_bundle, import_bundle
from manakmarg.db import fts, schema
from manakmarg.db.engine import get_engine, init_db
from manakmarg.ingest import sources
from manakmarg.ingest.excel_standards import SOURCE_MINISTRY, SOURCE_TOTAL, classify_export, ingest_standard_exports, read_export
from manakmarg.ingest.fetch import AccessBlocked, FetchError
from manakmarg.ingest.quality import run_quality_checks
from manakmarg.reasoning.intents import Gazetteer
from manakmarg.refresh import log as refresh_log
from manakmarg.refresh.portal import (
    GROUP_PAGE,
    LIST_EXPORT_URL,
    MINISTRIES_URL,
    MINISTRY_COUNTS_URL,
    MINISTRY_PAGE,
    OVERALL_LIST_PAGE,
    BisPortalClient,
    Ministry,
    PortalChanged,
)
from manakmarg.refresh.smoke import DEFAULT_QUERIES, compare_datasets
from manakmarg.refresh.validation import check_export
from manakmarg.search import fts_search
from manakmarg.search.vectors import CORPORA, RUNTIME_CORPORA, build_vector_indexes

log = logging.getLogger(__name__)

LOCK_NAME = "refresh.lock"
STALE_LOCK_S = 6 * 3600
DOWNLOAD_ERRORS = (AccessBlocked, FetchError, PortalChanged)
GROUPWISE_REASON = (
    "The Group-wise page's aggregate Excel download is offered only to signed-in users whose role the portal approves, "
    "so it is not collected automatically. An existing group-wise export in data/ is reused unchanged, which keeps its "
    "flags; the refresh does not create or change Department or Group classification."
)
LOG_FIELDS = (
    "refresh_id",
    "trigger",
    "status",
    "started_at",
    "completed_at",
    "source_urls",
    "dataset_version",
    "previous_version",
    "overall_export",
    "groupwise_export",
    "ministries_detected",
    "ministries_with_standards",
    "ministry_files_downloaded",
    "failed_ministries",
    "records",
    "classification",
    "validation",
    "tests",
    "activation",
    "error",
)


class RefreshFailed(Exception):
    """A refresh step failed; the active dataset stays in place."""


@dataclass
class RefreshPaths:
    db_path: Path
    index_dir: Path
    manifest_dir: Path
    data_dir: Path
    refresh_dir: Path

    @classmethod
    def from_settings(cls, settings: Settings) -> "RefreshPaths":
        return cls(Path(settings.db_path), paths.INDEX_DIR, paths.MANIFEST_DIR, paths.DATA_DIR, Path(settings.refresh_dir))


# --------------------------------------------------------------------------- entry point


def run_refresh(
    settings: Settings,
    *,
    portal=None,
    refresh_paths: RefreshPaths | None = None,
    trigger: str = "manual",
    activate: bool = True,
    run_pytest: bool | None = None,
    smoke_queries=DEFAULT_QUERIES,
    before_swap=None,
    after_swap=None,
) -> dict:
    """Run one refresh and return its report. Never raises for a refresh failure; the report says what happened.

    ``before_swap``/``after_swap`` let a running server close its database connections before the files are replaced
    and reopen them (with fresh caches) afterwards."""
    rp = refresh_paths or RefreshPaths.from_settings(settings)
    rp.refresh_dir.mkdir(parents=True, exist_ok=True)
    started = clock.now_utc()
    version = _new_version(rp.refresh_dir, started)
    report = {
        "refresh_id": version,
        "trigger": trigger,
        "status": "running",
        "started_at": started.isoformat(timespec="seconds"),
        "completed_at": None,
        "source_urls": {
            "overall_list_page": OVERALL_LIST_PAGE,
            "ministry_wise_page": MINISTRY_PAGE,
            "group_wise_page": GROUP_PAGE,
            "export_request": LIST_EXPORT_URL,
            "ministries_request": MINISTRIES_URL,
            "ministry_counts_request": MINISTRY_COUNTS_URL,
        },
        "dataset_version": None,
        "previous_version": (refresh_log.read_active(rp.refresh_dir) or {}).get("version"),
        "overall_export": {"status": "not_run"},
        "groupwise_export": {"status": "not_run"},
        "ministries_detected": 0,
        "ministries_with_standards": 0,
        "ministry_files_downloaded": 0,
        "failed_ministries": [],
        "records": None,
        "classification": None,
        "indexes": None,
        "quality": None,
        "validation": {"passed": False, "problems": [], "warnings": []},
        "tests": {"smoke": {"status": "not_run"}, "pytest": {"status": "not_run"}},
        "activation": {"status": "not_activated"},
        "error": None,
    }
    lock = _acquire_lock(rp.refresh_dir)
    if lock is None:
        report["status"] = "skipped"
        report["error"] = "another refresh is already running"
        report["activation"]["reason"] = report["error"]
        report["dataset_version"] = report["previous_version"]
        return _finish(rp, report, None, settings.refresh_keep_versions)

    version_dir = rp.refresh_dir / version
    pytest_wanted = settings.refresh_run_pytest if run_pytest is None else run_pytest
    try:
        _refresh(settings, rp, report, version_dir, portal, activate, pytest_wanted, smoke_queries, before_swap, after_swap)
    except RefreshFailed as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
    except Exception as exc:  # the schedule must never crash the server, and nothing unverified may be activated
        log.exception("BIS data refresh failed unexpectedly")
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        _release_lock(lock)
    if report["status"] not in ("success", "staged") and report["activation"]["status"] == "not_activated":
        report["activation"].setdefault("reason", "the refresh did not pass; the previous dataset stays active")
    report["dataset_version"] = (refresh_log.read_active(rp.refresh_dir) or {}).get("version")
    return _finish(rp, report, version_dir, settings.refresh_keep_versions)


def log_entry(report: dict) -> dict:
    """The refresh-log line for a report (the full report is kept in ``<version>/report.json``)."""
    entry = {key: report.get(key) for key in LOG_FIELDS}
    overall = report.get("overall_export") or {}
    entry["overall_export"] = {key: overall.get(key) for key in ("status", "file_url", "sha256", "bytes", "error") if key in overall}
    check = overall.get("check") or {}
    entry["overall_export"].update({key: check.get(key) for key in ("rows", "generated_on", "problems") if key in check})
    smoke = (report.get("tests") or {}).get("smoke") or {}
    entry["tests"] = {
        "smoke": {key: smoke.get(key) for key in ("status", "passed", "checked", "failures") if key in smoke},
        "pytest": (report.get("tests") or {}).get("pytest"),
    }
    return entry


# --------------------------------------------------------------------------- the refresh


def _refresh(settings, rp: RefreshPaths, report: dict, version_dir: Path, portal, activate: bool, run_pytest: bool, smoke_queries, before_swap, after_swap) -> None:
    if settings.offline:
        raise RefreshFailed("offline mode is set (MANAKMARG_OFFLINE=true); the refresh needs network access")
    portal = portal or BisPortalClient(
        user_agent=settings.user_agent, min_delay_s=settings.fetch_min_delay_s, export_timeout_s=settings.refresh_export_timeout_s
    )
    downloads = version_dir / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    problems, warnings = report["validation"]["problems"], report["validation"]["warnings"]
    classifications: dict[str, str] = {}
    manifest: list[dict] = []

    # 1. overall standard list
    try:
        total = portal.download_total(downloads)
    except DOWNLOAD_ERRORS as exc:
        report["overall_export"] = {"status": _download_status(exc), "error": str(exc)}
        raise RefreshFailed(f"the overall standard list could not be downloaded: {exc}") from exc
    total_check = check_export(total.path, kind="total")
    report["overall_export"] = {"status": "valid" if total_check.ok else "invalid", **total.to_dict(), "check": asdict(total_check)}
    manifest.append(report["overall_export"])
    classifications[total.path.name] = "total_export"
    problems += [f"overall export: {problem}" for problem in total_check.problems]
    warnings += [f"overall export: {warning}" for warning in total_check.warnings]

    # 2. group-wise (not collectable anonymously; reuse the existing export)
    carried = _carry_groupwise_exports(rp.data_dir, downloads)
    classifications.update({name: "untitled_export" for name in carried})
    report["groupwise_export"] = {"status": "not_collected", "reason": GROUPWISE_REASON, "carried_files": carried}

    # 3. every ministry, one file each
    try:
        ministries = portal.list_ministries()
    except DOWNLOAD_ERRORS as exc:
        report["ministry_listing"] = {"status": _download_status(exc), "error": str(exc)}
        raise RefreshFailed(f"the Ministry-wise list could not be read: {exc}") from exc
    wanted = [ministry for ministry in ministries if (ministry.published_count or 0) > 0]
    report["ministries_detected"] = len(ministries)
    report["ministries_with_standards"] = len(wanted)
    downloaded = 0
    for index, ministry in enumerate(wanted):
        try:
            export = portal.download_ministry(ministry, downloads)
        except DOWNLOAD_ERRORS as exc:
            report["failed_ministries"].append(_ministry_failure(ministry, _download_status(exc), str(exc)))
            if isinstance(exc, AccessBlocked):
                for skipped in wanted[index + 1 :]:
                    report["failed_ministries"].append(_ministry_failure(skipped, "not_attempted", "stopped after the portal refused access"))
                break
            continue
        check = check_export(
            export.path, kind="ministry", expected_title=ministry.name, expected_rows=ministry.published_count, min_row_ratio=settings.refresh_min_row_ratio
        )
        manifest.append({**export.to_dict(), "check": asdict(check)})
        if not check.ok:
            report["failed_ministries"].append(_ministry_failure(ministry, "invalid", "; ".join(check.problems)))
            continue
        warnings += [f"{ministry.name}: {warning}" for warning in check.warnings]
        classifications[export.path.name] = "ministry_node"
        downloaded += 1
    report["ministry_files_downloaded"] = downloaded
    (version_dir / "downloads.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    # 4. dataset-level validation
    if report["failed_ministries"]:
        problems.append(f"{len(report['failed_ministries'])} of {len(wanted)} ministry export(s) failed")
    if not wanted:
        problems.append("no ministry with published standards was detected; the Ministry-wise page may have changed")
    baseline = _active_master_count(rp.db_path)
    if baseline and total_check.rows < baseline * (1 - settings.refresh_max_shrink):
        problems.append(
            f"the overall export has {total_check.rows} rows, more than {settings.refresh_max_shrink:.0%} below the "
            f"{baseline} standards of the active dataset"
        )
    previous = refresh_log.last_successful(rp.refresh_dir) or {}
    if previous.get("ministries_with_standards") and len(wanted) < previous["ministries_with_standards"] * (1 - settings.refresh_max_shrink):
        problems.append(f"{len(wanted)} ministries with standards, down from {previous['ministries_with_standards']} in the last successful refresh")
    report["validation"]["passed"] = not problems
    if problems:
        raise RefreshFailed("validation failed: " + "; ".join(problems[:5]))

    # 5. stage: a copy of the active database, updated from the downloaded files
    staging = version_dir / "staging"
    staged_db, staged_indexes = staging / "manakmarg.sqlite3", staging / "indexes"
    active_ready = data_status(rp.db_path)["ready"]
    if rp.db_path.exists():
        _copy_database(rp.db_path, staged_db)
    engine = get_engine(staged_db)
    try:
        init_db(engine)
        with engine.begin() as conn:
            sources.sync_registry(conn)
        before = _metrics(engine)
        summary = ingest_standard_exports(engine, downloads, classifications=classifications)
        not_loaded = sorted(set(summary["skipped_files"]) & set(classifications))
        if not_loaded:
            raise RefreshFailed(f"downloaded files were not ingested: {', '.join(not_loaded)}")
        missing_runs = ({SOURCE_TOTAL} | ({SOURCE_MINISTRY} if downloaded else set())) - set(summary["runs"])
        if missing_runs:
            raise RefreshFailed(f"ingestion produced no run for {', '.join(sorted(missing_runs))}")
        after = _metrics(engine)
        report["records"] = _record_changes(before, after, summary)
        report["classification"] = {
            "ministry_nodes_before": before["ministry_nodes"],
            "ministry_nodes_after": after["ministry_nodes"],
            "links_before": before["classification_links"],
            "links_after": after["classification_links"],
        }
        if not after["master"]:
            raise RefreshFailed("no current standards from the overall export after ingestion")

        # 6. search indexes and the product vocabulary built from them
        with engine.begin() as conn:
            fts.create_fts(conn)
            fts.rebuild_fts(conn)
            fts_counts = {name: conn.exec_driver_sql(f"SELECT count(*) FROM {name}").scalar() for name in fts.FTS_SPECS}
        staged_indexes.mkdir(parents=True, exist_ok=True)
        with engine.connect() as conn:
            vector_counts = build_vector_indexes(conn, staged_indexes, corpora=_index_corpora(rp.index_dir))
            vocabulary = len(Gazetteer.load(conn).product_words)
            searchable = _standard_search_works(conn)
            findings = run_quality_checks(conn)
        report["indexes"] = {"fts": fts_counts, "vectors": vector_counts, "product_vocabulary_terms": vocabulary, "standard_search": searchable}
        report["quality"] = dict(Counter(finding.severity for finding in findings if finding.count))
        (version_dir / "data_quality.json").write_text(json.dumps([asdict(finding) for finding in findings], indent=2, ensure_ascii=False), encoding="utf-8")
        if not searchable:
            raise RefreshFailed("the rebuilt full-text index does not find current standards")
        if active_ready and not vocabulary:
            raise RefreshFailed("the product vocabulary is empty after indexing")
    finally:
        engine.dispose()

    # 7. regression checks
    smoke = compare_datasets(rp.db_path if active_ready else None, rp.index_dir, staged_db, staged_indexes, settings, queries=smoke_queries)
    report["tests"]["smoke"] = {"status": "passed" if smoke.passed else "failed", **asdict(smoke)}
    failing = [] if smoke.passed else ["assistant regression checks"]
    if run_pytest:
        report["tests"]["pytest"] = _run_pytest()
        if report["tests"]["pytest"]["status"] != "passed":
            failing.append("backend test suite")
    if failing:
        raise RefreshFailed(f"{' and '.join(failing)} failed")
    if not activate:
        report["status"] = "staged"
        report["activation"] = {"status": "not_activated", "reason": "dry run: activation was not requested", "staged_database": str(staged_db)}
        return

    # 8. activation
    activation = activate_dataset(staged_db, staged_indexes, rp, version_dir, before_swap=before_swap, after_swap=after_swap)
    report["activation"] = activation
    if activation["status"] != "activated":
        raise RefreshFailed(f"activation {activation['status']}: {activation.get('error')}")
    refresh_log.write_active(
        rp.refresh_dir,
        {
            "version": version_dir.name,
            "activated_at": activation["activated_at"],
            "standards": report["records"]["after"],
            "ministry_nodes": report["classification"]["ministry_nodes_after"],
            "snapshot": activation.get("snapshot"),
        },
    )
    report["status"] = "success"


# --------------------------------------------------------------------------- activation


def _replace_file(source: Path, target: Path) -> None:
    os.replace(source, target)


def _verify_activated(db_path: Path) -> None:
    status = data_status(db_path)
    if not status["ready"]:
        raise RuntimeError(f"the activated database is not usable ({status['reason']})")


def activate_dataset(staged_db: Path, staged_indexes: Path, rp: RefreshPaths, version_dir: Path, *, before_swap=None, after_swap=None) -> dict:
    """Replace the active database and indexes with the staged ones; restore the previous dataset if anything fails."""
    result: dict = {"status": "not_activated", "activated_at": None}
    previous_bundle = None
    previous_indexes = version_dir / "previous-indexes"
    if data_status(rp.db_path)["ready"]:
        previous_bundle = version_dir / "previous-dataset.tar.gz"
        export_bundle(rp.db_path, rp.index_dir, rp.manifest_dir, previous_bundle)
        result["previous_snapshot"] = str(previous_bundle)
    rp.index_dir.mkdir(parents=True, exist_ok=True)
    index_files = [(path, rp.index_dir / path.name) for path in sorted(Path(staged_indexes).glob("*.joblib"))]
    for _source, target in index_files:
        if target.exists():
            previous_indexes.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(target, previous_indexes / target.name)

    incoming_db = rp.db_path.with_name(rp.db_path.name + ".incoming")
    incoming_indexes = [(target.with_name(target.name + ".incoming"), target) for _source, target in index_files]
    rp.db_path.parent.mkdir(parents=True, exist_ok=True)
    _copy_database(staged_db, incoming_db)
    for (source, _target), (incoming, _final) in zip(index_files, incoming_indexes):
        shutil.copyfile(source, incoming)

    swapped = False
    try:
        if before_swap:
            before_swap()
        _checkpoint(rp.db_path)
        _replace_file(incoming_db, rp.db_path)
        swapped = True
        for suffix in ("-wal", "-shm"):
            Path(f"{rp.db_path}{suffix}").unlink(missing_ok=True)
        for incoming, target in incoming_indexes:
            _replace_file(incoming, target)
        _verify_activated(rp.db_path)
    except Exception as exc:  # never leave a half-activated dataset behind
        log.exception("activation failed")
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["status"] = _roll_back(rp, previous_bundle, previous_indexes) if swapped else "failed"
        return result
    finally:
        incoming_db.unlink(missing_ok=True)
        for incoming, _target in incoming_indexes:
            incoming.unlink(missing_ok=True)
        if after_swap:
            after_swap()
    result["status"] = "activated"
    result["activated_at"] = clock.now_utc().isoformat(timespec="seconds")
    snapshot = version_dir / "dataset.tar.gz"
    try:
        export_bundle(rp.db_path, rp.index_dir, rp.manifest_dir, snapshot)
        result["snapshot"] = str(snapshot)
    except (BundleError, OSError) as exc:
        result["snapshot_error"] = str(exc)
    return result


def _roll_back(rp: RefreshPaths, previous_bundle: Path | None, previous_indexes: Path) -> str:
    if previous_bundle is None or not previous_bundle.exists():
        return "failed"
    try:
        for suffix in ("-wal", "-shm"):
            Path(f"{rp.db_path}{suffix}").unlink(missing_ok=True)
        import_bundle(previous_bundle, db_path=rp.db_path, index_dir=rp.index_dir, manifest_dir=rp.manifest_dir, force=True)
        for path in previous_indexes.glob("*.joblib"):
            shutil.copyfile(path, rp.index_dir / path.name)
    except (BundleError, OSError):
        log.exception("rollback of a failed activation failed")
        return "rollback_failed"
    return "rolled_back"


# --------------------------------------------------------------------------- helpers


def _new_version(refresh_dir: Path, started) -> str:
    base = started.strftime("%Y%m%dT%H%M%SZ")
    name, counter = base, 1
    while (refresh_dir / name).exists():
        name, counter = f"{base}-{counter}", counter + 1
    return name


def _acquire_lock(refresh_dir: Path) -> Path | None:
    path = refresh_dir / LOCK_NAME
    if path.exists() and time.time() - path.stat().st_mtime > STALE_LOCK_S:
        path.unlink(missing_ok=True)  # left behind by a process that died mid-refresh
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"pid": os.getpid(), "started_at": clock.now_utc().isoformat(timespec="seconds")}))
    return path


def _release_lock(path: Path | None) -> None:
    if path is not None:
        path.unlink(missing_ok=True)


def _finish(rp: RefreshPaths, report: dict, version_dir: Path | None, keep: int) -> dict:
    report["completed_at"] = clock.now_utc().isoformat(timespec="seconds")
    if version_dir is not None and version_dir.exists():
        (version_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        if report["status"] != "staged":
            shutil.rmtree(version_dir / "staging", ignore_errors=True)
    refresh_log.append(rp.refresh_dir, log_entry(report))
    _prune(rp.refresh_dir, keep)
    log.info("BIS data refresh %s: %s (activation %s)", report["refresh_id"], report["status"], report["activation"].get("status"))
    return report


def _prune(refresh_dir: Path, keep: int) -> None:
    if keep <= 0:
        return
    active = (refresh_log.read_active(refresh_dir) or {}).get("version")
    versions = sorted(path for path in refresh_dir.iterdir() if path.is_dir() and re.match(r"^\d{8}T\d{6}Z", path.name))
    for path in versions[:-keep]:
        if path.name != active:
            shutil.rmtree(path, ignore_errors=True)


def _download_status(exc: Exception) -> str:
    if isinstance(exc, AccessBlocked):
        return "access_blocked"
    if isinstance(exc, PortalChanged):
        return "structure_changed"
    return "download_failed"


def _ministry_failure(ministry: Ministry, status: str, error: str) -> dict:
    return {"ministry_id": ministry.ministry_id, "name": ministry.name, "published_count": ministry.published_count, "status": status, "error": error}


def _carry_groupwise_exports(data_dir: Path, downloads: Path) -> list[str]:
    carried = []
    for path in sorted(Path(data_dir).glob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        try:
            export = read_export(path)
        except Exception:  # not a standards export (for example the HSN master) or unreadable: nothing to carry
            continue
        if classify_export(export) == "untitled_export":
            name = f"groupwise-carried-{path.name}"
            shutil.copyfile(path, downloads / name)
            carried.append(name)
    return carried


def _copy_database(source: Path, target: Path) -> None:
    """Consistent copy of a SQLite database (including pages still in its WAL file)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    origin = sqlite3.connect(f"{Path(source).resolve().as_uri()}?mode=ro", uri=True)
    try:
        destination = sqlite3.connect(target)
        try:
            origin.backup(destination)
        finally:
            destination.close()
    finally:
        origin.close()


def _checkpoint(db_path: Path) -> None:
    if not Path(db_path).exists():
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error:
        pass
    finally:
        conn.close()


def _active_master_count(db_path: Path) -> int:
    if not Path(db_path).exists():
        return 0
    try:
        conn = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)
        try:
            return conn.execute("SELECT count(*) FROM standard WHERE is_current = 1 AND source_id = ?", (SOURCE_TOTAL,)).fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def _metrics(engine) -> dict:
    standard, node, links = schema.standard, schema.classification_node, schema.standard_classification
    with engine.connect() as conn:
        standards = dict(conn.execute(sa.select(standard.c.std_key, standard.c.record_hash).where(standard.c.is_current.is_(True))).all())
        master = conn.execute(
            sa.select(sa.func.count()).select_from(standard).where(standard.c.is_current.is_(True), standard.c.source_id == SOURCE_TOTAL)
        ).scalar()
        nodes = conn.execute(sa.select(sa.func.count()).select_from(node).where(node.c.is_current.is_(True), node.c.dimension == "ministry")).scalar()
        link_count = conn.execute(sa.select(sa.func.count()).select_from(links).where(links.c.is_current.is_(True))).scalar()
    return {"standards": standards, "master": master, "ministry_nodes": nodes, "classification_links": link_count}


def _record_changes(before: dict, after: dict, summary: dict) -> dict:
    old, new = before["standards"], after["standards"]
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    updated = sorted(key for key in set(old) & set(new) if old[key] != new[key])
    return {
        "before": len(old),
        "after": len(new),
        "added": len(added),
        "updated": len(updated),
        "removed": len(removed),
        "duplicates": sum(summary["duplicates_skipped"].values()),
        "rejected": sum(run.get("rejected", 0) for run in summary["runs"].values()),
        "examples": {"added": added[:10], "updated": updated[:10], "removed": removed[:10]},
    }


def _index_corpora(index_dir: Path) -> tuple[str, ...]:
    existing = tuple(name for name in CORPORA if (Path(index_dir) / f"{name}.joblib").exists())
    return tuple(dict.fromkeys((*RUNTIME_CORPORA, *existing)))


def _standard_search_works(conn) -> bool:
    table = schema.standard
    title = conn.execute(sa.select(table.c.title_clean).where(table.c.is_current.is_(True), table.c.title_clean.is_not(None)).limit(1)).scalar()
    words = sorted(re.findall(r"[A-Za-z]{4,}", title or ""), key=len, reverse=True)
    return bool(words) and bool(fts_search.search_standards(conn, words[0], limit=1))


def _run_pytest(timeout_s: float = 3600.0) -> dict:
    tests_dir = paths.PROJECT_ROOT / "backend" / "tests"
    if importlib.util.find_spec("pytest") is None or not tests_dir.is_dir():
        return {"status": "unavailable", "detail": "pytest or backend/tests is not installed in this environment"}
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=tests_dir.parent, capture_output=True, text=True, timeout=timeout_s
        )
    except subprocess.TimeoutExpired:
        return {"status": "failed", "detail": f"timed out after {timeout_s:.0f} s"}
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    return {"status": "passed" if completed.returncode == 0 else "failed", "returncode": completed.returncode, "summary": lines[-1] if lines else ""}
