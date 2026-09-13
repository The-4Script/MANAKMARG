"""Loads parsed page, guideline, laboratory and hallmarking records into the normalized schema.

Every loader works inside one ``RunRecorder`` (one source): it stamps provenance through ``run.upsert`` and
retires rows of that source that the run no longer saw. Child tables (manual sections, chunks, scope items,
district aliases, product terms) are replaced per parent row. Operability of labs and AHCs is not stored here;
it is computed at query time against the clock from the stored official facts.
"""

import hashlib
import json
from collections import Counter

import sqlalchemy as sa

from manakmarg.db import schema
from manakmarg.ingest.bis_pages import FaqRecord, PageText, ProcessStepRecord, SchemeDocRecord
from manakmarg.ingest.compliance_loader import SCHEMES
from manakmarg.ingest.documents import (
    TEXT_EXTRACTED,
    TEXT_NO_TEXT_LAYER,
    TEXT_PARSED,
    Chunk,
    chunk_page_texts,
    register_document,
    replace_chunks,
)
from manakmarg.ingest.fetch import FetchResult
from manakmarg.ingest.hallmarking import AhcEventRecord, AhcRecord, DistrictRecord, GazetteValidation
from manakmarg.ingest.lab_lists import GroupList
from manakmarg.ingest.lims import LabRecord, ScopeRecord
from manakmarg.ingest.product_manual import ParsedManual
from manakmarg.ingest.psg import GuidelineRecord
from manakmarg.ingest.runs import RunRecorder
from manakmarg.normalize.geo import norm_district
from manakmarg.normalize.text import norm_match
from manakmarg.search.resolvers import EXACT_VERSION, MATCH_KEY_VERSION, StandardResolver


def _key(*parts) -> str:
    text = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _unique(counter: Counter, base: str) -> str:
    counter[base] += 1
    return base if counter[base] == 1 else f"{base}#{counter[base]}"


# --------------------------------------------------------------------------- process pages, FAQs, web pages


def _ensure_scheme(run: RunRecorder, scheme_id: str | None) -> None:
    if scheme_id is None or scheme_id not in SCHEMES:
        return
    table = schema.certification_scheme
    if run.conn.execute(sa.select(table.c.scheme_id).where(table.c.scheme_id == scheme_id)).first():
        return
    info = SCHEMES[scheme_id]
    run.upsert(
        "certification_scheme",
        key={"scheme_id": scheme_id},
        values={
            "name": info["name"],
            "short_name": info["short_name"],
            "official_description": info["description"],
            "conformity_mark": info["mark"],
            "official_url": None,
        },
        locator=f"scheme:{scheme_id}",
    )


def load_process_steps(
    run: RunRecorder, steps: list[ProcessStepRecord], *, page_url: str, scheme_id: str | None = None
) -> dict:
    _ensure_scheme(run, scheme_id)
    for step in steps:
        run.upsert(
            "process_step",
            key={"scheme_id": scheme_id, "ordinal": step.ordinal},
            values={
                "step_label": step.step_label,
                "text": step.text,
                "link_url": step.link_url,
                "link_label": step.link_label,
            },
            locator=f"{page_url}#{step.locator}",
        )
    return {"steps": len(steps), "retired": run.retire_unseen("process_step")}


def load_scheme_documents(run: RunRecorder, documents: list[SchemeDocRecord], *, page_url: str) -> dict:
    for scheme_id in sorted({document.scheme_id for document in documents if document.scheme_id}):
        _ensure_scheme(run, scheme_id)
    for document in documents:
        run.upsert(
            "scheme_document",
            key={"scheme_id": document.scheme_id, "url": document.url},
            values={
                "ordinal": document.ordinal,
                "title": document.title,
                "size_text": document.size_text,
                "category": document.category,
            },
            locator=f"{page_url}#{document.locator}",
        )
    return {"documents": len(documents), "retired": run.retire_unseen("scheme_document")}


def load_faqs(run: RunRecorder, faqs: list[FaqRecord], *, page_url: str) -> dict:
    keys: Counter = Counter()
    for faq in faqs:
        links = [{"label": label, "url": url} for label, url in faq.answer_links]
        run.upsert(
            "faq",
            key={"faq_key": _unique(keys, _key(faq.category, faq.question))},
            values={
                "category": faq.category,
                "ordinal": faq.ordinal,
                "question": faq.question,
                "answer": faq.answer,
                "answer_links": json.dumps(links, ensure_ascii=False) if links else None,
                "language": "en",
                "source_url": page_url,
            },
            locator=f"{page_url}#{faq.locator}",
        )
    return {"faqs": len(faqs), "retired": run.retire_unseen("faq")}


def load_web_page(run: RunRecorder, page: PageText, *, url: str, fetched: FetchResult | None = None) -> dict:
    """An official HTML page kept as a searchable document (title, text blocks, last-updated date)."""
    chunks = chunk_page_texts([(None, "\n".join(page.paragraphs))])
    document_id = register_document(
        run,
        url=url,
        doc_type="web_page",
        title=page.title,
        source_page_url=url,
        text_status=TEXT_PARSED if chunks else TEXT_NO_TEXT_LAYER,
        fetched=fetched,
        doc_date=page.last_updated,
    )
    return {"document_id": document_id, "chunks": replace_chunks(run.conn, document_id, chunks), "links": len(page.links)}


# --------------------------------------------------------------------------- guidelines and documents


def load_guidelines(run: RunRecorder, records: list[GuidelineRecord], *, page_url: str) -> dict:
    resolver = StandardResolver(run.conn)
    terms = schema.product_term
    summary = Counter()
    seen: set[str] = set()
    for record in records:
        guideline_key = _key(record.url, record.is_ref_raw)
        if guideline_key in seen:
            summary["duplicate_rows"] += 1
            continue
        seen.add(guideline_key)
        resolutions = resolver.resolve_text(record.is_ref_raw)
        resolution = resolutions[0] if resolutions else None
        guideline_id = run.upsert(
            "product_guideline",
            key={"guideline_key": guideline_key},
            values={
                "url": record.url,
                "is_ref_raw": record.is_ref_raw,
                "family_key": resolution.family_key if resolution else None,
                "standard_id": resolution.best_standard_id if resolution else None,
                "resolution": resolution.kind if resolution else "no_designation_found",
                "title": record.title or record.is_ref_raw,
                "doc_kind": record.doc_kind,
                "size_text": record.size_text,
                "format_text": record.format_text,
            },
            locator=f"{page_url}#{record.locator}",
        ).pk
        summary["guidelines"] += 1
        summary["resolved" if resolution and resolution.best_standard_id else "unresolved"] += 1
        run.conn.execute(terms.delete().where(terms.c.guideline_id == guideline_id))
        if record.title and norm_match(record.title):
            run.conn.execute(
                terms.insert().values(
                    term=record.title,
                    term_norm=norm_match(record.title),
                    origin="guideline_title",
                    guideline_id=guideline_id,
                    standard_id=resolution.best_standard_id if resolution else None,
                    weight=0.6,
                )
            )
    summary["retired"] = run.retire_unseen("product_guideline")
    return dict(summary)


def set_guideline_status(run: RunRecorder, url: str, status: str, document_id: int | None) -> list[int]:
    """Record on every guideline row pointing at ``url`` how far its document could be read."""
    table = schema.product_guideline
    ids = [row.guideline_id for row in run.conn.execute(sa.select(table.c.guideline_id).where(table.c.url == url))]
    if ids:
        run.conn.execute(
            table.update().where(table.c.guideline_id.in_(ids)).values(parse_status=status, document_id=document_id)
        )
    return ids


def load_product_manual(
    run: RunRecorder,
    *,
    url: str,
    title: str | None,
    manual: ParsedManual,
    fetched: FetchResult,
    page_count: int,
    source_page_url: str | None,
) -> dict:
    document_id = register_document(
        run,
        url=url,
        doc_type="product_manual",
        title=title or manual.document_no,
        source_page_url=source_page_url,
        text_status=TEXT_PARSED,
        fetched=fetched,
        pages=page_count,
    )
    sections = schema.guideline_section
    guideline_ids = set_guideline_status(run, url, TEXT_PARSED, document_id)
    for guideline_id in guideline_ids:
        run.conn.execute(sections.delete().where(sections.c.guideline_id == guideline_id))
        for ordinal, section in enumerate(manual.sections, start=1):
            run.conn.execute(
                sections.insert().values(
                    guideline_id=guideline_id,
                    ordinal=ordinal,
                    section_key=section.section_key,
                    heading=section.heading,
                    page_start=section.page_start,
                    page_end=section.page_end,
                    text=section.text,
                    structured_json=json.dumps(section.structured, ensure_ascii=False) if section.structured else None,
                )
            )
    chunks = [
        Chunk(ordinal, section.page_start, section.page_end, section.text, section.section_key, section.heading)
        for ordinal, section in enumerate((section for section in manual.sections if section.text), start=1)
    ]
    return {
        "document_id": document_id,
        "guidelines_linked": len(guideline_ids),
        "sections": len(manual.sections),
        "chunks": replace_chunks(run.conn, document_id, chunks),
    }


def record_document_failure(
    run: RunRecorder,
    *,
    url: str,
    doc_type: str,
    title: str | None,
    source_page_url: str | None,
    text_status: str,
    http_status: int | None,
    reason: str,
) -> int:
    """Register a document that could not be read (e.g. HTTP 403) so the gap stays visible; never retried."""
    document_id = register_document(
        run,
        url=url,
        doc_type=doc_type,
        title=title,
        source_page_url=source_page_url,
        text_status=text_status,
        http_status=http_status,
        notes=reason,
    )
    if doc_type == "product_manual":
        set_guideline_status(run, url, text_status, document_id)
    return document_id


def load_text_document(
    run: RunRecorder,
    *,
    url: str,
    doc_type: str,
    title: str | None,
    page_texts: list[tuple[int, str]],
    fetched: FetchResult,
    source_page_url: str | None,
    doc_date=None,
) -> dict:
    """A fetched PDF kept as page-numbered text chunks for retrieval."""
    chunks = chunk_page_texts(page_texts)
    document_id = register_document(
        run,
        url=url,
        doc_type=doc_type,
        title=title,
        source_page_url=source_page_url,
        text_status=TEXT_EXTRACTED if chunks else TEXT_NO_TEXT_LAYER,
        fetched=fetched,
        pages=len(page_texts),
        doc_date=doc_date,
    )
    return {"document_id": document_id, "chunks": replace_chunks(run.conn, document_id, chunks)}


def link_order_document(run: RunRecorder, *, order_url: str, document_id: int) -> int:
    orders = schema.regulatory_order
    return run.conn.execute(
        orders.update().where(orders.c.order_key == order_url).values(document_id=document_id)
    ).rowcount


# --------------------------------------------------------------------------- laboratories


def lab_key(lab: LabRecord) -> str:
    if lab.lims_lab_id is not None:
        return f"lims:{lab.lims_lab_id}"
    if lab.osl_code:
        return f"osl:{lab.osl_code}"
    return f"name:{norm_match(lab.name)}"


def load_labs(run: RunRecorder, labs: list[LabRecord], *, directory_url: str) -> dict:
    keys: Counter = Counter()
    for lab in labs:
        run.upsert(
            "laboratory",
            key={"lab_key": _unique(keys, lab_key(lab))},
            values={
                "osl_code": lab.osl_code,
                "lims_lab_id": lab.lims_lab_id,
                "name": lab.name,
                "lab_category": lab.category,
                "address_raw": lab.address_raw,
                "city": lab.address.city,
                "district": lab.address.district,
                "state": lab.address.state,
                "pincode": lab.address.pincode,
                "org_phone": lab.org_phone,
                "org_email": lab.org_email,
                "lims_validity_date": lab.validity_date,
                "lims_validity_raw": lab.validity_raw,
            },
            locator=f"{directory_url}#{lab.locator}",
        )
    return {"labs": len(labs), "retired": run.retire_unseen("laboratory")}


def _lab_indexes(conn) -> tuple[dict[str, int], dict[str, int]]:
    table = schema.laboratory
    by_osl: dict[str, int] = {}
    by_name: dict[str, int] = {}
    rows = conn.execute(
        sa.select(table.c.lab_id, table.c.osl_code, table.c.name)
        .where(table.c.is_current.is_(True))
        .order_by(table.c.lab_id)
    )
    for row in rows:
        if row.osl_code:
            by_osl.setdefault(row.osl_code, row.lab_id)
        by_name.setdefault(norm_match(row.name), row.lab_id)
    return by_osl, by_name


def load_lab_scope(run: RunRecorder, rows: list[ScopeRecord], *, query_doc_no: str, search_url: str) -> dict:
    """Store LIMS IS-wise rows for one searched document number. A standard is linked only when LIMS names a
    version that is in the published list; otherwise only the family key is kept."""
    resolver = StandardResolver(run.conn)
    by_osl, by_name = _lab_indexes(run.conn)
    items = schema.lab_scope_item
    keys: Counter = Counter()
    summary = Counter()
    for row in rows:
        if row.lims_row_id is not None:
            base = _key("lims-row", row.lims_row_id)
        else:
            base = _key(query_doc_no, row.lab_name_raw, row.osl_code_raw, row.is_ref_raw, row.product, row.grade_type)
        resolutions = resolver.resolve_text(row.is_ref_raw)
        resolution = resolutions[0] if resolutions else None
        standard_id = (
            resolution.best_standard_id if resolution and resolution.kind in (EXACT_VERSION, MATCH_KEY_VERSION) else None
        )
        lab_id = by_osl.get(row.osl_code_raw) if row.osl_code_raw else None
        if lab_id is None:
            lab_id = by_name.get(norm_match(row.lab_name_raw))
        scope_id = run.upsert(
            "lab_scope",
            key={"scope_key": _unique(keys, base)},
            values={
                "lab_id": lab_id,
                "lab_name_raw": row.lab_name_raw,
                "osl_code_raw": row.osl_code_raw,
                "is_ref_raw": row.is_ref_raw,
                "family_key": resolution.family_key if resolution else None,
                "standard_id": standard_id,
                "version_year": row.version_year,
                "product": row.product,
                "grade_type": row.grade_type,
                "charges_total": row.charges_total,
                "charges_raw": row.charges_raw,
                "validity_date": row.validity_date,
                "validity_raw": row.validity_raw,
                "remark_raw": row.remark_raw,
                "exclusions_text": row.exclusions_text,
                "scope_file_url": row.scope_file_url,
                "query_doc_no": query_doc_no,
            },
            locator=f"{search_url}#{row.locator}",
        ).pk
        run.conn.execute(items.delete().where(items.c.scope_id == scope_id))
        for ordinal, item in enumerate(row.items, start=1):
            run.conn.execute(
                items.insert().values(
                    scope_id=scope_id,
                    ordinal=ordinal,
                    clause=item.clause,
                    parameter=item.parameter,
                    exclusion=item.exclusion,
                    charge=item.charge,
                    charge_raw=item.charge_raw,
                    effective_date_raw=item.effective_date_raw,
                    remark=item.remark,
                )
            )
        summary["rows"] += 1
        summary["items"] += len(row.items)
        summary["labs_linked"] += lab_id is not None
        summary["standards_linked"] += standard_id is not None
    summary["retired"] = run.retire_unseen("lab_scope", where={"query_doc_no": query_doc_no})
    return dict(summary)


def load_group_list(run: RunRecorder, group_list: GroupList, *, document_url: str) -> dict:
    keys: Counter = Counter()
    as_of = group_list.as_of.isoformat() if group_list.as_of else group_list.as_of_raw
    statuses = Counter()
    for record in group_list.records:
        identity = f"osl:{record.osl_code}" if record.osl_code else f"sl:{record.sl_no}"
        run.upsert(
            "lab_list_entry",
            key={"entry_key": _unique(keys, f"group{group_list.group_no}:{identity}")},
            values={
                "group_no": group_list.group_no,
                "osl_code": record.osl_code,
                "name_raw": record.name,
                "state_raw": record.state_raw,
                "state": record.state,
                "ownership": record.ownership,
                "valid_upto": record.valid_upto,
                "valid_upto_raw": record.valid_upto_raw,
                "remarks_raw": record.remarks_raw,
                "derived_status": record.derived_status,
                "status_basis": record.status_basis,
                "list_as_of": as_of,
            },
            locator=f"{document_url}#{record.locator}",
        )
        statuses[record.derived_status] += 1
    return {
        "entries": len(group_list.records),
        "statuses": dict(statuses),
        "retired": run.retire_unseen("lab_list_entry"),
    }


# --------------------------------------------------------------------------- hallmarking


def load_ahcs(run: RunRecorder, records: list[AhcRecord], *, page_url: str) -> dict:
    summary = Counter()
    seen: set[str] = set()
    for record in records:
        locator = f"{page_url}#{record.locator}"
        if not record.name:
            run.reject(locator, "AHC row without a centre name")
            continue
        if record.recognition_no in seen:
            summary["duplicate_rows"] += 1
            continue
        seen.add(record.recognition_no)
        run.upsert(
            "ahc",
            key={"recognition_no": record.recognition_no},
            values={
                "region_code": record.region_code,
                "name": record.name,
                "address_raw": record.address_raw,
                "district": record.address.district,
                "area": record.address.area,
                "state": record.address.state,
                "pincode": record.address.pincode,
                "scope_text": record.scope_text,
                "gold": record.gold,
                "silver": record.silver,
                "validity_date": record.validity_date,
                "validity_raw": record.validity_raw,
                "list_status_raw": record.list_status_raw,
                "org_phone": record.org_phone,
                "org_email": record.org_email,
            },
            locator=locator,
        )
        summary["ahcs"] += 1
    summary["retired"] = run.retire_unseen("ahc")
    return dict(summary)


def load_ahc_events(run: RunRecorder, events: list[AhcEventRecord], *, page_url: str) -> dict:
    keys: Counter = Counter()
    for event in events:
        run.upsert(
            "ahc_status_event",
            key={"event_key": _unique(keys, f"{event.recognition_no}|{event.status}|{event.event_date_raw or ''}")},
            values={
                "recognition_no": event.recognition_no,
                "status": event.status,
                "event_date": event.event_date,
                "event_date_raw": event.event_date_raw,
                "region": event.region,
                "center_type": event.center_type,
                "name_address_raw": event.name_address_raw,
            },
            locator=f"{page_url}#{event.locator}",
        )
    return {"events": len(events), "retired": run.retire_unseen("ahc_status_event")}


def load_districts(
    run: RunRecorder, records: list[DistrictRecord], validation: GazetteValidation | None, *, document_url: str
) -> dict:
    variants = {
        (state, district): (name, basis) for state, district, name, basis in (validation.variants if validation else ())
    }
    aliases = schema.district_alias
    keys: Counter = Counter()
    summary = Counter()
    for record in records:
        locator = f"{document_url}#{record.locator}"
        if not record.state:
            run.reject(locator, f"Unrecognised state/UT name '{record.state_raw}'")
            continue
        note = validation.notes.get(record.sr_no) if validation else None
        in_gazette = None if validation is None else bool(note) and not note.startswith("Not found")
        district_id = run.upsert(
            "hallmarking_district",
            key={"district_key": _unique(keys, f"{record.state}|{record.district_norm}")},
            values={
                "sr_no": record.sr_no,
                "state_raw": record.state_raw,
                "state": record.state,
                "district_raw": record.district_raw,
                "district": record.district,
                "district_norm": record.district_norm,
                "phase_no": record.phase_no,
                "phase_label": record.phase_label,
                "phase_order_date": record.phase_order_date,
                "phase_order_date_raw": record.phase_order_date_raw,
                "gazette_validated": in_gazette,
                "gazette_note": note,
            },
            locator=locator,
        ).pk
        names = {record.district_norm: "phasewise_name"}
        names.setdefault(record.district_norm.replace(" ", ""), "compact_name")
        variant = variants.get((record.state, record.district))
        if variant:
            names.setdefault(norm_district(variant[0]), f"gazette_{variant[1]}")
        run.conn.execute(aliases.delete().where(aliases.c.district_id == district_id))
        for alias_norm, basis in names.items():
            if alias_norm:
                run.conn.execute(aliases.insert().values(alias_norm=alias_norm, district_id=district_id, basis=basis))
        summary["districts"] += 1
        summary["not_in_gazette"] += in_gazette is False
    for state, name in validation.extra_in_gazette if validation else ():
        run.errors.append({"locator": None, "reason": f"gazette_annex_only: {state} / {name}"})
    summary["gazette_annex_only"] = len(validation.extra_in_gazette) if validation else 0
    summary["retired"] = run.retire_unseen("hallmarking_district")
    return dict(summary)


def load_gazette_only_districts(
    run: RunRecorder, entries: list[tuple[str, str]], *, document_url: str, note: str
) -> dict:
    """Districts the Gazette annex lists but the phase-wise list does not. They are kept under the Gazette's
    provenance, without a phase, and are always shown as needing verification."""
    aliases = schema.district_alias
    keys: Counter = Counter()
    for state, name in entries:
        district_norm = norm_district(name)
        district_id = run.upsert(
            "hallmarking_district",
            key={"district_key": _unique(keys, f"{state}|{district_norm}")},
            values={
                "sr_no": None,
                "state_raw": state,
                "state": state,
                "district_raw": name,
                "district": name,
                "district_norm": district_norm,
                "phase_no": None,
                "phase_label": None,
                "phase_order_date": None,
                "phase_order_date_raw": None,
                "gazette_validated": True,
                "gazette_note": note,
            },
            locator=f"{document_url}#annexure:{state}/{name}",
        ).pk
        names = {district_norm: "gazette_name"}
        names.setdefault(district_norm.replace(" ", ""), "compact_name")
        run.conn.execute(aliases.delete().where(aliases.c.district_id == district_id))
        for alias_norm, basis in names.items():
            if alias_norm:
                run.conn.execute(aliases.insert().values(alias_norm=alias_norm, district_id=district_id, basis=basis))
    return {"districts": len(entries), "retired": run.retire_unseen("hallmarking_district")}
