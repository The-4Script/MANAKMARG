"""Assistant: routes a question to deterministic services and composes an evidence-cited answer in EN or HI.

Every sentence carries the evidence ids it relies on. Facts (standards, listings, dates, labs, AHCs, districts) come
from the reasoning services over official records; the templates only word them. An optional LLM narrative, when
enabled, is checked against the same evidence before it is shown (``manakmarg.llm``).
"""

from dataclasses import dataclass, field
from datetime import date

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from manakmarg.core import clock
from manakmarg.db import schema
from manakmarg.normalize.orders import extract_gsr_number, extract_so_number
from manakmarg.normalize.text import snippet
from manakmarg.reasoning.applicability import (
    CANDIDATE,
    COMPULSORY,
    DENOTIFIED,
    ENFORCEMENT_DATE_REACHED,
    NO_LISTING_FOUND,
    UPCOMING,
    Assessment,
    assess,
    load_listings,
)
from manakmarg.reasoning.evidence import EvidenceBuilder
from manakmarg.reasoning.hallmarking import AMBIGUOUS, COVERED, NOT_IN_LIST, check_district, find_ahcs
from manakmarg.reasoning.i18n import say
from manakmarg.reasoning.intents import (
    INTENT_GAP,
    INTENT_HALLMARKING,
    INTENT_LABS,
    INTENT_PROCESS,
    INTENT_TESTS,
    INTENT_UPCOMING,
    Gazetteer,
    QueryUnderstanding,
    understand,
)
from manakmarg.reasoning.journey import build_journey
from manakmarg.reasoning.labs import find_labs
from manakmarg.search import fts_search

MAX_ITEMS = 6


@dataclass(frozen=True)
class AnswerItem:
    text: str
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class AnswerSection:
    key: str
    title: str
    items: tuple[AnswerItem, ...]


@dataclass
class AssistantResponse:
    query: str
    lang: str
    understanding: QueryUnderstanding
    headline: str
    status_label: str | None
    sections: list[AnswerSection]
    caveats: list[str]
    next_actions: list[AnswerItem]
    follow_ups: list[str]
    links: list[dict]
    evidence: EvidenceBuilder
    narrative: str | None = None
    narrative_source: str = "template"
    headline_evidence: list[str] = field(default_factory=list)


class _Composer:
    def __init__(self, lang: str):
        self.lang = lang
        self.sections: list[AnswerSection] = []
        self.actions: list[AnswerItem] = []
        self.links: list[dict] = []
        self.follow_ups: list[str] = []

    def say(self, key: str, **params) -> str:
        return say(key, self.lang, **params)

    def section(self, key: str, items: list[AnswerItem]) -> None:
        if items:
            self.sections.append(AnswerSection(key, self.say(f"section.{key}"), tuple(items)))

    def action(self, key: str, *evidence_ids: str) -> None:
        self.actions.append(AnswerItem(self.say(key), tuple(evidence_ids)))

    def link(self, key: str, to: str) -> None:
        if all(existing["to"] != to for existing in self.links):
            self.links.append({"label": self.say(key), "to": to})

    def follow(self, key: str, **params) -> None:
        text = self.say(key, **params)
        if text not in self.follow_ups:
            self.follow_ups.append(text)


def _number_suffix(order) -> str:
    number = order.so_number or order.gsr_number
    if not number:
        return ""
    printed = extract_so_number(order.title) if order.so_number else extract_gsr_number(order.title)
    return "" if printed == number else f" — {number}"


def _q(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


# --------------------------------------------------------------------------- product compliance


def _product_answer(conn, understanding: QueryUnderstanding, composer: _Composer, evidence: EvidenceBuilder, today: date, vectors) -> tuple[str, str | None, list[str], list[str]]:
    std_key = understanding.standard_refs[0] if understanding.standard_refs else None
    assessment: Assessment = assess(conn, text=understanding.product_text, std_key=std_key if not understanding.product_text else None, today=today, evidence=evidence, vectors=vectors)
    if understanding.product_text and std_key:
        assessment = assess(conn, text=understanding.product_text, std_key=std_key, today=today, evidence=evidence, vectors=vectors)
    lead = assessment.listings[0] if assessment.listings else None
    headline_ids: list[str] = []
    if lead is not None:
        headline_ids.append(lead.evidence_id)
        params = {"product": lead.product_name, "scheme": lead.scheme_name or "", "date": lead.enforcement_date.isoformat() if lead.enforcement_date else "", "days": lead.days_to_enforcement}
        key = {COMPULSORY: "head.compulsory", UPCOMING: "head.upcoming", ENFORCEMENT_DATE_REACHED: "head.enforcement_reached", DENOTIFIED: "head.denotified"}.get(lead.effect, "head.verify")
        headline = composer.say(key, **params)
        if assessment.label == CANDIDATE:
            headline = composer.say("prefix.possible") + headline

        why = []
        if lead.status_basis:
            why.append(AnswerItem(composer.say("item.basis", basis=snippet(lead.status_basis, 280)), (lead.evidence_id,)))
        if assessment.basis == "standard_reference" and std_key:
            why.append(AnswerItem(composer.say("item.matched_standard", ref=std_key), (lead.evidence_id,)))
        elif lead.token_coverage is not None:
            why.append(AnswerItem(composer.say("item.matched", product=lead.product_name, coverage=round(lead.token_coverage * 100)), (lead.evidence_id,)))

        standards = []
        for link in lead.standards:
            if link.std_key:
                standards.append(AnswerItem(composer.say("item.standard", std_key=link.std_key, title=link.title or ""), tuple(filter(None, (link.evidence_id, lead.evidence_id)))))
            if link.ref_raw and link.ref_raw != link.std_key:
                standards.append(AnswerItem(composer.say("item.standard_listed_as", ref=link.ref_raw), (lead.evidence_id,)))
        orders = [
            AnswerItem(
                composer.say(
                    "item.order",
                    kind=order.kind.replace("_", " ").upper() if order.kind == "qco" else order.kind.replace("_", " ").capitalize(),
                    title=order.title,
                    number=_number_suffix(order),
                    date=f" ({order.order_date.isoformat()})" if order.order_date and order.order_date.isoformat() not in order.title else "",
                ),
                (order.evidence_id,),
            )
            for order in lead.orders[:MAX_ITEMS]
        ]
        others = [
            AnswerItem(composer.say("item.listing", product=view.product_name, effect=composer.say(f"effect.{view.effect}")), (view.evidence_id,))
            for view in assessment.listings[1:4]
        ]
        composer.section("standards", standards)
        composer.section("why", why)
        composer.section("orders", orders)
        composer.section("other_listings", others)

        subject = std_key or lead.product_name
        composer.link("link.journey", f"/journey?coverage_id={lead.coverage_id}")
        family = next((link.family_key for link in lead.standards if link.family_key), None)
        if family:
            composer.link("link.labs", f"/labs?ref={_q(family)}")
        if assessment.label in ("LIKELY_APPLICABLE", "CANDIDATE"):
            composer.action("action.confirm", lead.evidence_id)
        if lead.effect not in (COMPULSORY, UPCOMING):
            composer.action("action.verify", lead.evidence_id)
        composer.action("action.journey")
        if lead.effect in (COMPULSORY, UPCOMING):
            composer.action("action.labs")
            composer.action("action.apply")
        composer.follow("follow.tests", subject=subject)
        composer.follow("follow.labs", subject=family or subject)
        composer.follow("follow.apply")
    else:
        identified = next((identifier for identifier in assessment.identifiers if identifier.standard_ids), None)
        if identified is not None:
            headline = composer.say("head.standard_no_listing", std_key=identified.std_key or identified.ref_raw)
            composer.link("link.standard", f"/standards?key={_q(identified.std_key or identified.ref_raw)}")
        else:
            headline = composer.say("head.no_listing", text=understanding.product_text or understanding.text)
        standards = []
        for candidate in assessment.standards[:3]:
            row = conn.execute(sa.select(schema.standard).where(schema.standard.c.standard_id == candidate.standard_id)).mappings().first()
            if row is not None:
                evidence_id = evidence.add_record("standard", row, record_id=row["std_key"], title=f"{row['std_key']} — {candidate.title}", snippet=candidate.title)
                standards.append(AnswerItem(composer.say("item.standard", std_key=candidate.std_key, title=candidate.title), (evidence_id,)))
        composer.section("standards", standards)
        composer.follow("follow.upcoming")
    return headline, assessment.label, assessment.caveats, headline_ids


# --------------------------------------------------------------------------- hallmarking


def _hallmarking_answer(conn, understanding: QueryUnderstanding, composer: _Composer, evidence: EvidenceBuilder, today: date) -> tuple[str, str | None, list[str], list[str]]:
    headline_ids: list[str] = []
    status = None
    caveats: list[str] = []
    district, state = understanding.district, understanding.state
    if district:
        check = check_district(conn, district, state, evidence=evidence)
        status = check.status
        if check.status == AMBIGUOUS:
            headline = composer.say("head.hm_ambiguous", district=district, states=", ".join(sorted({match.state for match in check.matches})))
        elif check.status == NOT_IN_LIST:
            headline = composer.say("head.hm_not_listed", district=district)
            caveats.append("absence_not_proof")
        else:
            match = check.matches[0]
            headline_ids = list(match.evidence_ids)
            state = match.state
            if check.status == COVERED:
                headline = composer.say("head.hm_covered", district=match.district, state=match.state, phase=match.phase_no, order=match.phase_order_date_raw or "")
            else:
                headline = composer.say("head.hm_verify", district=match.district, state=match.state, note=match.gazette_note or "")
            composer.section("district", [AnswerItem(composer.say("item.hm_gazette", note=match.gazette_note), match.evidence_ids)] if match.gazette_note else [])
        composer.link("link.hallmarking", f"/hallmarking?district={_q(district)}" + (f"&state={_q(state)}" if state else ""))
    elif state:
        table = schema.hallmarking_district
        rows = conn.execute(
            sa.select(table).where(table.c.is_current.is_(True), table.c.state == state).order_by(table.c.phase_no.nulls_last(), table.c.district)
        ).mappings().all()
        if rows:
            headline_ids = [
                evidence.add_record(
                    "hallmarking_district",
                    row,
                    record_id=row["district_id"],
                    title=f"{row['district']}, {row['state']}",
                    snippet=f"{row['phase_label'] or ''} {row['phase_order_date_raw'] or ''}".strip() or row["gazette_note"],
                )
                for row in rows
            ]
            names = ", ".join(row["district"] for row in rows[:15]) + ("…" if len(rows) > 15 else "")
            headline = composer.say("head.hm_state", count=len(rows), state=state, names=names)
            verify = [row for row in rows if row["gazette_validated"] is False or row["phase_no"] is None]
            composer.section("district", [AnswerItem(composer.say("item.hm_gazette", note=f"{row['district']}: {row['gazette_note']}"), (headline_ids[rows.index(row)],)) for row in verify])
        else:
            headline = composer.say("head.hm_state_none", state=state)
            caveats.append("absence_not_proof")
        composer.link("link.hallmarking", f"/hallmarking?state={_q(state)}")
    else:
        headline = composer.say("head.hm_general")

    if district or state:
        result = find_ahcs(conn, state=state, district=district if status not in (None, NOT_IN_LIST) else None, metal=understanding.metal, include_inactive=True, today=today, evidence=evidence)
        inactive = sum(count for key, count in result.counts.items() if key != "OPERATIVE")
        place = ", ".join(filter(None, (district, state)))
        items = [AnswerItem(composer.say("item.ahc_count", operative=len(result.operative), inactive=inactive, place=place))]
        items += [
            AnswerItem(composer.say("item.ahc", name=view.name, recognition_no=view.recognition_no, validity=view.validity_date.isoformat() if view.validity_date else "—"), view.evidence_ids)
            for view in result.operative[:MAX_ITEMS]
        ]
        composer.section("ahcs", items)
        if result.operative:
            composer.action("action.ahcs", *result.operative[0].evidence_ids[:1])
        composer.follow("follow.ahcs", place=district or state)
    for recognition_no in understanding.recognition_nos:
        row = conn.execute(sa.select(schema.ahc).where(schema.ahc.c.recognition_no == recognition_no)).mappings().first()
        if row is None:
            continue
        result = find_ahcs(conn, state=row["state"], include_inactive=True, today=today, evidence=evidence)
        view = next((item for item in result.operative + result.inactive if item.recognition_no == recognition_no), None)
        if view is not None:
            composer.section("ahcs", [AnswerItem(composer.say("item.ahc_status", name=view.name, recognition_no=view.recognition_no, status=view.effective_status, reason=" ".join(view.reasons)), view.evidence_ids)])
    _faq_section(conn, understanding.text, composer, evidence, categories=("hallmarking_general", "hallmarking_mandatory"))
    composer.section("district" if not district else "faq", [])
    jewellers_item = AnswerItem(composer.say("item.jewellers"))
    composer.sections.append(AnswerSection("jewellers", composer.say("section.jewellers"), (jewellers_item,)))
    composer.follow("follow.huid")
    return headline, status, caveats, headline_ids


# --------------------------------------------------------------------------- labs, upcoming, process, FAQ


def _labs_answer(conn, understanding: QueryUnderstanding, composer: _Composer, evidence: EvidenceBuilder, today: date, vectors) -> tuple[str, str | None, list[str], list[str]]:
    refs = " ".join(understanding.standard_refs)
    if not refs and understanding.product_text:
        assessment = assess(conn, text=understanding.product_text, today=today, evidence=evidence, vectors=vectors)
        families = [link.family_key for view in assessment.listings[:1] for link in view.standards if link.family_key]
        refs = " ".join(families)
    if not refs:
        return composer.say("head.labs_need_standard"), None, [], []
    result = find_labs(conn, refs, state=understanding.state, district=understanding.district, city=understanding.city, include_inactive=False, today=today, evidence=evidence)
    place = f" ({', '.join(filter(None, (understanding.city or understanding.district, understanding.state)))})" if (understanding.city or understanding.district or understanding.state) else ""
    shown_refs = ", ".join(result.designations) or refs
    composer.link("link.labs", f"/labs?ref={_q(refs)}" + (f"&city={_q(understanding.city)}" if understanding.city else "") + (f"&state={_q(understanding.state)}" if understanding.state else ""))
    if not result.matches:
        key = "head.labs_not_indexed" if "scope_not_indexed" in result.notes else "head.labs_none"
        composer.action("action.lims")
        return composer.say(key, refs=shown_refs), None, [], []
    items = [
        AnswerItem(
            composer.say(
                "item.lab",
                name=match.lab_name,
                place=", ".join(filter(None, (match.city, match.state))) or "—",
                ref=match.is_ref_raw,
                status=match.status,
                charges=f" · ₹{match.charges_total:,.0f}" if match.charges_total else "",
            ),
            match.evidence_ids,
        )
        for match in result.matches[:MAX_ITEMS]
    ]
    if result.location_fallback:
        items.insert(0, AnswerItem(composer.say("item.labs_fallback")))
    composer.section("labs", items)
    composer.follow("follow.apply")
    return composer.say("head.labs", count=result.counts.get("rows", len(result.matches)), refs=shown_refs, place=place), None, [], []


def _upcoming_answer(conn, composer: _Composer, evidence: EvidenceBuilder, today: date) -> tuple[str, str | None, list[str], list[str]]:
    table = schema.scheme_coverage
    ids = [
        row.coverage_id
        for row in conn.execute(
            sa.select(table.c.coverage_id)
            .where(table.c.is_current.is_(True), table.c.page_kind == "upcoming_qco", table.c.parent_coverage_id.is_(None), table.c.enforcement_date > today)
            .order_by(table.c.enforcement_date)
        )
    ]
    listings = load_listings(conn, ids, evidence, today)
    items = [
        AnswerItem(
            composer.say("item.upcoming", product=view.product_name, refs=", ".join(link.ref_raw for link in view.standards) or "—", date=view.enforcement_date.isoformat() if view.enforcement_date else "—", days=view.days_to_enforcement),
            (view.evidence_id,),
        )
        for view in listings[: MAX_ITEMS + 2]
    ]
    composer.section("upcoming", items)
    composer.link("link.upcoming", "/certification?tab=UPCOMING")
    return composer.say("head.upcoming_list", count=len(listings), today=today.isoformat()), None, ["listing_snapshot"], []


def _process_answer(conn, composer: _Composer, evidence: EvidenceBuilder) -> tuple[str, str | None, list[str], list[str]]:
    rows = conn.execute(sa.select(schema.process_step).where(schema.process_step.c.is_current.is_(True)).order_by(schema.process_step.c.ordinal)).mappings().all()
    items = []
    for row in rows:
        evidence_id = evidence.add_record("process_step", row, record_id=row["step_id"], title=f"Apply for licence — step {row['step_label']}", snippet=row["text"])
        items.append(AnswerItem(composer.say("item.step", label=row["step_label"], text=row["text"]), (evidence_id,)))
    composer.section("process", items)
    return composer.say("head.process"), None, [], []


def _faq_section(conn, text: str, composer: _Composer, evidence: EvidenceBuilder, *, categories: tuple[str, ...] | None = None, limit: int = 3) -> int:
    hits = fts_search.search_faq(conn, text, limit=10)
    if not hits:
        return 0
    table = schema.faq
    rows = {row["faq_id"]: row for row in conn.execute(sa.select(table).where(table.c.faq_id.in_([hit.id for hit in hits]))).mappings()}
    items = []
    for hit in hits:
        row = rows.get(hit.id)
        if row is None or (categories and row["category"] not in categories):
            continue
        evidence_id = evidence.add_record("faq", row, record_id=row["faq_id"], title=row["question"], snippet=row["answer"], url=row["source_url"])
        items.append(AnswerItem(composer.say("item.faq", question=row["question"], answer=snippet(row["answer"], 260)), (evidence_id,)))
        if len(items) >= limit:
            break
    composer.section("faq", items)
    return len(items)


def _documents_section(conn, text: str, composer: _Composer, evidence: EvidenceBuilder, limit: int = 2) -> int:
    hits = fts_search.search_chunks(conn, text, limit=limit)
    items = []
    for hit in hits:
        row = conn.execute(
            sa.select(schema.document_chunk, schema.document.c.url, schema.document.c.title.label("doc_title"), schema.document.c.source_id, schema.document.c.retrieved_at)
            .select_from(schema.document_chunk.join(schema.document, schema.document.c.document_id == schema.document_chunk.c.document_id))
            .where(schema.document_chunk.c.chunk_id == hit.id)
        ).mappings().first()
        if row is None:
            continue
        evidence_id = evidence.add(kind="document_chunk", record_id=row["chunk_id"], title=row["doc_title"] or row["url"], source_id=row["source_id"], snippet=row["text"], url=row["url"], retrieved_at=row["retrieved_at"], page=row["page_start"])
        items.append(AnswerItem(snippet(hit.snippet or row["text"], 260), (evidence_id,)))
    composer.section("documents", items)
    return len(items)


# --------------------------------------------------------------------------- entry point


def answer(
    conn: Connection,
    query: str,
    *,
    lang: str = "en",
    today: date | None = None,
    vectors=None,
    gazetteer: Gazetteer | None = None,
) -> AssistantResponse:
    today = today or clock.today()
    lang = lang if lang in ("en", "hi") else "en"
    understanding = understand(query, gazetteer=gazetteer or Gazetteer.load(conn))
    evidence = EvidenceBuilder(conn)
    composer = _Composer(lang)
    intent = understanding.intent

    if intent == INTENT_GAP:
        headline, status, caveats, headline_ids = composer.say("head.gap"), None, [], []
        composer.link("link.gap", "/gap-analysis")
    elif intent == INTENT_HALLMARKING or understanding.recognition_nos:
        headline, status, caveats, headline_ids = _hallmarking_answer(conn, understanding, composer, evidence, today)
    elif intent == INTENT_LABS:
        headline, status, caveats, headline_ids = _labs_answer(conn, understanding, composer, evidence, today, vectors)
    elif intent == INTENT_UPCOMING:
        headline, status, caveats, headline_ids = _upcoming_answer(conn, composer, evidence, today)
    elif intent == INTENT_PROCESS and not (understanding.product_text or understanding.standard_refs):
        headline, status, caveats, headline_ids = _process_answer(conn, composer, evidence)
    elif understanding.product_text or understanding.standard_refs:
        headline, status, caveats, headline_ids = _product_answer(conn, understanding, composer, evidence, today, vectors)
        if intent == INTENT_TESTS:
            journey = build_journey(conn, text=understanding.product_text, std_key=understanding.standard_refs[0] if understanding.standard_refs else None, today=today, vectors=vectors)
            tests = next((step for step in journey.steps if step.key == "tests"), None)
            if tests and tests.data.get("sit_rows"):
                section_id = evidence.add(kind="guideline_section", record_id=f"sit:{tests.data['manual_url']}", title=tests.data["manual_title"], source_id="bis_product_manual_documents", url=tests.data["manual_url"], page=tests.data.get("sit_page"))
                composer.sections.insert(0, AnswerSection("tests", composer.say("section.tests"), tuple(AnswerItem(composer.say("item.sit", requirement=row["requirement"], clause=row["clause"], frequency=row["frequency"] or "—"), (section_id,)) for row in tests.data["sit_rows"][:8])))
        if intent == INTENT_PROCESS:
            _process_answer(conn, composer, evidence)
    else:
        found = 0
        if understanding.in_scope:
            found = _faq_section(conn, query, composer, evidence) + _documents_section(conn, query, composer, evidence)
        if not understanding.in_scope:
            headline, status, caveats, headline_ids = composer.say("head.out_of_scope"), None, [], []
        else:
            headline, status, caveats, headline_ids = (composer.say("head.faq") if found else composer.say("head.nothing")), None, [], []
        if not found:
            composer.follow("follow.upcoming")

    return AssistantResponse(
        query=query,
        lang=lang,
        understanding=understanding,
        headline=headline,
        status_label=status,
        sections=composer.sections,
        caveats=list(dict.fromkeys(caveats)),
        next_actions=composer.actions,
        follow_ups=composer.follow_ups[:4],
        links=composer.links,
        evidence=evidence,
        headline_evidence=headline_ids,
    )
