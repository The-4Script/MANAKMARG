"""Product search, standards, schemes, listings, upcoming QCOs, applicability, journeys and FAQs."""

from datetime import date

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.engine import Connection

from manakmarg.db import schema
from manakmarg.ingest.sources import REGISTRY
from manakmarg.normalize.is_number import parse_designation
from manakmarg.reasoning.applicability import assess, listing_effect, load_listings
from manakmarg.reasoning.evidence import EvidenceBuilder
from manakmarg.reasoning.intents import understand
from manakmarg.reasoning.journey import build_journey
from manakmarg.search import fts_search
from manakmarg.search.hybrid import find_product_matches
from manakmarg.search.resolvers import StandardResolver

from ..deps import get_conn, get_state, get_today
from ..serialize import plain, with_evidence

router = APIRouter(tags=["compliance"])


def _text():
    # A fresh Query per parameter: FastAPI must not share one FieldInfo between parameters.
    return Query(None, max_length=300)


@router.get("/search")
def search(q: str = Query(..., min_length=1, max_length=300), conn: Connection = Depends(get_conn)) -> dict:
    state = get_state()
    matches = find_product_matches(conn, q, limit=10, vectors=state.vectors)
    return {
        "understanding": plain(understand(q, gazetteer=state.gazetteer(conn))),
        "coverage": plain(matches.coverage),
        "standards": plain(matches.standards),
    }


# --------------------------------------------------------------------------- standards


def _standard_row(row) -> dict:
    return {
        "standard_id": row["standard_id"],
        "std_key": row["std_key"],
        "title": row["title_clean"] or row["title"],
        "standard_type": row["standard_type"],
        "degree_of_equivalence": row["degree_of_equivalence"],
        "publication_date": row["publication_date"],
        "listing_status": row["listing_status"],
    }


@router.get("/standards")
def standards(q: str | None = _text(), limit: int = Query(25, ge=1, le=100), conn: Connection = Depends(get_conn)) -> dict:
    table = schema.standard
    if not q:
        rows = conn.execute(
            sa.select(table).where(table.c.is_current.is_(True)).order_by(table.c.publication_date.desc().nulls_last()).limit(limit)
        ).mappings()
        return {"items": plain([_standard_row(row) for row in rows]), "matched_identifiers": []}
    resolutions = StandardResolver(conn).resolve_text(q, assume_is_prefix=True)
    ordered_ids = [standard_id for resolution in resolutions for standard_id in resolution.standard_ids]
    ordered_ids += [hit.id for hit in fts_search.search_standards(conn, q, limit=limit)]
    ordered_ids = list(dict.fromkeys(ordered_ids))[:limit]
    rows = {row["standard_id"]: row for row in conn.execute(sa.select(table).where(table.c.standard_id.in_(ordered_ids or [-1]))).mappings()}
    return {
        "items": plain([_standard_row(rows[standard_id]) for standard_id in ordered_ids if standard_id in rows]),
        "matched_identifiers": [{"ref_raw": item.ref_raw, "kind": item.kind, "note": item.note} for item in resolutions],
    }


@router.get("/standards/detail")
def standard_detail(key: str = Query(..., max_length=200), conn: Connection = Depends(get_conn), today: date = Depends(get_today)) -> dict:
    table = schema.standard
    row = conn.execute(sa.select(table).where(table.c.std_key == key)).mappings().first()
    if row is None:
        designation = parse_designation(key)
        if designation is not None:
            row = conn.execute(
                sa.select(table).where(table.c.family_key == designation.family_key, table.c.is_current.is_(True)).order_by(table.c.year.desc())
            ).mappings().first()
    if row is None:
        raise HTTPException(404, f"{key} is not in the indexed published-standards list.")
    evidence = EvidenceBuilder(conn)
    evidence_id = evidence.add_record("standard", row, record_id=row["std_key"], title=f"{row['std_key']} — {row['title_clean'] or row['title']}", snippet=row["title"])
    versions = conn.execute(
        sa.select(table.c.std_key, table.c.year, table.c.publication_date, table.c.title_clean, table.c.listing_status, table.c.is_current)
        .where(table.c.family_key == row["family_key"])
        .order_by(table.c.year.desc())
    ).mappings().all()
    node, links = schema.classification_node, schema.standard_classification
    classification = conn.execute(
        sa.select(node.c.name, node.c.dimension, node.c.export_label)
        .select_from(links.join(node, node.c.node_id == links.c.node_id))
        .where(links.c.standard_id == row["standard_id"], links.c.is_current.is_(True))
    ).mappings().all()
    aliases = conn.execute(
        sa.select(schema.standard_alias.c.raw_text, schema.standard_alias.c.context, schema.standard_alias.c.resolution).where(
            schema.standard_alias.c.standard_id == row["standard_id"]
        )
    ).mappings().all()
    assessment = assess(conn, std_key=row["family_key"], today=today, evidence=evidence)
    guidelines = conn.execute(
        sa.select(schema.product_guideline).where(schema.product_guideline.c.family_key == row["family_key"], schema.product_guideline.c.is_current.is_(True))
    ).mappings().all()
    scope = schema.lab_scope
    lab_rows = conn.execute(
        sa.select(scope.c.family_key, sa.func.count(), sa.func.count(sa.distinct(scope.c.lab_id)))
        .where(scope.c.is_current.is_(True), scope.c.family_key == row["family_key"])
        .group_by(scope.c.family_key)
    ).all()
    return with_evidence(
        {
            "standard": {**_standard_row(row), "family_key": row["family_key"], "revision_label": row["revision_label"], "amendment_label": row["amendment_label"], "designation_raw": row["designation_raw"], "evidence_id": evidence_id},
            "versions": versions,
            "classification": classification,
            "aliases": aliases,
            "listings": assessment.listings,
            "compulsory": assessment.compulsory,
            "guidelines": [
                {key: guideline[key] for key in ("guideline_id", "title", "is_ref_raw", "url", "doc_kind", "size_text", "parse_status")} for guideline in guidelines
            ],
            "lab_scope": {"rows": lab_rows[0][1], "laboratories": lab_rows[0][2]} if lab_rows else {"rows": 0, "laboratories": 0},
            "portal_url": REGISTRY["bis_std_export_total"].url,
        },
        evidence,
    )


# --------------------------------------------------------------------------- schemes, listings, orders


@router.get("/schemes")
def schemes(conn: Connection = Depends(get_conn)) -> dict:
    coverage, scheme = schema.scheme_coverage, schema.certification_scheme
    counts: dict[str, dict[str, int]] = {}
    for scheme_id, status, count in conn.execute(
        sa.select(coverage.c.scheme_id, coverage.c.listing_status, sa.func.count())
        .where(coverage.c.is_current.is_(True))
        .group_by(coverage.c.scheme_id, coverage.c.listing_status)
    ):
        counts.setdefault(scheme_id or "UPCOMING_QCOS", {})[status] = count
    items = [
        {**{key: row[key] for key in ("scheme_id", "name", "short_name", "official_description", "conformity_mark", "official_url")}, "counts": counts.get(row["scheme_id"], {})}
        for row in conn.execute(sa.select(scheme).order_by(scheme.c.scheme_id)).mappings()
    ]
    return {"items": items, "upcoming_counts": counts.get("UPCOMING_QCOS", {})}


@router.get("/coverage")
def coverage_list(
    scheme_id: str | None = Query(None, max_length=20),
    status: str | None = Query(None, max_length=30),
    q: str | None = _text(),
    include_items: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn: Connection = Depends(get_conn),
    today: date = Depends(get_today),
) -> dict:
    table = schema.scheme_coverage
    query = sa.select(table).where(table.c.is_current.is_(True))
    if scheme_id == "UPCOMING":
        query = query.where(table.c.page_kind == "upcoming_qco")
    elif scheme_id:
        query = query.where(table.c.scheme_id == scheme_id)
    if status:
        query = query.where(table.c.listing_status == status)
    if not include_items:
        query = query.where(table.c.parent_coverage_id.is_(None))
    if q:
        ids = [hit.id for hit in fts_search.search_coverage(conn, q, limit=500)]
        query = query.where(table.c.coverage_id.in_(ids or [-1]))
    total = conn.execute(sa.select(sa.func.count()).select_from(query.subquery())).scalar()
    rows = conn.execute(query.order_by(table.c.scheme_id, table.c.coverage_id).limit(limit).offset(offset)).mappings().all()
    items = []
    for row in rows:
        effect, days = listing_effect(row["listing_status"], row["enforcement_date"], today)
        items.append(
            {
                **{key: row[key] for key in ("coverage_id", "scheme_id", "page_kind", "section_label", "category", "sr_no_raw", "product_name", "standard_ref_raw", "listing_status", "status_basis", "enforcement_date", "ministry_department", "parent_coverage_id")},
                "effect": effect,
                "days_to_enforcement": days,
            }
        )
    return {"total": total, "items": plain(items)}


@router.get("/coverage/{coverage_id}")
def coverage_detail(coverage_id: int, conn: Connection = Depends(get_conn), today: date = Depends(get_today)) -> dict:
    evidence = EvidenceBuilder(conn)
    listings = load_listings(conn, [coverage_id], evidence, today)
    if not listings:
        raise HTTPException(404, "Listing not found.")
    table = schema.scheme_coverage
    children = conn.execute(
        sa.select(table.c.coverage_id, table.c.product_name).where(table.c.parent_coverage_id == coverage_id, table.c.is_current.is_(True)).order_by(table.c.coverage_id)
    ).mappings().all()
    return with_evidence({"listing": listings[0], "illustrative_items": children}, evidence)


@router.get("/qco/upcoming")
def upcoming(conn: Connection = Depends(get_conn), today: date = Depends(get_today)) -> dict:
    table = schema.scheme_coverage
    rows = conn.execute(
        sa.select(table.c.coverage_id)
        .where(table.c.is_current.is_(True), table.c.page_kind == "upcoming_qco", table.c.parent_coverage_id.is_(None))
        .order_by(table.c.enforcement_date.nulls_last(), table.c.coverage_id)
    ).all()
    evidence = EvidenceBuilder(conn)
    listings = load_listings(conn, [row.coverage_id for row in rows], evidence, today)
    return with_evidence({"checked_on": today, "items": listings}, evidence)


class AssessRequest(BaseModel):
    text: str | None = Field(None, max_length=300)
    std_key: str | None = Field(None, max_length=200)
    coverage_id: int | None = None


@router.post("/assess")
def assess_product(body: AssessRequest, conn: Connection = Depends(get_conn), today: date = Depends(get_today)) -> dict:
    if not (body.text or body.std_key or body.coverage_id):
        raise HTTPException(422, "Provide a product description, an IS number or a listing id.")
    result = assess(conn, text=body.text, std_key=body.std_key, coverage_id=body.coverage_id, today=today, vectors=get_state().vectors)
    return with_evidence(result)


class JourneyRequest(AssessRequest):
    state: str | None = Field(None, max_length=60)
    district: str | None = Field(None, max_length=80)
    city: str | None = Field(None, max_length=80)


@router.post("/journey")
def journey(body: JourneyRequest, conn: Connection = Depends(get_conn), today: date = Depends(get_today)) -> dict:
    if not (body.text or body.std_key or body.coverage_id):
        raise HTTPException(422, "Provide a product description, an IS number or a listing id.")
    result = build_journey(
        conn,
        text=body.text,
        std_key=body.std_key,
        coverage_id=body.coverage_id,
        state=body.state,
        district=body.district,
        city=body.city,
        today=today,
        vectors=get_state().vectors,
    )
    return with_evidence(result)


@router.get("/faq")
def faq(q: str | None = _text(), category: str | None = Query(None, max_length=60), limit: int = Query(20, ge=1, le=100), conn: Connection = Depends(get_conn)) -> dict:
    table = schema.faq
    query = sa.select(table).where(table.c.is_current.is_(True))
    if category:
        query = query.where(table.c.category == category)
    if q:
        ids = [hit.id for hit in fts_search.search_faq(conn, q, limit=limit)]
        rows = {row["faq_id"]: row for row in conn.execute(query.where(table.c.faq_id.in_(ids or [-1]))).mappings()}
        ordered = [rows[faq_id] for faq_id in ids if faq_id in rows]
    else:
        ordered = conn.execute(query.order_by(table.c.category, table.c.ordinal).limit(limit)).mappings().all()
    return {
        "items": [
            {**{key: row[key] for key in ("faq_id", "category", "ordinal", "question", "answer", "source_url", "retrieved_at")}, "answer_links": __import__("json").loads(row["answer_links"] or "[]")}
            for row in ordered
        ]
    }
