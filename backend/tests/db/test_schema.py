import pytest
import sqlalchemy as sa

from manakmarg.db import fts, schema
from manakmarg.db.engine import get_engine, init_db

EXPECTED_TABLES = {
    "source",
    "ingestion_run",
    "raw_artifact",
    "document",
    "document_chunk",
    "standard",
    "standard_alias",
    "classification_node",
    "standard_classification",
    "standard_relation",
    "certification_scheme",
    "regulatory_order",
    "scheme_coverage",
    "coverage_standard",
    "coverage_order",
    "product_term",
    "product_guideline",
    "guideline_section",
    "process_step",
    "scheme_document",
    "laboratory",
    "lab_scope",
    "lab_scope_item",
    "ahc",
    "ahc_status_event",
    "hallmarking_district",
    "district_alias",
    "jeweller",
    "faq",
}

PROVENANCE_TABLES = {
    "document",
    "standard",
    "standard_alias",
    "classification_node",
    "standard_classification",
    "standard_relation",
    "certification_scheme",
    "regulatory_order",
    "scheme_coverage",
    "product_guideline",
    "process_step",
    "scheme_document",
    "laboratory",
    "lab_scope",
    "ahc",
    "ahc_status_event",
    "hallmarking_district",
    "jeweller",
    "faq",
}

PROVENANCE_COLUMNS = {
    "source_id",
    "run_id",
    "source_locator",
    "retrieved_at",
    "record_hash",
    "first_seen_run",
    "last_seen_run",
    "is_current",
}


@pytest.fixture
def engine(tmp_path):
    eng = get_engine(tmp_path / "test.sqlite3")
    init_db(eng)
    yield eng
    eng.dispose()


def _insert_test_source(conn):
    conn.execute(schema.source.insert().values(source_id="test_src", name="Test source"))


def test_init_db_creates_every_table(engine):
    assert EXPECTED_TABLES <= set(sa.inspect(engine).get_table_names())


def test_init_db_is_idempotent(engine):
    init_db(engine)


def test_domain_tables_carry_provenance_columns():
    for name in PROVENANCE_TABLES:
        assert PROVENANCE_COLUMNS <= set(schema.metadata.tables[name].c.keys()), name


def test_foreign_keys_are_enforced(engine):
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                schema.standard.insert().values(
                    std_key="IS 1:2000",
                    family_key="IS 1",
                    match_key="IS 1",
                    number_key="1",
                    designation_raw="IS 1:2000",
                    prefix="IS",
                    number="1",
                    title="Example",
                    listing_status="published_export",
                    source_id="no-such-source",
                )
            )


def test_fts_indexes_are_declared():
    assert set(fts.FTS_SPECS) == {
        "standard_fts",
        "coverage_fts",
        "guideline_fts",
        "faq_fts",
        "chunk_fts",
        "lab_fts",
        "ahc_fts",
    }


def test_standard_fts_rebuild_supports_match(engine):
    with engine.begin() as conn:
        _insert_test_source(conn)
        conn.execute(
            schema.standard.insert().values(
                std_key="IS 14756:2024",
                family_key="IS 14756",
                match_key="IS 14756",
                number_key="14756",
                designation_raw="IS 14756:2024",
                prefix="IS",
                number="14756",
                year=2024,
                title="Stainless Steel Utensils — Specification",
                title_clean="Stainless Steel Utensils — Specification",
                listing_status="published_export",
                source_id="test_src",
            )
        )
        fts.rebuild_fts(conn, "standard_fts")
        hits = conn.exec_driver_sql(
            "SELECT rowid FROM standard_fts WHERE standard_fts MATCH 'utensils'"
        ).fetchall()
    assert len(hits) == 1
