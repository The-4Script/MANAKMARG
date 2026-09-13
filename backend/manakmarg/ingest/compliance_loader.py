"""Loads parsed compulsory-certification listings into the normalized schema (plan Task 3.3).

For every ``CoverageRecord``: a ``scheme_coverage`` row (with status and quoted basis), resolved
``coverage_standard`` links (with explicit resolution kinds), shared ``regulatory_order`` rows linked
through ``coverage_order``, aliases for every standard reference seen on the page, and ``product_term``
rows for product search. Link tables are replaced per coverage row; coverage rows not seen in a run
are retired, never deleted.
"""

import hashlib
from collections import Counter

import sqlalchemy as sa

from manakmarg.db import schema
from manakmarg.ingest.bis_schemes import ILLUSTRATIVE_ITEM, CoverageRecord
from manakmarg.ingest.runs import RunRecorder
from manakmarg.normalize.orders import OrderRef, order_identity
from manakmarg.normalize.text import norm_match
from manakmarg.search.resolvers import UNRESOLVED, StandardResolver

# Descriptions are quoted from official BIS pages; None where no official description is published.
SCHEMES = {
    "SCHEME_I": {
        "name": "Scheme – I (ISI Mark Scheme)",
        "short_name": "Scheme I",
        "description": "“Product certification scheme for use of mark” under Scheme-I of the BIS (Conformity "
        "Assessment) Regulations, 2018 (BIS Product Certification Process page).",
        "mark": "Standard Mark under a Licence (BIS 'Products under Compulsory Certification' page).",
    },
    "SCHEME_II": {
        "name": "Scheme – II (Registration Scheme)",
        "short_name": "Scheme II",
        "description": "“Compulsory Registration Scheme” for self declaration of conformity (heading on the BIS "
        "Scheme II page).",
        "mark": None,
    },
    "SCHEME_IV": {
        "name": "Scheme – IV (Grant of Certificate of Conformity)",
        "short_name": "Scheme IV",
        "description": "“Product Certification Scheme for grant of certificate of conformity” under Scheme-IV of the "
        "BIS (Conformity Assessment) Regulations, 2018 (BIS Product Certification Process page).",
        "mark": "Certificate of Conformity (CoC) (BIS 'Products under Compulsory Certification' page).",
    },
    "SCHEME_X": {
        "name": "Scheme – X (Certification)",
        "short_name": "Scheme X",
        "description": None,
        "mark": None,
    },
}


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _coverage_base_key(record: CoverageRecord, parent_key: str | None) -> str:
    return _hash(
        "|".join(
            [
                record.page_kind,
                record.section_label or "",
                record.category or "",
                record.sr_no_raw or "",
                record.standard_ref_raw or "",
                record.product_name,
                parent_key or "",
            ]
        )
    )


def _seed_scheme(run: RunRecorder, scheme_id: str, page_url: str) -> None:
    info = SCHEMES[scheme_id]
    run.upsert(
        "certification_scheme",
        key={"scheme_id": scheme_id},
        values={
            "name": info["name"],
            "short_name": info["short_name"],
            "official_description": info["description"],
            "conformity_mark": info["mark"],
            "official_url": page_url,
        },
        locator=page_url,
    )


def _order_key(order: OrderRef) -> str:
    return order_identity(order.url, order.so_number, order.gsr_number)


def _upsert_order(run: RunRecorder, order: OrderRef) -> int:
    table = schema.regulatory_order
    key = _order_key(order)
    existing = run.conn.execute(sa.select(table.c.order_id, table.c.source_id).where(table.c.order_key == key)).first()
    if existing is not None and existing.source_id != run.source_id:
        return existing.order_id
    return run.upsert(
        "regulatory_order",
        key={"order_key": key},
        values={
            "title": order.title,
            "url": order.url,
            "order_kind": order.kind,
            "so_number": order.so_number,
            "gsr_number": order.gsr_number,
            "order_date": order.order_date,
            "raw_text": order.raw_text,
        },
        locator=order.url,
    ).pk


def _replace_order_links(run: RunRecorder, coverage_id: int, orders: list[OrderRef], cache: dict[str, int]) -> int:
    run.conn.execute(schema.coverage_order.delete().where(schema.coverage_order.c.coverage_id == coverage_id))
    for ordinal, order in enumerate(orders):
        key = _order_key(order)
        if key not in cache:
            cache[key] = _upsert_order(run, order)
        run.conn.execute(
            schema.coverage_order.insert().values(coverage_id=coverage_id, order_id=cache[key], ordinal=ordinal, relation=order.kind)
        )
    return len(orders)


def retire_unlinked_orders(conn) -> int:
    """Orders no current listing links to any more (for example rows keyed before orders sharing a PDF were kept
    apart) are marked not current; history is kept, nothing is deleted."""
    table, links = schema.regulatory_order, schema.coverage_order
    result = conn.execute(
        table.update()
        .where(table.c.is_current.is_(True), table.c.order_id.not_in(sa.select(links.c.order_id)))
        .values(is_current=False)
    )
    return result.rowcount


def _replace_standard_links(
    run: RunRecorder, coverage_id: int, record: CoverageRecord, resolver: StandardResolver, locator: str, summary: dict
) -> None:
    table = schema.coverage_standard
    run.conn.execute(table.delete().where(table.c.coverage_id == coverage_id))
    ordinal = 0
    for text, role in record.standard_refs:
        resolutions = resolver.resolve_text(text, assume_is_prefix=record.refs_assume_is_prefix)
        if not resolutions:
            run.conn.execute(
                table.insert().values(
                    coverage_id=coverage_id,
                    ordinal=ordinal,
                    ref_raw=text,
                    family_key=None,
                    standard_id=None,
                    resolution="no_designation_found",
                    role=role,
                )
            )
            ordinal += 1
            summary["unresolved_refs"] += 1
            continue
        for resolution in resolutions:
            run.conn.execute(
                table.insert().values(
                    coverage_id=coverage_id,
                    ordinal=ordinal,
                    ref_raw=resolution.ref_raw,
                    family_key=resolution.family_key,
                    standard_id=resolution.best_standard_id,
                    resolution=resolution.kind,
                    role=role,
                )
            )
            ordinal += 1
            summary["standard_links"] += 1
            if resolution.kind == UNRESOLVED:
                summary["unresolved_refs"] += 1
            if resolution.best_standard_id is not None:
                run.upsert(
                    "standard_alias",
                    key={"raw_text": resolution.ref_raw, "context": record.page_kind},
                    values={
                        "normalized_key": resolution.designation.std_key,
                        "resolution": resolution.kind,
                        "standard_id": resolution.best_standard_id,
                        "family_key": resolution.family_key,
                    },
                    locator=locator,
                )


def _replace_terms(run: RunRecorder, coverage_id: int, record: CoverageRecord) -> None:
    table = schema.product_term
    run.conn.execute(table.delete().where(table.c.coverage_id == coverage_id))
    product_origin = "illustrative_item" if record.item_kind == ILLUSTRATIVE_ITEM else "coverage_product"
    terms = [(record.product_name, product_origin, 1.0)]
    if record.category:
        terms.append((record.category, "coverage_category", 0.5))
    seen = set()
    for term, origin, weight in terms:
        normalized = norm_match(term)
        if not normalized or (normalized, origin) in seen:
            continue
        seen.add((normalized, origin))
        run.conn.execute(
            table.insert().values(term=term, term_norm=normalized, origin=origin, coverage_id=coverage_id, weight=weight)
        )


def load_scheme_records(
    run: RunRecorder, records: list[CoverageRecord], *, scheme_id: str | None, page_url: str
) -> dict:
    """Store one page's records inside ``run``; returns counts for the run summary."""
    if scheme_id:
        _seed_scheme(run, scheme_id, page_url)
    resolver = StandardResolver(run.conn)
    summary = {"coverage_rows": 0, "orders_linked": 0, "standard_links": 0, "unresolved_refs": 0}

    coverage_ids: dict[str, int] = {}
    base_keys: dict[str, str] = {}
    key_counts: Counter = Counter()
    order_cache: dict[str, int] = {}

    for record in records:
        parent_key = base_keys.get(record.parent_locator) if record.parent_locator else None
        base_key = _coverage_base_key(record, parent_key)
        base_keys[record.locator] = base_key
        key_counts[base_key] += 1
        coverage_key = base_key if key_counts[base_key] == 1 else _hash(f"{base_key}#{key_counts[base_key]}")
        locator = f"{page_url}#{record.locator}"

        coverage_id = run.upsert(
            "scheme_coverage",
            key={"coverage_key": coverage_key},
            values={
                "scheme_id": record.scheme_id,
                "page_kind": record.page_kind,
                "section_label": record.section_label,
                "category": record.category,
                "sr_no_raw": record.sr_no_raw,
                "product_name": record.product_name,
                "parent_coverage_id": coverage_ids.get(record.parent_locator) if record.parent_locator else None,
                "standard_ref_raw": record.standard_ref_raw,
                "standard_title_raw": record.standard_title_raw,
                "product_category": record.product_category,
                "essential_requirement": record.essential_requirement,
                "specific_requirement": record.specific_requirement,
                "notification_text_raw": record.notification_text,
                "listing_status": record.listing_status,
                "status_basis": record.status_basis,
                "ministry_department": record.ministry_department,
                "enforcement_date": record.enforcement_date,
                "enforcement_date_raw": record.enforcement_date_raw,
                "notes": record.notes,
            },
            locator=locator,
        ).pk
        coverage_ids[record.locator] = coverage_id
        summary["coverage_rows"] += 1

        _replace_standard_links(run, coverage_id, record, resolver, locator, summary)
        summary["orders_linked"] += _replace_order_links(run, coverage_id, record.orders, order_cache)
        _replace_terms(run, coverage_id, record)

    run.retire_unseen("scheme_coverage")
    run.retire_unseen("standard_alias")
    return summary
