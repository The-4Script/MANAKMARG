"""HSN master ingestion: found by header, codes kept as text, descriptions verbatim, bad rows rejected, reload safe."""

import sqlalchemy as sa

from manakmarg.db import schema
from manakmarg.db.engine import get_engine, init_db
from manakmarg.ingest import sources
from manakmarg.ingest.hsn import find_hsn_workbook, ingest_hsn, read_hsn_workbook
from tests.hsn_workbook import HSN_ROWS, write_decoy_workbook, write_hsn_workbook


def _engine(tmp_path):
    engine = get_engine(tmp_path / "hsn.sqlite3")
    init_db(engine)
    with engine.begin() as conn:
        sources.sync_registry(conn)
    return engine


def test_workbook_is_found_by_its_header_not_its_name(tmp_path):
    data = tmp_path / "data"
    write_decoy_workbook(data)
    path = write_hsn_workbook(data, name="zz_anything.xlsx")
    assert find_hsn_workbook(data) == (path, "HSN_MSTR")
    assert find_hsn_workbook(tmp_path / "empty") is None


def test_parsing_keeps_codes_and_descriptions_exactly(tmp_path):
    path = write_hsn_workbook(tmp_path)
    parsed = read_hsn_workbook(path, "HSN_MSTR")
    by_code = {record.code: record for record in parsed.records}
    assert len(parsed.records) == len(HSN_ROWS)
    assert by_code["0101"].code_digits == "0101"  # leading zero kept
    assert by_code["2307 00"].code_digits == "230700"
    assert by_code["73053121"].description == "Non-galvanised, of iron : Clad, plated or coated"
    assert by_code["85"].description == "  ELECTRICAL MACHINERY  AND EQUIPMENT  "  # verbatim, not cleaned
    assert parsed.duplicates == 1
    assert sorted(reason for _, reason in parsed.rejected) == ["code is not 2-8 digits", "empty description"]


def test_ingestion_is_repeatable_and_retires_removed_codes(tmp_path):
    engine = _engine(tmp_path)
    data = tmp_path / "data"
    write_hsn_workbook(data)
    first = ingest_hsn(engine, data)
    second = ingest_hsn(engine, data)
    assert first["records"] == len(HSN_ROWS) and first["inserted"] == len(HSN_ROWS)
    assert second["inserted"] == 0 and second["updated"] == 0 and second["unchanged"] == len(HSN_ROWS)
    write_hsn_workbook(data, rows=HSN_ROWS[:-1])
    third = ingest_hsn(engine, data)
    assert third["retired"] == 1
    with engine.connect() as conn:
        row = conn.execute(sa.select(schema.hsn_code).where(schema.hsn_code.c.code == "73053121")).mappings().one()
        retired = conn.execute(sa.select(schema.hsn_code.c.is_current).where(schema.hsn_code.c.code == "85")).scalar()
    engine.dispose()
    assert row["source_id"] == "hsn_master_workbook" and row["source_locator"].endswith("!HSN_MSTR!R5")
    assert row["code_length"] == 8 and retired is False


def test_missing_workbook_is_reported_not_raised(tmp_path):
    engine = _engine(tmp_path)
    assert ingest_hsn(engine, tmp_path / "nothing")["status"] == "not_found"
    engine.dispose()


def test_source_registry_claims_no_publisher_or_url():
    definition = sources.REGISTRY["hsn_master_workbook"]
    assert definition.url == "" and "Not stated" in definition.publisher
    assert "not a GST, customs or BIS determination" in definition.copyright_notes
