"""Test helper: insert standard rows exactly as the Excel ingestion would key them."""

from manakmarg.db import schema
from manakmarg.normalize.is_number import parse_designation


def add_standard(conn, raw, title="Title", *, current=True, source_id="bis_std_export_total"):
    designation = parse_designation(raw)
    result = conn.execute(
        schema.standard.insert().values(
            std_key=designation.std_key,
            family_key=designation.family_key,
            match_key=designation.match_key,
            number_key=designation.number_key,
            designation_raw=raw,
            prefix=designation.prefix,
            number=designation.number,
            part=designation.part,
            section=designation.section,
            subsection=designation.subsection,
            year=designation.year,
            suffix=designation.suffix,
            title=title,
            title_clean=title,
            listing_status="published_export",
            in_master_export=True,
            source_id=source_id,
            source_locator="test",
            retrieved_at="2026-09-12T20:17:00+05:30",
            is_current=current,
        )
    )
    return result.inserted_primary_key[0]


def seed_standards(conn, raws):
    return {raw: add_standard(conn, raw) for raw in raws}
