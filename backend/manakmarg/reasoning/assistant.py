"""Assistant: routes a question to deterministic services and composes an evidence-cited answer in EN or HI.

Every sentence carries the evidence ids it relies on. Facts (standards, listings, dates, labs, AHCs, districts) come
from the reasoning services over official records; the templates only word them. The route
(``manakmarg.reasoning.routing``) decides which records are consulted and is returned with the answer. An optional
LLM narrative, when enabled, is checked against the same evidence before it is shown (``manakmarg.llm``).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from manakmarg.core import clock
from manakmarg.db import schema
from manakmarg.normalize.language import LANGUAGES, detect_language
from manakmarg.normalize.orders import extract_gsr_number, extract_so_number
from manakmarg.normalize.text import norm_match, snippet
from manakmarg.reasoning.applicability import (
    CANDIDATE,
    COMPULSORY,
    DENOTIFIED,
    ENFORCEMENT_DATE_REACHED,
    UNKNOWN,
    UPCOMING,
    Assessment,
    assess,
    load_listings,
)
from manakmarg.reasoning.evidence import EvidenceBuilder
from manakmarg.reasoning.interpret import interpret
from manakmarg.reasoning.localize import to_hindi
from manakmarg.reasoning.hallmarking import AMBIGUOUS, COVERED, NOT_IN_LIST, check_district, find_ahcs
from manakmarg.reasoning.i18n import say
from manakmarg.reasoning.intents import (
    INTENT_LABS,
    INTENT_PROCESS,
    INTENT_STATUS,
    INTENT_STANDARD,
    INTENT_TESTS,
    QUESTION_WORDS,
    Gazetteer,
    QueryUnderstanding,
    understand,
    apply_model_hints,
    suggest_place,
)
from manakmarg.core.config import Settings, get_settings
from manakmarg.reasoning import groq
from manakmarg.reasoning.journey import build_journey
from manakmarg.reasoning.labs import find_labs
from manakmarg.reasoning.routing import (
    ROUTE_AHC,
    ROUTE_CERTIFICATION,
    ROUTE_GAP,
    ROUTE_GENERAL,
    ROUTE_HALLMARKING,
    ROUTE_INVALID_IDENTIFIER,
    ROUTE_LAB,
    ROUTE_OUT_OF_SCOPE,
    ROUTE_PRODUCT,
    ROUTE_QCO,
    ROUTE_UNKNOWN_LOCATION,
    ROUTE_HSN,
    ROUTE_UPCOMING,
    SCHEME_ROUTES,
    Route,
    route_query,
)
from manakmarg.search import fts_search
from manakmarg.search.catalogue import TIER_KIND_OF, TIER_SUBJECT, search_product, short_subject, subject_tier
from manakmarg.search.hsn import code_in_text, query_words, search_hsn
from manakmarg.search.hybrid import content_tokens
from manakmarg.search.resolvers import StandardResolver

MAX_ITEMS = 6
_STATUS_EFFECT = {"LISTED_COMPULSORY": "COMPULSORY", "DENOTIFIED": "DENOTIFIED", "RESCINDED": "RESCINDED", "NEEDS_VERIFICATION": "NEEDS_VERIFICATION", "UPCOMING": "UPCOMING"}
_SCHEME_SHORT = {"SCHEME_I": "Scheme I", "SCHEME_II": "Scheme II", "SCHEME_IV": "Scheme IV", "SCHEME_X": "Scheme X"}
OVERVIEW_SOURCE = "bis_compulsory_overview_page"


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
    route: Route | None = None


_SOURCE_MARK = re.compile(r"\ue000(\d+)\ue001")


class _Composer:
    def __init__(self, lang: str):
        self.lang = lang
        self.sections: list[AnswerSection] = []
        self.actions: list[AnswerItem] = []
        self.links: list[dict] = []
        self.follow_ups: list[str] = []
        self.sources: list[str] = []

    def src(self, text: str | None) -> str:
        """An official English passage placed in the answer. In a Hindi answer it becomes a placeholder, replaced by a
        checked Hindi translation (or the English original) once the whole answer is composed (``localized``)."""
        text = text or ""
        if self.lang != "hi" or not text:
            return text
        self.sources.append(text)
        return f"\ue000{len(self.sources) - 1}\ue001"

    def localized(self, settings: Settings) -> tuple[Callable[[str], str], bool]:
        """A function that fills every placeholder in a text, and whether any translation is shown."""
        translated = to_hindi(self.sources, settings) if self.sources else {}

        def fill(text: str) -> str:
            return _SOURCE_MARK.sub(lambda match: translated.get(self.sources[int(match.group(1))], self.sources[int(match.group(1))]), text)

        return fill, bool(translated)

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


def _lab_items(result, composer: _Composer) -> list[AnswerItem]:
    return [
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


def _product_answer(conn, understanding: QueryUnderstanding, composer: _Composer, evidence: EvidenceBuilder, today: date, vectors) -> tuple[str, str | None, list[str], list[str]]:
    std_key = understanding.standard_refs[0] if understanding.standard_refs else None
    entities = {"material": understanding.material, "product": understanding.product}
    assessment: Assessment = assess(conn, text=understanding.product_text, std_key=std_key if not understanding.product_text else None, today=today, evidence=evidence, vectors=vectors, **entities)
    if understanding.product_text and std_key:
        assessment = assess(conn, text=understanding.product_text, std_key=std_key, today=today, evidence=evidence, vectors=vectors, **entities)
    lead = assessment.listings[0] if assessment.listings else None
    # "Which standard / what is the IS for X" (and "is it compulsory" when no listing is about X itself): answer from the
    # whole published catalogue unless a compulsory listing is about the product itself — then that listing, with its
    # legal status, stays the answer. A listing only mentioning the product ("Square Tins … for Ghee") is not.
    if understanding.product_text and not std_key and (lead is None or {INTENT_STANDARD, INTENT_STATUS} & set(understanding.intents)):
        tier = subject_tier(understanding.product_text, lead.product_name) if lead is not None else None
        about_product = lead is not None and _listing_is_about_product(assessment, lead, tier)
        strong_listing = about_product and lead.effect in (COMPULSORY, UPCOMING, ENFORCEMENT_DATE_REACHED)
        if not strong_listing:
            catalogue, matched = search_product(conn, understanding.product_text, limit=5)
            if any(match.specification and match.tier <= TIER_KIND_OF for match in catalogue) or (catalogue and INTENT_STANDARD in understanding.intents):
                return _catalogue_answer(conn, understanding, assessment, catalogue, composer, evidence, matched or understanding.product_text)
            if lead is not None and tier is None and (lead.token_coverage or 0) < 1.0:
                # Nothing in the catalogue, and the listing shares only some words ("Oil pressure stove" for "groundnut
                # oil"): do not present it as the answer.
                lead = None
                assessment = replace(assessment, listings=[], label=UNKNOWN)
    headline_ids: list[str] = []
    if lead is not None:
        headline_ids.append(lead.evidence_id)
        params = {"product": lead.product_name, "scheme": lead.scheme_name or "", "date": lead.enforcement_date.isoformat() if lead.enforcement_date else "", "days": lead.days_to_enforcement}
        key = {COMPULSORY: "head.compulsory", UPCOMING: "head.upcoming", ENFORCEMENT_DATE_REACHED: "head.enforcement_reached", DENOTIFIED: "head.denotified"}.get(lead.effect, "head.verify")
        headline = composer.say(key, **params)
        full_matches = {view.product_name.lower() for view in assessment.listings if view.token_coverage is not None and view.token_coverage >= 1.0}
        if assessment.label == CANDIDATE and not std_key and understanding.product_text and len(understanding.product_text.split()) == 1 and len(full_matches) >= 4:
            # A single broad word ("steel") fully matches many listings; do not single one out as the likely answer.
            headline = composer.say("head.broad_product", text=understanding.product_text)
        elif assessment.label == CANDIDATE:
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
        order_items = [
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
            for order in lead.orders
        ]
        # Two records of one order (the same notification published at two URLs) read identically: show it once, citing both.
        merged: dict[str, tuple[str, ...]] = {}
        for item in order_items:
            merged[item.text] = tuple(dict.fromkeys(merged.get(item.text, ()) + tuple(item.evidence_ids)))
        orders = [AnswerItem(text, ids) for text, ids in list(merged.items())[:MAX_ITEMS]]
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
            if INTENT_LABS in understanding.intents:
                result = find_labs(conn, family, state=understanding.state, district=understanding.district, city=understanding.city, include_inactive=False, today=today, evidence=evidence)
                composer.section("labs", _lab_items(result, composer))
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
        # Without a listing, a published standard is shown only when its title contains every product word; weaker
        # full-text neighbours are not presented as related to the product.
        wanted = set(content_tokens(understanding.product_text)) if understanding.product_text else set()
        standards = []
        for candidate in assessment.standards:
            if identified is None and (not wanted or not wanted <= set(content_tokens(candidate.title))):
                continue
            row = conn.execute(sa.select(schema.standard).where(schema.standard.c.standard_id == candidate.standard_id)).mappings().first()
            if row is not None:
                evidence_id = evidence.add_record("standard", row, record_id=row["std_key"], title=f"{row['std_key']} — {candidate.title}", snippet=candidate.title)
                standards.append(AnswerItem(composer.say("item.standard", std_key=candidate.std_key, title=candidate.title), (evidence_id,)))
            if len(standards) >= 3:
                break
        composer.section("standards" if identified is not None else "related_standards", standards)
        composer.follow("follow.upcoming")
    caveats = list(assessment.caveats) + _related_hsn_section(conn, understanding, composer, evidence)
    return headline, assessment.label, caveats, headline_ids


def _listing_is_about_product(assessment: Assessment, lead, tier: int | None) -> bool:
    """A listing whose name has the product as its subject ("Domestic Pressure Cooker"), or that matched every product
    word through a curated synonym ("solar panels" → "Photovoltaic modules"). A listing naming the product only in a
    purpose ("Square Tins … for Ghee") is about something else."""
    if tier is not None:
        return tier <= TIER_KIND_OF
    return bool(assessment.synonyms_used) and (lead.token_coverage or 0) >= 1.0


def _catalogue_answer(conn, understanding: QueryUnderstanding, assessment: Assessment, catalogue, composer: _Composer, evidence: EvidenceBuilder, product: str) -> tuple[str, str | None, list[str], list[str]]:
    items, headline_ids = [], []
    for match in catalogue:
        row = conn.execute(sa.select(schema.standard).where(schema.standard.c.standard_id == match.standard_id)).mappings().first()
        if row is None:
            continue
        evidence_id = evidence.add_record("standard", row, record_id=row["std_key"], title=f"{row['std_key']} — {match.title}", snippet=match.title)
        items.append(AnswerItem(composer.say("item.standard", std_key=match.std_key, title=match.title), (evidence_id,)))
        headline_ids = headline_ids or [evidence_id]
    direct = [match for match in catalogue if match.specification and match.tier <= TIER_KIND_OF]
    # Without a standard that *is* the product, a specification whose subject includes it ("Cashew kernels") answers.
    direct = direct or [match for match in catalogue if match.specification and match.tier <= TIER_SUBJECT]
    # Several standards can each be "for" the product (packaged pasteurized milk, flavoured milk, UHT milk): name them.
    listed = ", ".join(f"{match.std_key} ({short_subject(match.title, product)})" for match in (direct or catalogue)[:3])
    lead = assessment.listings[0] if assessment.listings else None
    about_product = lead is not None and _listing_is_about_product(assessment, lead, subject_tier(product, lead.product_name))
    if INTENT_STATUS in understanding.intents and INTENT_STANDARD not in understanding.intents:
        # "Is BIS mandatory for X?": the status leads (no listing is about X itself, or its listing is no longer in force).
        key = "head.catalogue_status_listing" if about_product else "head.catalogue_status_none"
        headline = composer.say(key, product=product, standards=listed, listing=lead.product_name if lead else "", effect=composer.say(f"effect.{lead.effect}") if lead else "")
    elif len(direct) == 1:
        headline = composer.say("head.catalogue_standard", product=product, std_key=direct[0].std_key, title=direct[0].title)
    elif direct:
        headline = composer.say("head.catalogue_standards", product=product, standards=listed)
    else:
        headline = composer.say("head.catalogue_related", product=product)
    composer.section("catalogue_standards", items)
    caveats: list[str] = []
    if lead is not None:
        effect = composer.say(f"effect.{lead.effect}")
        key = "item.catalogue_listing_status" if about_product else "item.catalogue_related_listing"
        composer.section("compulsory_status", [AnswerItem(composer.say(key, product=product, listing=lead.product_name, effect=effect), (lead.evidence_id,))])
        if not about_product:
            caveats.append("absence_not_proof")
    else:
        composer.section("compulsory_status", [AnswerItem(composer.say("item.catalogue_no_listing", product=product))])
        caveats.append("absence_not_proof")
    top = direct[0] if direct else catalogue[0]
    composer.link("link.standard", f"/standards?key={_q(top.std_key)}")
    composer.follow("follow.labs", subject=top.family_key or top.std_key)
    caveats += _related_hsn_section(conn, understanding, composer, evidence)
    return headline, None, caveats, headline_ids


# --------------------------------------------------------------------------- HSN (classification lookup, never a BIS fact)


def _hsn_items(matches, composer: _Composer, evidence: EvidenceBuilder) -> list[AnswerItem]:
    items = []
    for match in matches:
        evidence_id = evidence.add(
            kind="hsn_code",
            record_id=match.code,
            title=f"HSN {match.code}",
            source_id=match.source_id,
            snippet=match.description,
            locator=match.source_locator,
            retrieved_at=match.retrieved_at,
        )
        heading = match.parents[-1] if match.parents else None
        text = composer.say("item.hsn", code=match.code, description=match.description)
        if heading:
            text = composer.say("item.hsn_under", item=text, code=heading["code"], description=heading["description"])
        items.append(AnswerItem(text, (evidence_id,)))
    return items


def _related_hsn_section(conn, understanding: QueryUnderstanding, composer: _Composer, evidence: EvidenceBuilder) -> list[str]:
    """A separate, clearly labelled HSN block for product questions. Shown only when a code's official description
    contains every product word; it never changes the BIS headline, status or caveats about compulsory status."""
    words = query_words(understanding.product_text)
    if not words:
        return []
    result = search_hsn(conn, words, limit=3)
    matches = [match for match in result.matches if match.coverage >= 1.0]
    if not matches:
        return []
    composer.section("hsn_related", _hsn_items(matches, composer, evidence))
    return ["hsn_not_definitive"]


def _hsn_answer(conn, understanding: QueryUnderstanding, composer: _Composer, evidence: EvidenceBuilder) -> tuple[str, str | None, list[str], list[str]]:
    text = understanding.normalized_text or understanding.text
    words = query_words(understanding.product_text)
    code = code_in_text(text)
    lookup = code if code and not words else (words or text)
    result = search_hsn(conn, lookup, limit=6)
    if result.mode == "invalid":
        return composer.say("head.hsn_invalid", text=lookup), None, ["hsn_not_definitive"], []
    if not result.matches:
        return composer.say("head.hsn_none", text=lookup), None, ["hsn_not_definitive"], []
    composer.section("hsn", _hsn_items(result.matches, composer, evidence))
    return composer.say("head.hsn_matches", count=len(result.matches), text=lookup), None, ["hsn_not_definitive"], []


# --------------------------------------------------------------------------- hallmarking


def _metal_answer(conn, understanding: QueryUnderstanding, composer: _Composer, evidence: EvidenceBuilder) -> tuple[str, list[str]]:
    table = schema.hallmarking_district
    rows = conn.execute(sa.select(table).where(table.c.is_current.is_(True)).order_by(table.c.district_id)).mappings().all()
    notified = [row for row in rows if row["phase_no"] is not None]
    headline_ids = []
    for row in {row["source_id"]: row for row in rows}.values():
        headline_ids.append(
            evidence.add_record("hallmarking_district", row, record_id=row["district_id"], title=f"{row['district']}, {row['state']}", snippet=row["phase_label"] or row["gazette_note"])
        )
    key = "head.hm_metal_silver" if understanding.metal == "silver" else "head.hm_metal_gold"
    return composer.say(key, count=len(notified)), headline_ids


def _hallmarking_answer(conn, understanding: QueryUnderstanding, composer: _Composer, evidence: EvidenceBuilder, today: date) -> tuple[str, str | None, list[str], list[str]]:
    headline_ids: list[str] = []
    status = None
    caveats: list[str] = []
    state = understanding.state
    district = understanding.district or (understanding.unresolved_place if not state else None)
    faq_text = understanding.text
    if district:
        check = check_district(conn, district, state, evidence=evidence)
        status = check.status
        if check.status == AMBIGUOUS:
            headline = composer.say("head.hm_ambiguous", district=district, states=", ".join(sorted({match.state for match in check.matches})))
        elif check.status == NOT_IN_LIST:
            headline = composer.say("head.hm_not_listed", district=district)
            caveats.append("absence_not_proof")
            if understanding.unresolved_place:
                caveats.append("location_not_recognised")
            composer.section("suggestions", [AnswerItem(composer.say("item.suggestion", district=item.get("district"), state=item.get("state"))) for item in check.suggestions[:5]])
            if not check.suggestions:
                _place_suggestion(understanding, composer)
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
    elif understanding.metal and INTENT_STATUS in understanding.intents:
        headline, headline_ids = _metal_answer(conn, understanding, composer, evidence)
        faq_text = f"{understanding.metal} hallmarking"
        composer.link("link.hallmarking", "/hallmarking")
    else:
        headline = composer.say("head.hm_general")

    if (district and status != NOT_IN_LIST) or state:
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
    _faq_section(conn, faq_text, composer, evidence, categories=("hallmarking_general", "hallmarking_mandatory"))
    jewellers_item = AnswerItem(composer.say("item.jewellers"))
    composer.sections.append(AnswerSection("jewellers", composer.say("section.jewellers"), (jewellers_item,)))
    composer.follow("follow.huid")
    return headline, status, caveats, headline_ids


# --------------------------------------------------------------------------- labs, upcoming, process, schemes, FAQ


def _labs_answer(conn, understanding: QueryUnderstanding, composer: _Composer, evidence: EvidenceBuilder, today: date, vectors) -> tuple[str, str | None, list[str], list[str]]:
    refs = " ".join(understanding.standard_refs)
    if not refs and understanding.product_text:
        assessment = assess(conn, text=understanding.product_text, today=today, evidence=evidence, vectors=vectors)
        families = [link.family_key for view in assessment.listings[:1] for link in view.standards if link.family_key]
        refs = " ".join(families)
    if not refs:
        return composer.say("head.labs_need_standard"), None, [], []
    has_place = bool(understanding.city or understanding.district or understanding.state)
    unknown_place = understanding.unresolved_place if not has_place else None
    result = find_labs(conn, refs, state=understanding.state, district=understanding.district, city=understanding.city, include_inactive=False, today=today, evidence=evidence)
    place = f" ({', '.join(filter(None, (understanding.city or understanding.district, understanding.state)))})" if has_place else ""
    shown_refs = ", ".join(result.designations) or refs
    composer.link("link.labs", f"/labs?ref={_q(refs)}" + (f"&city={_q(understanding.city)}" if understanding.city else "") + (f"&state={_q(understanding.state)}" if understanding.state else ""))
    caveats = ["location_not_recognised"] if unknown_place else []
    if not result.matches:
        key = "head.labs_not_indexed" if "scope_not_indexed" in result.notes else "head.labs_none"
        composer.action("action.lims")
        return composer.say(key, refs=shown_refs), None, caveats, []
    items = _lab_items(result, composer)
    if result.location_fallback:
        items.insert(0, AnswerItem(composer.say("item.labs_fallback")))
    if unknown_place:
        items.insert(0, AnswerItem(composer.say("item.labs_place_unknown", place=unknown_place)))
    composer.section("labs", items)
    if unknown_place:
        _place_suggestion(understanding, composer)
    composer.follow("follow.apply")
    count = result.counts.get("rows", len(result.matches))
    if unknown_place:
        return composer.say("head.labs_place_unknown", place=unknown_place, count=count, refs=shown_refs), None, caveats, []
    return composer.say("head.labs", count=count, refs=shown_refs, place=place), None, caveats, []


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


# A process question about one of these asks something the official FAQs answer directly (the fee, the timeline, the
# validity or renewal of a licence), so that answer leads and the generic application steps follow.
_PROCESS_FAQ_TOPICS = frozenset("fee fees cost charge charges timeline time long days din validity valid renew renewal documents शुल्क फीस".split())
# How the question words map to the wording of the official FAQs ("how long" → "timeline", "kitna"/"cost" → "fee").
_PROCESS_FAQ_TERMS = {"long": "timeline", "days": "timeline", "din": "timeline", "renew": "renewal", "cost": "fee", "charges": "fee", "charge": "fee", "kitna": "fee", "kitni": "fee", "फीस": "fee", "शुल्क": "fee"}
_PROCESS_FAQ_NOISE = frozenset("much take takes taken get getting kitne".split())


def _process_answer(conn, composer: _Composer, evidence: EvidenceBuilder, query: str | None = None) -> tuple[str, str | None, list[str], list[str]]:
    # Only the content words go to the FAQ search: "how much" would otherwise pull in unrelated "how much ..." FAQs.
    tokens = norm_match(query).split() if query else []
    topics = [word for word in tokens if word in _PROCESS_FAQ_TOPICS or word in _PROCESS_FAQ_TERMS]
    words = [word for word in tokens if word not in fts_search.GENERAL_STOP_WORDS and word not in QUESTION_WORDS and word not in _PROCESS_FAQ_NOISE]
    faq_text = " ".join(dict.fromkeys(_PROCESS_FAQ_TERMS.get(word, word) for word in topics + words)).replace("license", "licence")
    if topics and _faq_section(conn, faq_text, composer, evidence, limit=2):
        headline = composer.say("head.faq")
    else:
        headline = composer.say("head.process")
    rows = conn.execute(sa.select(schema.process_step).where(schema.process_step.c.is_current.is_(True)).order_by(schema.process_step.c.ordinal)).mappings().all()
    items = []
    for row in rows:
        evidence_id = evidence.add_record("process_step", row, record_id=row["step_id"], title=f"Apply for licence — step {row['step_label']}", snippet=row["text"])
        items.append(AnswerItem(composer.say("item.step", label=row["step_label"], text=composer.src(row["text"])), (evidence_id,)))
    composer.section("process", items)
    return headline, None, [], []


def _scheme_answer(conn, scheme_id: str, composer: _Composer, evidence: EvidenceBuilder) -> tuple[str, str | None, list[str], list[str]]:
    composer.link("link.certification", f"/certification?tab={scheme_id}")
    table = schema.certification_scheme
    row = conn.execute(sa.select(table).where(table.c.scheme_id == scheme_id)).mappings().first()
    if row is None:
        return composer.say("head.scheme_not_indexed", scheme=_SCHEME_SHORT[scheme_id]), None, [], []
    scheme_evidence = evidence.add_record("certification_scheme", row, record_id=scheme_id, title=row["name"], snippet=row["official_description"] or row["name"], url=row["official_url"])
    coverage = schema.scheme_coverage
    counts = conn.execute(
        sa.select(coverage.c.listing_status, sa.func.count())
        .where(coverage.c.scheme_id == scheme_id, coverage.c.is_current.is_(True))
        .group_by(coverage.c.listing_status)
        .order_by(sa.func.count().desc())
    ).all()
    total = sum(count for _, count in counts)
    if row["official_description"]:
        headline = composer.say("head.scheme", name=row["name"], description=composer.src(row["official_description"]))
    else:
        headline = composer.say("head.scheme_no_description", name=row["name"], count=total)
    items = []
    if row["conformity_mark"]:
        items.append(AnswerItem(composer.say("item.scheme_mark", mark=row["conformity_mark"]), (scheme_evidence,)))
    if counts:
        summary = ", ".join(f"{count} {composer.say('effect.' + _STATUS_EFFECT.get(status, 'NEEDS_VERIFICATION'))}" for status, count in counts)
        items.append(AnswerItem(composer.say("item.scheme_counts", counts=summary), (scheme_evidence,)))
    documents = schema.scheme_document
    for document in conn.execute(
        sa.select(documents).where(documents.c.scheme_id == scheme_id, documents.c.is_current.is_(True)).order_by(documents.c.ordinal).limit(MAX_ITEMS)
    ).mappings():
        document_evidence = evidence.add_record("scheme_document", document, record_id=document["scheme_doc_id"], title=document["title"], snippet=document["title"], url=document["url"])
        items.append(AnswerItem(composer.say("item.scheme_document", title=document["title"]), (document_evidence,)))
    composer.section("scheme", items)
    composer.follow("follow.apply")
    composer.follow("follow.upcoming")
    return headline, None, ["listing_snapshot"], [scheme_evidence]


def _qco_general_answer(conn, query: str, composer: _Composer, evidence: EvidenceBuilder) -> tuple[str, str | None, list[str], list[str]]:
    chunk, document = schema.document_chunk, schema.document
    rows = conn.execute(
        sa.select(chunk, document.c.url, document.c.title.label("doc_title"), document.c.source_id, document.c.retrieved_at)
        .select_from(chunk.join(document, document.c.document_id == chunk.c.document_id))
        .where(document.c.source_id == OVERVIEW_SOURCE, document.c.is_current.is_(True))
        .order_by(chunk.c.ordinal)
        .limit(1)
    ).mappings().all()
    items, headline_ids = [], []
    for row in rows:
        evidence_id = evidence.add(kind="document_chunk", record_id=row["chunk_id"], title=row["doc_title"] or row["url"], source_id=row["source_id"], snippet=row["text"], url=row["url"], retrieved_at=row["retrieved_at"], page=row["page_start"])
        items.append(AnswerItem(snippet(row["text"], 520), (evidence_id,)))
        headline_ids.append(evidence_id)
    composer.section("documents", items)
    composer.link("link.certification", "/certification")
    composer.follow("follow.upcoming")
    composer.follow("follow.example_product")
    return composer.say("head.qco_general"), None, [], headline_ids


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
        items.append(AnswerItem(composer.say("item.faq", question=composer.src(row["question"]), answer=composer.src(snippet(row["answer"], 260))), (evidence_id,)))
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
        items.append(AnswerItem(composer.src(snippet(hit.snippet or row["text"], 260)), (evidence_id,)))
    composer.section("documents", items)
    return len(items)


def _invalid_identifier_answer(conn, understanding: QueryUnderstanding, composer: _Composer) -> tuple[str, str | None, list[str], list[str]]:
    ref = understanding.invalid_refs[0]
    digits = ref[2:].strip(" -:/").translate(str.maketrans("OoIl", "0011"))
    corrected = f"IS {digits}"
    if any(resolution.standard_ids for resolution in StandardResolver(conn).resolve_text(corrected)):
        composer.follow("follow.check_standard", ref=corrected)
    return composer.say("head.invalid_identifier", number=ref[2:].strip(" -:/")), UNKNOWN, ["possible_typo"], []


def _place_suggestion(understanding: QueryUnderstanding, composer: _Composer) -> None:
    """ "Did you mean …" for a Devanagari place name one spelling away from a known one; results stay unfiltered."""
    candidate = suggest_place(understanding.unresolved_place)
    if candidate:
        composer.section("suggestions", [AnswerItem(composer.say("item.place_suggestion", place=candidate))])


def _unknown_location_answer(conn, understanding: QueryUnderstanding, composer: _Composer, evidence: EvidenceBuilder) -> tuple[str, str | None, list[str], list[str]]:
    place = understanding.unresolved_place
    check = check_district(conn, place, None, evidence=evidence)
    composer.section("suggestions", [AnswerItem(composer.say("item.suggestion", district=item.get("district"), state=item.get("state"))) for item in check.suggestions[:5]])
    if not check.suggestions:
        _place_suggestion(understanding, composer)
    composer.follow("follow.example_hallmarking")
    return composer.say("head.unknown_location", place=place), None, ["location_not_recognised"], []


def _general_answer(conn, query: str, composer: _Composer, evidence: EvidenceBuilder) -> tuple[str, str | None, list[str], list[str]]:
    found = _faq_section(conn, query, composer, evidence) + _documents_section(conn, query, composer, evidence)
    if not found:
        composer.follow("follow.upcoming")
    return (composer.say("head.faq") if found else composer.say("head.nothing")), None, [], []


# --------------------------------------------------------------------------- entry point

_LOCAL_ROUTES_NEEDING_NO_MODEL = frozenset(SCHEME_ROUTES) | {
    ROUTE_PRODUCT, ROUTE_CERTIFICATION, ROUTE_QCO, ROUTE_LAB, ROUTE_HALLMARKING, ROUTE_AHC, ROUTE_GAP, ROUTE_UPCOMING,
    ROUTE_INVALID_IDENTIFIER, ROUTE_UNKNOWN_LOCATION, ROUTE_HSN,
}


def _model_assisted_route(query: str, understanding: QueryUnderstanding, route: Route, gazetteer: Gazetteer, settings: Settings) -> tuple[Route, QueryUnderstanding]:
    """Local first: a model is asked for routing hints only when the question is in scope but no deterministic flow
    applies (general or unroutable) — never for identifiers, listings, labs, hallmarking or other structured lookups.
    Hints are allow-listed (``apply_model_hints``) and the result goes back through the same local router."""
    if route.category in _LOCAL_ROUTES_NEEDING_NO_MODEL or not understanding.in_scope:
        groq.USAGE.add("understanding_not_needed")
        return route, understanding
    hints = groq.understand_query(query, settings)
    if not hints:
        return route, understanding
    hinted = apply_model_hints(understanding, hints)
    new_route = route_query(hinted, gazetteer)
    if new_route.category == route.category:
        return route, understanding
    return Route(new_route.category, f"{new_route.reason} (routing hint from language model)", new_route.scheme_id), hinted


def answer(
    conn: Connection,
    query: str,
    *,
    lang: str = "en",
    fallback_lang: str = "en",
    today: date | None = None,
    vectors=None,
    gazetteer: Gazetteer | None = None,
    settings: Settings | None = None,
) -> AssistantResponse:
    """``lang`` is "en", "hi" or "auto" (the language of the question, with ``fallback_lang`` when it is unclear)."""
    today = today or clock.today()
    lang = detect_language(query, fallback_lang) if lang == "auto" else (lang if lang in LANGUAGES else "en")
    settings = settings or get_settings()
    gazetteer = gazetteer or Gazetteer.load(conn)
    understanding = understand(query, gazetteer=gazetteer)
    route = route_query(understanding, gazetteer)
    if route.category == ROUTE_OUT_OF_SCOPE and fts_search.search_faq_all_terms(conn, understanding.normalized_text or query):
        route = Route(ROUTE_GENERAL, "every word found in an official FAQ")
    interpreted = interpret(query, understanding, route, gazetteer, settings)
    if interpreted is not None:
        understanding, route = interpreted
        route = Route(route.category, f"{route.reason} (question restated in English: {understanding.interpreted_as!r})", route.scheme_id)
    else:
        route, understanding = _model_assisted_route(query, understanding, route, gazetteer, settings)
    # Free-text lookups (FAQs, documents) search the English restatement when there is one.
    search_text = understanding.interpreted_as or query
    evidence = EvidenceBuilder(conn)
    composer = _Composer(lang)
    category = route.category

    if category == ROUTE_INVALID_IDENTIFIER:
        headline, status, caveats, headline_ids = _invalid_identifier_answer(conn, understanding, composer)
    elif category == ROUTE_GAP:
        headline, status, caveats, headline_ids = composer.say("head.gap"), None, [], []
        composer.link("link.gap", "/gap-analysis")
    elif category in (ROUTE_HALLMARKING, ROUTE_AHC):
        headline, status, caveats, headline_ids = _hallmarking_answer(conn, understanding, composer, evidence, today)
    elif category == ROUTE_LAB:
        headline, status, caveats, headline_ids = _labs_answer(conn, understanding, composer, evidence, today, vectors)
    elif category == ROUTE_UPCOMING:
        headline, status, caveats, headline_ids = _upcoming_answer(conn, composer, evidence, today)
    elif category == ROUTE_HSN:
        headline, status, caveats, headline_ids = _hsn_answer(conn, understanding, composer, evidence)
    elif route.scheme_id:
        headline, status, caveats, headline_ids = _scheme_answer(conn, SCHEME_ROUTES[category], composer, evidence)
    elif category == ROUTE_CERTIFICATION:
        headline, status, caveats, headline_ids = _process_answer(conn, composer, evidence, understanding.interpreted_as or understanding.normalized_text or query)
    elif category == ROUTE_UNKNOWN_LOCATION:
        headline, status, caveats, headline_ids = _unknown_location_answer(conn, understanding, composer, evidence)
    elif category == ROUTE_PRODUCT:
        headline, status, caveats, headline_ids = _product_answer(conn, understanding, composer, evidence, today, vectors)
        if INTENT_TESTS in understanding.intents:
            journey = build_journey(conn, text=understanding.product_text, std_key=understanding.standard_refs[0] if understanding.standard_refs else None, today=today, vectors=vectors)
            tests = next((step for step in journey.steps if step.key == "tests"), None)
            if tests and tests.data.get("sit_rows"):
                section_id = evidence.add(kind="guideline_section", record_id=f"sit:{tests.data['manual_url']}", title=tests.data["manual_title"], source_id="bis_product_manual_documents", url=tests.data["manual_url"], page=tests.data.get("sit_page"))
                composer.sections.insert(0, AnswerSection("tests", composer.say("section.tests"), tuple(AnswerItem(composer.say("item.sit", requirement=row["requirement"], clause=row["clause"], frequency=row["frequency"] or "—"), (section_id,)) for row in tests.data["sit_rows"][:8])))
        if INTENT_PROCESS in understanding.intents:
            _process_answer(conn, composer, evidence)
    elif category == ROUTE_QCO:
        headline, status, caveats, headline_ids = _qco_general_answer(conn, search_text, composer, evidence)
    elif category == ROUTE_GENERAL:
        headline, status, caveats, headline_ids = _general_answer(conn, search_text, composer, evidence)
    else:
        # ROUTE_OUT_OF_SCOPE: no BIS cue, identifier, place or listed product (understanding.in_scope is False here
        # or nothing in the records matched), so no record is consulted.
        headline, status, caveats, headline_ids = composer.say("head.out_of_scope"), None, [], []
        composer.follow("follow.example_product")
        composer.follow("follow.example_hallmarking")
        composer.follow("follow.upcoming")

    # Official English passages in a Hindi answer are shown in (checked) Hindi; names and identifiers stay as recorded.
    fill, translated = composer.localized(settings)
    sections = [AnswerSection(section.key, section.title, tuple(AnswerItem(fill(item.text), item.evidence_ids) for item in section.items)) for section in composer.sections]
    if translated:
        caveats = [*caveats, "machine_translation"]
    return AssistantResponse(
        query=query,
        lang=lang,
        understanding=understanding,
        headline=fill(headline),
        status_label=status,
        sections=sections,
        caveats=list(dict.fromkeys(caveats)),
        next_actions=[AnswerItem(fill(item.text), item.evidence_ids) for item in composer.actions],
        follow_ups=[fill(text) for text in composer.follow_ups[:4]],
        links=composer.links,
        evidence=evidence,
        headline_evidence=headline_ids,
        route=route,
    )
