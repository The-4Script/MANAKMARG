"""Compliance journey builder (spec §9.2).

Product → standard(s) → compulsory status → certification scheme → Product Manual → tests → laboratories →
application → next actions. A step carries data only when official records support it; otherwise it is returned
as ``missing`` with a note, never filled with guesses.
"""

import json
from dataclasses import dataclass, field
from datetime import date

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from manakmarg.core import clock
from manakmarg.db import schema
from manakmarg.ingest.sources import REGISTRY
from manakmarg.reasoning.applicability import (
    CANDIDATE,
    IN_FORCE_OR_NOTIFIED,
    LIKELY_APPLICABLE,
    NO_LISTING_FOUND,
    Assessment,
    ListingView,
    assess,
)
from manakmarg.reasoning.evidence import EvidenceBuilder
from manakmarg.reasoning.labs import find_labs

OK = "ok"
ATTENTION = "attention"
MISSING = "missing"

STANDARDS_PORTAL_URL = REGISTRY["bis_std_export_total"].url
MANAKONLINE_URL = "https://www.manakonline.in/MANAK/ApplicationLicenceRelatedrpt"
MAX_STANDARDS = 3
MAX_SIT_ROWS = 40


@dataclass
class JourneyStep:
    key: str
    state: str
    data: dict = field(default_factory=dict)
    evidence_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Journey:
    query: dict
    checked_on: date
    assessment: Assessment
    selected: ListingView | None
    steps: list[JourneyStep]
    next_actions: list[dict]
    evidence: EvidenceBuilder


def _standard_ids(assessment: Assessment, selected: ListingView | None) -> list[int]:
    ids: list[int] = []
    if selected is not None:
        ids += [link.standard_id for link in selected.standards if link.standard_id and link.role == "specified"]
        ids += [link.standard_id for link in selected.standards if link.standard_id and link.role != "specified"]
    if not ids:
        for identifier in assessment.identifiers:
            ids += list(identifier.standard_ids[:1])
    if not ids and assessment.label == CANDIDATE:
        ids += [candidate.standard_id for candidate in assessment.standards[:1]]
    return list(dict.fromkeys(ids))[:MAX_STANDARDS]


def _standards_step(conn: Connection, ids: list[int], evidence: EvidenceBuilder) -> JourneyStep:
    if not ids:
        return JourneyStep("standards", MISSING, notes=["no_standard_identified"])
    table = schema.standard
    rows = conn.execute(sa.select(table).where(table.c.standard_id.in_(ids))).mappings().all()
    by_id = {row["standard_id"]: row for row in rows}
    node, links = schema.classification_node, schema.standard_classification
    standards, evidence_ids = [], []
    for standard_id in ids:
        row = by_id.get(standard_id)
        if row is None:
            continue
        evidence_id = evidence.add_record(
            "standard", row, record_id=row["std_key"], title=f"{row['std_key']} — {row['title_clean'] or row['title']}", snippet=row["title"]
        )
        evidence_ids.append(evidence_id)
        versions = conn.execute(
            sa.select(table.c.std_key, table.c.year, table.c.publication_date, table.c.listing_status)
            .where(table.c.family_key == row["family_key"], table.c.is_current.is_(True))
            .order_by(table.c.year.desc())
        ).mappings().all()
        ministries = conn.execute(
            sa.select(node.c.name, node.c.dimension)
            .select_from(links.join(node, node.c.node_id == links.c.node_id))
            .where(links.c.standard_id == standard_id, links.c.is_current.is_(True))
        ).mappings().all()
        standards.append(
            {
                "standard_id": standard_id,
                "std_key": row["std_key"],
                "family_key": row["family_key"],
                "title": row["title_clean"] or row["title"],
                "standard_type": row["standard_type"],
                "degree_of_equivalence": row["degree_of_equivalence"],
                "publication_date": row["publication_date"],
                "revision_label": row["revision_label"],
                "versions": [dict(version) for version in versions],
                "classification": [dict(item) for item in ministries],
                "portal_url": STANDARDS_PORTAL_URL,
                "evidence_id": evidence_id,
            }
        )
    return JourneyStep("standards", OK if standards else MISSING, {"standards": standards}, evidence_ids)


def _status_step(assessment: Assessment, selected: ListingView | None) -> JourneyStep:
    data = {
        "label": assessment.label,
        "compulsory": assessment.compulsory,
        "basis": assessment.basis,
        "listing": selected,
        "other_listings": assessment.listings[1:5],
    }
    if selected is None:
        return JourneyStep("compulsory_status", MISSING, data, notes=["absence_not_proof"])
    ids = [selected.evidence_id, *(order.evidence_id for order in selected.orders)]
    state = OK if selected.effect in IN_FORCE_OR_NOTIFIED and assessment.label not in ("NEEDS_VERIFICATION",) else ATTENTION
    return JourneyStep("compulsory_status", state, data, ids)


def _scheme_step(conn: Connection, selected: ListingView | None, evidence: EvidenceBuilder) -> JourneyStep:
    if selected is None:
        return JourneyStep("scheme", MISSING, notes=["no_listing"])
    if selected.scheme_id is None:
        return JourneyStep("scheme", ATTENTION, {"scheme": None}, notes=["scheme_not_stated_on_upcoming_page"])
    scheme = conn.execute(
        sa.select(schema.certification_scheme).where(schema.certification_scheme.c.scheme_id == selected.scheme_id)
    ).mappings().first()
    documents = conn.execute(
        sa.select(schema.scheme_document)
        .where(schema.scheme_document.c.scheme_id == selected.scheme_id, schema.scheme_document.c.is_current.is_(True))
        .order_by(schema.scheme_document.c.ordinal)
    ).mappings().all()
    ids = []
    if scheme is not None:
        ids.append(
            evidence.add_record("certification_scheme", scheme, record_id=scheme["scheme_id"], title=scheme["name"], snippet=scheme["official_description"], url=scheme["official_url"])
        )
    docs = []
    for document in documents:
        evidence_id = evidence.add_record("scheme_document", document, record_id=document["scheme_doc_id"], title=document["title"], url=document["url"])
        ids.append(evidence_id)
        docs.append({"title": document["title"], "url": document["url"], "size_text": document["size_text"], "category": document["category"], "evidence_id": evidence_id})
    data = {
        "scheme_id": selected.scheme_id,
        "name": scheme["name"] if scheme else selected.scheme_name,
        "official_description": scheme["official_description"] if scheme else None,
        "conformity_mark": scheme["conformity_mark"] if scheme else None,
        "official_url": scheme["official_url"] if scheme else None,
        "documents": docs,
    }
    return JourneyStep("scheme", OK, data, ids)


def _manual_steps(conn: Connection, families: list[str], evidence: EvidenceBuilder) -> tuple[JourneyStep, list[dict]]:
    if not families:
        return JourneyStep("product_manual", MISSING, notes=["no_standard_identified"]), []
    table = schema.product_guideline
    rows = conn.execute(
        sa.select(table).where(table.c.family_key.in_(families), table.c.is_current.is_(True)).order_by(table.c.guideline_id)
    ).mappings().all()
    if not rows:
        return JourneyStep("product_manual", MISSING, notes=["no_manual_listed"]), []
    sections_table = schema.guideline_section
    manuals, ids, parsed_sections = [], [], []
    for row in rows:
        evidence_id = evidence.add_record("product_guideline", row, record_id=row["guideline_id"], title=f"{row['is_ref_raw']} — {row['title']}", url=row["url"])
        ids.append(evidence_id)
        sections = conn.execute(
            sa.select(sections_table).where(sections_table.c.guideline_id == row["guideline_id"]).order_by(sections_table.c.ordinal)
        ).mappings().all()
        section_views = []
        for section in sections:
            structured = json.loads(section["structured_json"]) if section["structured_json"] else {}
            section_evidence = evidence.add(
                kind="guideline_section",
                record_id=f"{row['guideline_id']}:{section['section_key']}",
                title=f"{row['title']} — {section['heading'] or section['section_key']}",
                source_id="bis_product_manual_documents",
                snippet=section["text"],
                url=row["url"],
                page=section["page_start"],
            )
            section_views.append(
                {
                    "section_key": section["section_key"],
                    "heading": section["heading"],
                    "page_start": section["page_start"],
                    "page_end": section["page_end"],
                    "evidence_id": section_evidence,
                }
            )
            parsed_sections.append({"guideline": row, "section": section, "structured": structured, "evidence_id": section_evidence})
        summary = next((item["structured"] for item in parsed_sections if item["guideline"]["guideline_id"] == row["guideline_id"] and item["section"]["section_key"] == "summary"), {})
        manuals.append(
            {
                "guideline_id": row["guideline_id"],
                "title": row["title"],
                "is_ref_raw": row["is_ref_raw"],
                "doc_kind": row["doc_kind"],
                "url": row["url"],
                "parse_status": row["parse_status"],
                "size_text": row["size_text"],
                "summary": summary,
                "sections": section_views,
                "evidence_id": evidence_id,
            }
        )
    state = OK if any(manual["parse_status"] == "parsed" for manual in manuals) else ATTENTION
    notes = [] if state == OK else ["manual_not_parsed"]
    if any(manual["parse_status"] == "access_denied" for manual in manuals):
        notes.append("manual_access_denied")
    return JourneyStep("product_manual", state, {"manuals": manuals}, ids, notes), parsed_sections


def _tests_step(parsed_sections: list[dict], labs_step: JourneyStep) -> JourneyStep:
    sit = next((item for item in parsed_sections if item["section"]["section_key"] == "sit" and item["structured"].get("rows")), None)
    equipment = next((item for item in parsed_sections if item["section"]["section_key"] == "test_equipment" and item["structured"].get("tests")), None)
    if sit or equipment:
        data = {
            "source": "product_manual",
            "manual_title": (sit or equipment)["guideline"]["title"],
            "manual_url": (sit or equipment)["guideline"]["url"],
            "sit_rows": sit["structured"]["rows"][:MAX_SIT_ROWS] if sit else [],
            "sit_row_count": len(sit["structured"]["rows"]) if sit else 0,
            "sit_page": sit["section"]["page_start"] if sit else None,
            "test_equipment": equipment["structured"]["tests"] if equipment else [],
        }
        ids = [item["evidence_id"] for item in (sit, equipment) if item]
        return JourneyStep("tests", OK, data, ids)
    matches = labs_step.data.get("matches") or []
    if matches:
        first = matches[0]
        data = {"source": "lims_scope", "lab_name": first.lab_name, "is_ref_raw": first.is_ref_raw, "tests": list(first.tests), "test_count": first.test_count}
        return JourneyStep("tests", ATTENTION, data, list(first.evidence_ids[:1]), ["tests_from_lab_scope_only"])
    return JourneyStep("tests", MISSING, notes=["no_test_information"])


def _labs_step(conn: Connection, family_keys: list[str], location: dict, today: date, evidence: EvidenceBuilder) -> JourneyStep:
    if not family_keys:
        return JourneyStep("labs", MISSING, notes=["no_standard_identified"])
    result = find_labs(conn, " ".join(family_keys), today=today, evidence=evidence, **location)
    data = {
        "matches": result.matches[:6],
        "counts": result.counts,
        "indexed_doc_numbers": result.indexed_doc_numbers,
        "lims_search_urls": result.lims_search_urls,
        "location": result.location,
        "location_fallback": result.location_fallback,
    }
    if not result.matches:
        return JourneyStep("labs", ATTENTION if result.lims_search_urls else MISSING, data, notes=result.notes or ["no_labs_found"])
    ids = [evidence_id for match in result.matches[:6] for evidence_id in match.evidence_ids[:1]]
    notes = ["location_fallback"] if result.location_fallback else []
    return JourneyStep("labs", OK, data, ids, notes)


def _application_step(conn: Connection, selected: ListingView | None, evidence: EvidenceBuilder) -> JourneyStep:
    rows = conn.execute(
        sa.select(schema.process_step).where(schema.process_step.c.is_current.is_(True)).order_by(schema.process_step.c.ordinal)
    ).mappings().all()
    if not rows:
        return JourneyStep("application", MISSING, notes=["no_process_steps"])
    steps, ids = [], []
    for row in rows:
        evidence_id = evidence.add_record("process_step", row, record_id=row["step_id"], title=f"Apply for licence — step {row['step_label']}", snippet=row["text"])
        ids.append(evidence_id)
        steps.append({"step_label": row["step_label"], "text": row["text"], "link_url": row["link_url"], "link_label": row["link_label"], "evidence_id": evidence_id})
    notes = []
    if selected is not None and selected.scheme_id not in (None, "SCHEME_I"):
        notes.append("steps_describe_scheme_i_licence")
    return JourneyStep("application", OK, {"steps": steps, "portal_url": MANAKONLINE_URL}, ids, notes)


def _next_actions(assessment: Assessment, selected: ListingView | None, steps: dict[str, JourneyStep]) -> list[dict]:
    actions: list[dict] = []
    if assessment.label in (LIKELY_APPLICABLE, CANDIDATE):
        actions.append({"code": "confirm_product"})
    if steps["compulsory_status"].state == ATTENTION:
        actions.append({"code": "verify_status", "url": selected.page_url if selected else None})
    if selected is not None and selected.effect == "UPCOMING" and selected.enforcement_date:
        actions.append({"code": "prepare_before_enforcement", "date": selected.enforcement_date, "days": selected.days_to_enforcement})
    for standard in steps["standards"].data.get("standards", [])[:1]:
        actions.append({"code": "obtain_standard", "std_key": standard["std_key"], "url": standard["portal_url"]})
    for manual in steps["product_manual"].data.get("manuals", [])[:1]:
        actions.append({"code": "read_product_manual", "title": manual["title"], "url": manual["url"]})
    if steps["labs"].data.get("matches"):
        actions.append({"code": "test_at_listed_lab", "count": steps["labs"].data["counts"].get("laboratories")})
    elif steps["labs"].data.get("lims_search_urls"):
        actions.append({"code": "search_lims", "url": steps["labs"].data["lims_search_urls"][0]})
    if selected is not None and selected.effect in IN_FORCE_OR_NOTIFIED:
        actions.append({"code": "apply_online", "url": MANAKONLINE_URL, "scheme_id": selected.scheme_id})
    if assessment.compulsory == NO_LISTING_FOUND:
        actions.append({"code": "check_official_listing", "url": REGISTRY["bis_compulsory_overview_page"].url})
    return actions


def build_journey(
    conn: Connection,
    *,
    text: str | None = None,
    std_key: str | None = None,
    coverage_id: int | None = None,
    state: str | None = None,
    district: str | None = None,
    city: str | None = None,
    today: date | None = None,
    vectors=None,
) -> Journey:
    today = today or clock.today()
    evidence = EvidenceBuilder(conn)
    assessment = assess(conn, text=text, std_key=std_key, coverage_id=coverage_id, today=today, evidence=evidence, vectors=vectors)
    selected = assessment.listings[0] if assessment.listings else None

    standards = _standards_step(conn, _standard_ids(assessment, selected), evidence)
    family_keys = [item["family_key"] for item in standards.data.get("standards", [])]
    if selected is not None:
        family_keys += [link.family_key for link in selected.standards if link.family_key and link.role == "specified"]
    family_keys += [identifier.family_key for identifier in assessment.identifiers if identifier.family_key]
    family_keys = list(dict.fromkeys(family_keys))
    manual, parsed_sections = _manual_steps(conn, family_keys, evidence)
    labs = _labs_step(conn, family_keys, {"state": state, "district": district, "city": city}, today, evidence)
    steps = {
        "product": JourneyStep(
            "product",
            OK if selected else (ATTENTION if assessment.candidates or assessment.standards else MISSING),
            {"label": assessment.label, "candidates": assessment.candidates[:6], "synonyms_used": assessment.synonyms_used, "identifiers": assessment.identifiers},
            [selected.evidence_id] if selected else [],
        ),
        "standards": standards,
        "compulsory_status": _status_step(assessment, selected),
        "scheme": _scheme_step(conn, selected, evidence),
        "product_manual": manual,
        "tests": _tests_step(parsed_sections, labs),
        "labs": labs,
        "application": _application_step(conn, selected, evidence),
    }
    return Journey(
        query={"text": text, "std_key": std_key, "coverage_id": coverage_id, "state": state, "district": district, "city": city},
        checked_on=today,
        assessment=assessment,
        selected=selected,
        steps=list(steps.values()),
        next_actions=_next_actions(assessment, selected, steps),
        evidence=evidence,
    )
