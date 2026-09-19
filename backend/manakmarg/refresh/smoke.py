"""Regression checks for a staged dataset, run before it may replace the active one.

The real assistant answers a fixed set of questions on both databases. The route (which official records are
consulted), the answer language and the presence of an answer must not change, and a compulsory-certification status
must not disappear. The standards refresh never writes regulatory, laboratory, hallmarking or HSN tables, so their row
counts must be identical. Questions are answered without any external model.
"""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import sqlalchemy as sa

from manakmarg.core import clock
from manakmarg.core.config import Settings
from manakmarg.db import schema
from manakmarg.db.engine import get_engine
from manakmarg.reasoning.assistant import answer
from manakmarg.reasoning.intents import Gazetteer
from manakmarg.search.vectors import RUNTIME_CORPORA, load_vector_indexes

OUT_OF_SCOPE_PROBE = "capital of France"
DEFAULT_QUERIES: tuple[tuple[str, str], ...] = (
    ("What is IS 2062?", "en"),
    ("IS-2062", "en"),
    ("What is IS 13688?", "en"),
    ("I need the BIS standard for copper wire", "en"),
    ("Packaged Pasteurized Milk", "en"),
    ("Is BIS certification mandatory for stainless steel cookware?", "en"),
    ("Find IS 2062 labs in Kolkata", "en"),
    ("Is hallmarking mandatory in Jaipur?", "en"),
    ("How do I obtain a BIS licence?", "en"),
    ("What is Scheme I?", "en"),
    ("What is the HSN code for copper wire?", "en"),
    ("जयपुर में हॉलमार्किंग अनिवार्य है क्या?", "auto"),
    ("Kolkata mein IS 2062 ke testing ke liye lab bataiye", "auto"),
    (OUT_OF_SCOPE_PROBE, "en"),
)
# Tables the standards refresh does not own: listings, orders, Product Manuals, labs, hallmarking, FAQs, HSN.
UNOWNED_TABLES = (
    "scheme_coverage",
    "coverage_standard",
    "coverage_order",
    "regulatory_order",
    "product_guideline",
    "guideline_section",
    "laboratory",
    "lab_scope",
    "ahc",
    "hallmarking_district",
    "faq",
    "hsn_code",
)


@dataclass
class SmokeResult:
    passed: bool
    checked: int
    failures: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    answers: dict = field(default_factory=dict)
    table_counts: dict = field(default_factory=dict)


def _answers(db_path: Path, index_dir: Path, settings: Settings, queries, today: date) -> tuple[dict, dict]:
    engine = get_engine(db_path)
    try:
        vectors = load_vector_indexes(index_dir, RUNTIME_CORPORA)
        with engine.connect() as conn:
            gazetteer = Gazetteer.load(conn)
            summaries = {}
            for query, lang in queries:
                response = answer(conn, query, lang=lang, fallback_lang="en", today=today, vectors=vectors, gazetteer=gazetteer, settings=settings)
                summaries[query] = {
                    "route": response.route.category if response.route else None,
                    "status": response.status_label,
                    "lang": response.lang,
                    "has_sections": bool(response.sections),
                }
            counts = {name: conn.execute(sa.select(sa.func.count()).select_from(schema.metadata.tables[name])).scalar() for name in UNOWNED_TABLES}
    finally:
        engine.dispose()
    return summaries, counts


def compare_datasets(
    active_db: Path | None,
    active_index_dir: Path,
    staged_db: Path,
    staged_index_dir: Path,
    settings: Settings,
    *,
    queries=DEFAULT_QUERIES,
    today: date | None = None,
) -> SmokeResult:
    today = today or clock.today()
    local_only = settings.model_copy(update={"groq_api_key": None, "anthropic_api_key": None})
    staged, staged_counts = _answers(Path(staged_db), Path(staged_index_dir), local_only, queries, today)
    active, active_counts = ({}, {}) if active_db is None else _answers(Path(active_db), Path(active_index_dir), local_only, queries, today)

    failures: list[dict] = []
    warnings: list[dict] = []
    probe = staged.get(OUT_OF_SCOPE_PROBE)
    if probe is not None and (probe["route"] != "out_of_scope" or probe["has_sections"]):
        failures.append({"query": OUT_OF_SCOPE_PROBE, "field": "route", "expected": "out_of_scope without records", "staged": probe})
    for query, _lang in queries:
        before, after = active.get(query), staged[query]
        if before is None:
            continue
        for key in ("route", "lang"):
            if before[key] != after[key]:
                failures.append({"query": query, "field": key, "active": before[key], "staged": after[key]})
        if before["has_sections"] and not after["has_sections"]:
            failures.append({"query": query, "field": "answer", "active": "has an answer", "staged": "no answer sections"})
        if before["status"] != after["status"]:
            entry = {"query": query, "field": "status", "active": before["status"], "staged": after["status"]}
            (failures if before["status"] and not after["status"] else warnings).append(entry)
    for table, count in active_counts.items():
        if staged_counts.get(table) != count:
            failures.append({"table": table, "active": count, "staged": staged_counts.get(table)})
    return SmokeResult(
        passed=not failures,
        checked=len(queries),
        failures=failures,
        warnings=warnings,
        answers={query: {"active": active.get(query), "staged": staged[query]} for query, _lang in queries},
        table_counts={"active": active_counts, "staged": staged_counts},
    )
