"""Laboratories (LIMS scope, directories) and hallmarking (district coverage, AHCs, jewellers)."""

from datetime import date

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from sqlalchemy.engine import Connection

from manakmarg.db import schema
from manakmarg.normalize.geo import normalize_state
from manakmarg.reasoning.hallmarking import check_district, find_ahcs, jeweller_guidance
from manakmarg.reasoning.labs import find_labs
from manakmarg.search import fts_search

from ..deps import get_conn, get_today
from ..serialize import plain, with_evidence

router = APIRouter()


def _short():
    # A fresh Query per parameter: FastAPI must not share one FieldInfo between parameters.
    return Query(None, max_length=80)


@router.get("/labs/for-standard", tags=["labs"])
def labs_for_standard(
    ref: str = Query(..., min_length=1, max_length=120),
    state: str | None = _short(),
    district: str | None = _short(),
    city: str | None = _short(),
    include_inactive: bool = True,
    conn: Connection = Depends(get_conn),
    today: date = Depends(get_today),
) -> dict:
    return with_evidence(find_labs(conn, ref, state=state, district=district, city=city, include_inactive=include_inactive, today=today))


@router.get("/labs/indexed-standards", tags=["labs"])
def indexed_standards(conn: Connection = Depends(get_conn)) -> dict:
    scope = schema.lab_scope
    rows = conn.execute(
        sa.select(scope.c.query_doc_no, sa.func.count(), sa.func.count(sa.distinct(scope.c.lab_id)))
        .where(scope.c.is_current.is_(True))
        .group_by(scope.c.query_doc_no)
        .order_by(sa.func.count().desc())
    ).all()
    return {"items": [{"doc_no": doc_no, "rows": rows_count, "laboratories": labs} for doc_no, rows_count, labs in rows]}


@router.get("/labs", tags=["labs"])
def labs_directory(
    q: str | None = Query(None, max_length=120),
    state: str | None = _short(),
    category: str | None = Query(None, max_length=30),
    limit: int = Query(50, ge=1, le=200),
    conn: Connection = Depends(get_conn),
) -> dict:
    table = schema.laboratory
    query = sa.select(table).where(table.c.is_current.is_(True))
    if state:
        query = query.where(table.c.state == (normalize_state(state) or state))
    if category:
        query = query.where(table.c.lab_category == category)
    if q:
        ids = [hit.id for hit in fts_search.search_labs(conn, q, limit=500)]
        query = query.where(table.c.lab_id.in_(ids or [-1]))
    rows = conn.execute(query.order_by(table.c.name).limit(limit)).mappings().all()
    keys = ("lab_id", "osl_code", "name", "lab_category", "address_raw", "city", "district", "state", "pincode", "org_phone", "org_email", "lims_validity_date", "source_locator", "retrieved_at")
    return {"items": plain([{key: row[key] for key in keys} for row in rows])}


@router.get("/hallmarking/district-check", tags=["hallmarking"])
def district_check(district: str = Query(..., min_length=2, max_length=80), state: str | None = _short(), conn: Connection = Depends(get_conn)) -> dict:
    return with_evidence(check_district(conn, district, state))


@router.get("/hallmarking/districts", tags=["hallmarking"])
def districts(state: str | None = _short(), conn: Connection = Depends(get_conn)) -> dict:
    table = schema.hallmarking_district
    query = sa.select(table).where(table.c.is_current.is_(True))
    if state:
        query = query.where(table.c.state == (normalize_state(state) or state))
    rows = conn.execute(query.order_by(table.c.state, table.c.district)).mappings().all()
    keys = ("district_id", "sr_no", "state", "district", "phase_no", "phase_order_date", "phase_order_date_raw", "gazette_validated", "gazette_note", "source_id")
    states: dict[str, int] = {}
    for row in rows:
        states[row["state"]] = states.get(row["state"], 0) + 1
    return {"items": plain([{key: row[key] for key in keys} for row in rows]), "states": states}


@router.get("/hallmarking/ahc", tags=["hallmarking"])
def ahcs(
    state: str | None = _short(),
    district: str | None = _short(),
    metal: str | None = Query(None, pattern="^(gold|silver)$"),
    include_inactive: bool = False,
    limit: int = Query(100, ge=1, le=500),
    conn: Connection = Depends(get_conn),
    today: date = Depends(get_today),
) -> dict:
    result = find_ahcs(conn, state=state, district=district, metal=metal, include_inactive=include_inactive, today=today)
    total_operative = len(result.operative)
    result.operative = result.operative[:limit]
    result.inactive = result.inactive[:limit]
    return with_evidence(result, total_operative=total_operative)


@router.get("/hallmarking/jewellers", tags=["hallmarking"])
def jewellers() -> dict:
    return jeweller_guidance()
