"""Deployment helpers: data readiness, runtime data bundle round trip, health status and the serve guard."""

import io
import json
import tarfile

import pytest
from fastapi.testclient import TestClient

from manakmarg.__main__ import main
from manakmarg.api import deps
from manakmarg.api.app import create_app
from manakmarg.core.config import Settings, get_settings
from manakmarg.core.data_bundle import BundleError, data_status, export_bundle, import_bundle
from manakmarg.db.engine import get_engine, init_db
from manakmarg.search.vectors import VectorIndex, load_vector_indexes
from tests.fixture_db import build_fixture_db


@pytest.fixture(scope="module")
def ready_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("bundle") / "source.sqlite3"
    engine = build_fixture_db(path)
    engine.dispose()
    return path


def test_data_status(tmp_path, ready_db):
    assert data_status(tmp_path / "missing.sqlite3")["reason"] == "database_missing"
    empty = tmp_path / "empty.sqlite3"
    engine = get_engine(empty)
    init_db(engine)
    engine.dispose()
    assert data_status(empty)["reason"] == "database_empty"
    status = data_status(ready_db)
    assert status["ready"] and status["listings"] > 0 and status["standards"] > 0


def test_bundle_round_trip_restores_database_index_and_manifests(tmp_path, ready_db):
    index_dir, manifest_dir = tmp_path / "indexes", tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "sources.json").write_text('{"sources": []}', encoding="utf-8")
    VectorIndex.build([1, 2], ["ordinary portland cement", "steel utensils"]).save(index_dir, "coverage")
    VectorIndex.build([1], ["not needed at runtime"]).save(index_dir, "standards")
    bundle = export_bundle(ready_db, index_dir, manifest_dir, tmp_path / "out" / "bundle.tar.gz")
    assert set(bundle["files"]) == {"processed/manakmarg.sqlite3", "indexes/coverage.joblib", "manifests/sources.json"}

    target = tmp_path / "deploy"
    restored = import_bundle(bundle["output"], db_path=target / "processed" / "db.sqlite3", index_dir=target / "indexes", manifest_dir=target / "manifests")
    assert restored["imported"] and data_status(target / "processed" / "db.sqlite3")["ready"]
    assert (target / "indexes" / "coverage.joblib").exists() and not (target / "indexes" / "standards.joblib").exists()
    again = import_bundle(bundle["output"], db_path=target / "processed" / "db.sqlite3", index_dir=target / "indexes", manifest_dir=target / "manifests")
    assert again["imported"] is False


def test_unsafe_or_corrupt_bundles_are_rejected(tmp_path):
    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as tar:
        payload = b"x"
        member = tarfile.TarInfo("../outside.txt")
        member.size = len(payload)
        tar.addfile(member, io.BytesIO(payload))
    with pytest.raises(BundleError):
        import_bundle(evil, db_path=tmp_path / "db.sqlite3", index_dir=tmp_path / "i", manifest_dir=tmp_path / "m")
    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(tampered, "w:gz") as tar:
        for name, data in (("processed/manakmarg.sqlite3", b"not a database"), ("BUNDLE.json", json.dumps({"files": {"processed/manakmarg.sqlite3": "0" * 64}}).encode())):
            member = tarfile.TarInfo(name)
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
    with pytest.raises(BundleError):
        import_bundle(tampered, db_path=tmp_path / "db.sqlite3", index_dir=tmp_path / "i", manifest_dir=tmp_path / "m")
    with pytest.raises(BundleError):
        import_bundle(tmp_path / "nope.tar.gz", db_path=tmp_path / "db.sqlite3", index_dir=tmp_path / "i", manifest_dir=tmp_path / "m")


def test_health_reports_missing_data_with_503(tmp_path):
    engine = get_engine(tmp_path / "empty.sqlite3")
    init_db(engine)
    settings = Settings(db_path=tmp_path / "empty.sqlite3")
    app = create_app(settings, state=deps.AppState(settings, engine=engine, index_dir=tmp_path / "indexes"), frontend_dir=tmp_path / "nofe")
    with TestClient(app) as client:
        response = client.get("/api/health")
    engine.dispose()
    assert response.status_code == 503 and response.json()["data_ready"] is False


def test_runtime_loads_only_the_listing_index(tmp_path):
    VectorIndex.build([1, 2], ["cement", "steel"]).save(tmp_path, "coverage")
    VectorIndex.build([1, 2], ["a", "b"]).save(tmp_path, "standards")
    assert set(load_vector_indexes(tmp_path, ("coverage",))) == {"coverage"}
    assert set(load_vector_indexes(tmp_path)) == {"coverage", "standards"}


def test_serve_refuses_to_start_without_data(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MANAKMARG_DB_PATH", str(tmp_path / "missing.sqlite3"))
    get_settings.cache_clear()
    try:
        assert main(["serve", "--port", "65000"]) == 2
    finally:
        get_settings.cache_clear()
    assert "import-data" in capsys.readouterr().err


def test_host_and_port_come_from_platform_variables(monkeypatch):
    monkeypatch.setenv("PORT", "7860")
    monkeypatch.setenv("HOST", "0.0.0.0")
    settings = Settings()
    assert (settings.port, settings.host) == (7860, "0.0.0.0")
