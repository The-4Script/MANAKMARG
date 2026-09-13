import json

import pytest
import sqlalchemy as sa

from manakmarg.db import schema
from manakmarg.db.engine import get_engine, init_db
from manakmarg.ingest import sources

ALLOWED_AUTHORITY = {"official_primary", "official_secondary", "curated", "derived"}
ALLOWED_ACCESS = {"ok", "partial", "captcha_blocked", "access_denied", "not_used", "unavailable"}
ALLOWED_TYPES = {"excel_export", "html_table", "html_page", "pdf_document", "web_report", "web_api", "curated_file"}
REQUIRED_TEXT_FIELDS = (
    "source_id",
    "name",
    "publisher",
    "domain",
    "url",
    "source_type",
    "purpose",
    "ingestion_method",
    "authority",
    "access_status",
    "document_type",
    "copyright_notes",
)


def test_registry_entries_are_complete():
    assert len(sources.REGISTRY) >= 25
    for source_id, definition in sources.REGISTRY.items():
        assert definition.source_id == source_id
        for field in REQUIRED_TEXT_FIELDS:
            assert getattr(definition, field), f"{source_id}.{field} is empty"
        assert definition.authority in ALLOWED_AUTHORITY, source_id
        assert definition.access_status in ALLOWED_ACCESS, source_id
        assert definition.source_type in ALLOWED_TYPES, source_id


def test_registry_records_known_access_constraints():
    assert sources.REGISTRY["manak_jewellers_report"].access_status == "captcha_blocked"
    assert sources.REGISTRY["bis_standards_portal_api"].access_status == "not_used"
    assert sources.REGISTRY["bis_std_exports_ministry"].access_status == "partial"


def test_every_official_web_source_points_to_an_https_url():
    for definition in sources.REGISTRY.values():
        if definition.authority.startswith("official") and definition.source_type != "excel_export":
            assert definition.url.startswith(("https://", "http://")), definition.source_id


@pytest.fixture
def engine(tmp_path):
    eng = get_engine(tmp_path / "sources.sqlite3")
    init_db(eng)
    yield eng
    eng.dispose()


def test_sync_registry_is_idempotent(engine):
    with engine.begin() as conn:
        sources.sync_registry(conn)
        sources.sync_registry(conn)
    with engine.connect() as conn:
        count = conn.execute(sa.select(sa.func.count()).select_from(schema.source)).scalar()
    assert count == len(sources.REGISTRY)


def test_export_manifest_writes_machine_readable_registry(tmp_path):
    path = tmp_path / "sources.json"
    sources.export_manifest(path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["source_count"] == len(sources.REGISTRY)
    entry = next(item for item in manifest["sources"] if item["source_id"] == "bis_scheme_i_page")
    for key in (
        "name",
        "domain",
        "url",
        "type",
        "purpose",
        "ingestion_method",
        "authority",
        "access_status",
        "document_type",
        "copyright_access_notes",
        "last_checked",
    ):
        assert key in entry
