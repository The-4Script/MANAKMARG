"""SQLite FTS5 full-text indexes.

Indexes are standalone FTS5 tables rebuilt from the relational tables after ingestion
(``rebuild_fts``); the FTS rowid equals the primary key of the indexed row.
"""

from dataclasses import dataclass

from sqlalchemy.engine import Connection

TOKENIZER = "unicode61 remove_diacritics 2"


@dataclass(frozen=True)
class FtsSpec:
    name: str
    columns: tuple[str, ...]
    populate_sql: str


FTS_SPECS: dict[str, FtsSpec] = {
    spec.name: spec
    for spec in (
        FtsSpec(
            "standard_fts",
            ("std_key", "designation", "aliases", "title", "standard_type"),
            """
            SELECT s.standard_id,
                   s.std_key,
                   s.designation_raw,
                   COALESCE((SELECT group_concat(a.raw_text, ' | ')
                               FROM standard_alias a
                              WHERE a.standard_id = s.standard_id), ''),
                   COALESCE(s.title_clean, s.title),
                   COALESCE(s.standard_type, '')
              FROM standard s
             WHERE s.is_current = 1
            """,
        ),
        FtsSpec(
            "coverage_fts",
            ("product_name", "category", "section_label", "product_category", "standard_refs", "requirements"),
            """
            SELECT c.coverage_id,
                   c.product_name,
                   COALESCE(c.category, ''),
                   COALESCE(c.section_label, ''),
                   COALESCE(c.product_category, ''),
                   COALESCE(c.standard_ref_raw, ''),
                   COALESCE(c.essential_requirement, '') || ' ' || COALESCE(c.specific_requirement, '')
              FROM scheme_coverage c
             WHERE c.is_current = 1
            """,
        ),
        FtsSpec(
            "guideline_fts",
            ("title", "is_ref"),
            """
            SELECT g.guideline_id, g.title, g.is_ref_raw
              FROM product_guideline g
             WHERE g.is_current = 1
            """,
        ),
        FtsSpec(
            "faq_fts",
            ("question", "answer", "category"),
            """
            SELECT f.faq_id, f.question, f.answer, f.category
              FROM faq f
             WHERE f.is_current = 1
            """,
        ),
        FtsSpec(
            "chunk_fts",
            ("heading", "text"),
            """
            SELECT c.chunk_id, COALESCE(c.heading, ''), c.text
              FROM document_chunk c
            """,
        ),
        FtsSpec(
            "lab_fts",
            ("name", "address", "city", "district", "state"),
            """
            SELECT l.lab_id, l.name, COALESCE(l.address_raw, ''), COALESCE(l.city, ''),
                   COALESCE(l.district, ''), COALESCE(l.state, '')
              FROM laboratory l
             WHERE l.is_current = 1
            """,
        ),
        FtsSpec(
            "hsn_fts",
            ("code", "description"),
            """
            SELECT h.hsn_id, h.code_digits, h.description
              FROM hsn_code h
             WHERE h.is_current = 1
            """,
        ),
        FtsSpec(
            "ahc_fts",
            ("name", "address", "district", "state"),
            """
            SELECT a.ahc_id, a.name, COALESCE(a.address_raw, ''), COALESCE(a.district, ''),
                   COALESCE(a.state, '')
              FROM ahc a
             WHERE a.is_current = 1
            """,
        ),
    )
}


def create_fts(conn: Connection) -> None:
    for spec in FTS_SPECS.values():
        columns = ", ".join(spec.columns)
        conn.exec_driver_sql(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {spec.name} "
            f"USING fts5({columns}, tokenize='{TOKENIZER}', prefix='2 3')"
        )


def rebuild_fts(conn: Connection, name: str | None = None) -> None:
    specs = [FTS_SPECS[name]] if name else list(FTS_SPECS.values())
    for spec in specs:
        conn.exec_driver_sql(f"DELETE FROM {spec.name}")
        columns = ", ".join(("rowid", *spec.columns))
        conn.exec_driver_sql(f"INSERT INTO {spec.name} ({columns}) {spec.populate_sql}")
