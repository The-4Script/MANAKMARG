"""Applicability and compulsory status (spec §9.1).

Labels:

* ``CONFIRMED`` — the user named an exact identifier (an IS number or a listing) and an official listing states the fact.
* ``LIKELY_APPLICABLE`` — the product words fully match an official compulsory-listing product with a clear margin.
* ``CANDIDATE`` — weaker or tied matches; the user is asked to confirm the product.
* ``NEEDS_VERIFICATION`` — the matched listing is de-notified, rescinded or marked for verification, an upcoming
  enforcement date has been reached, or strong matches disagree.
* ``UNKNOWN`` — no supporting record.

Compulsory status is read from the listing record and computed dates only; match scores only order candidates.
The absence of a listing is never presented as proof that a product is unregulated.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from manakmarg.core import clock
from manakmarg.db import schema
from manakmarg.normalize.status_rules import upcoming_effect
from manakmarg.normalize.text import norm_match
from manakmarg.reasoning.evidence import EvidenceBuilder
from manakmarg.search.hybrid import CoverageCandidate, StandardCandidate, find_product_matches, standard_candidates
from manakmarg.search.resolvers import (
    EXACT_VERSION,
    FAMILY_AMBIGUOUS,
    FAMILY_LATEST,
    MATCH_KEY_VERSION,
    VERSION_NOT_IN_MASTER,
    Resolution,
    StandardResolver,
)

CONFIRMED = "CONFIRMED"
LIKELY_APPLICABLE = "LIKELY_APPLICABLE"
CANDIDATE = "CANDIDATE"
NEEDS_VERIFICATION = "NEEDS_VERIFICATION"
UNKNOWN = "UNKNOWN"

COMPULSORY = "COMPULSORY"
UPCOMING = "UPCOMING"
ENFORCEMENT_DATE_REACHED = "ENFORCEMENT_DATE_REACHED"
DENOTIFIED = "DENOTIFIED"
RESCINDED = "RESCINDED"
VERIFY = "NEEDS_VERIFICATION"
NO_LISTING_FOUND = "NO_LISTING_FOUND"

STRONG_COVERAGE = 0.8
WEAK_COVERAGE = 0.5
CLEAR_MARGIN = 0.1
IN_FORCE_OR_NOTIFIED = frozenset({COMPULSORY, UPCOMING})
WITHDRAWN_EFFECTS = frozenset({DENOTIFIED, RESCINDED})
_EFFECT_ORDER = {COMPULSORY: 0, UPCOMING: 1, ENFORCEMENT_DATE_REACHED: 2, VERIFY: 3, RESCINDED: 4, DENOTIFIED: 5}
_USABLE_RESOLUTIONS = frozenset({EXACT_VERSION, MATCH_KEY_VERSION, FAMILY_LATEST, FAMILY_AMBIGUOUS, VERSION_NOT_IN_MASTER})


@dataclass(frozen=True)
class StandardLink:
    ref_raw: str
    role: str
    resolution: str
    family_key: str | None
    standard_id: int | None
    std_key: str | None
    title: str | None
    evidence_id: str | None


@dataclass(frozen=True)
class OrderView:
    order_id: int
    title: str
    kind: str
    so_number: str | None
    gsr_number: str | None
    order_date: date | None
    url: str | None
    text_indexed: bool
    evidence_id: str


@dataclass(frozen=True)
class ListingView:
    coverage_id: int
    scheme_id: str | None
    scheme_name: str | None
    page_kind: str
    section_label: str | None
    category: str | None
    product_name: str
    parent_coverage_id: int | None
    parent_product_name: str | None
    listing_status: str
    status_basis: str | None
    effect: str
    days_to_enforcement: int | None
    enforcement_date: date | None
    enforcement_date_raw: str | None
    ministry_department: str | None
    essential_requirement: str | None
    specific_requirement: str | None
    notification_text: str | None
    standards: tuple[StandardLink, ...]
    orders: tuple[OrderView, ...]
    page_url: str | None
    retrieved_at: str | None
    evidence_id: str
    token_coverage: float | None
    matched_via: tuple[str, ...]


@dataclass(frozen=True)
class IdentifierView:
    ref_raw: str
    kind: str
    std_key: str | None
    family_key: str | None
    standard_ids: tuple[int, ...]
    note: str


@dataclass
class Assessment:
    label: str
    compulsory: str
    basis: str
    listings: list[ListingView]
    candidates: list[CoverageCandidate]
    standards: list[StandardCandidate]
    identifiers: list[IdentifierView]
    synonyms_used: list[tuple[str, str]]
    caveats: list[str]
    checked_on: date
    evidence: EvidenceBuilder


def listing_effect(status: str, enforcement_date: date | None, today: date) -> tuple[str, int | None]:
    if status == "UPCOMING":
        effect = upcoming_effect(enforcement_date, today=today)
        days = (enforcement_date - today).days if enforcement_date else None
        return {"NOT_YET_IN_FORCE": UPCOMING, "ENFORCEMENT_DATE_REACHED": ENFORCEMENT_DATE_REACHED}.get(effect, VERIFY), days
    return {"LISTED_COMPULSORY": COMPULSORY, "DENOTIFIED": DENOTIFIED, "RESCINDED": RESCINDED}.get(status, VERIFY), None


def _conflicting(effects: list[str]) -> bool:
    present = set(effects)
    return bool(present & IN_FORCE_OR_NOTIFIED) and bool(present & WITHDRAWN_EFFECTS)


def load_listings(
    conn: Connection,
    coverage_ids: list[int],
    evidence: EvidenceBuilder,
    today: date,
    candidates: dict[int, CoverageCandidate] | None = None,
) -> list[ListingView]:
    if not coverage_ids:
        return []
    coverage, scheme = schema.scheme_coverage, schema.certification_scheme
    rows = {
        row["coverage_id"]: row
        for row in conn.execute(
            sa.select(coverage, scheme.c.name.label("scheme_name"))
            .select_from(coverage.outerjoin(scheme, scheme.c.scheme_id == coverage.c.scheme_id))
            .where(coverage.c.coverage_id.in_(coverage_ids), coverage.c.is_current.is_(True))
        ).mappings()
    }
    parent_ids = [row["parent_coverage_id"] for row in rows.values() if row["parent_coverage_id"]]
    parents = {
        row.coverage_id: row.product_name
        for row in conn.execute(sa.select(coverage.c.coverage_id, coverage.c.product_name).where(coverage.c.coverage_id.in_(parent_ids or [-1])))
    }

    links, standard = schema.coverage_standard, schema.standard
    standards_by_listing: dict[int, list[StandardLink]] = defaultdict(list)
    link_rows = conn.execute(
        sa.select(
            links,
            standard.c.std_key,
            standard.c.title_clean,
            standard.c.title,
            standard.c.source_id.label("std_source_id"),
            standard.c.source_locator.label("std_source_locator"),
            standard.c.retrieved_at.label("std_retrieved_at"),
        )
        .select_from(links.outerjoin(standard, standard.c.standard_id == links.c.standard_id))
        .where(links.c.coverage_id.in_(list(rows)))
        .order_by(links.c.coverage_id, links.c.ordinal)
    ).mappings()
    for link in link_rows:
        evidence_id = None
        if link["standard_id"] is not None:
            evidence_id = evidence.add_record(
                "standard",
                link,
                record_id=link["std_key"],
                title=f"{link['std_key']} — {link['title_clean'] or link['title']}",
                snippet=link["title_clean"] or link["title"],
                prefix="std_",
            )
        standards_by_listing[link["coverage_id"]].append(
            StandardLink(
                ref_raw=link["ref_raw"],
                role=link["role"],
                resolution=link["resolution"],
                family_key=link["family_key"],
                standard_id=link["standard_id"],
                std_key=link["std_key"],
                title=link["title_clean"] or link["title"],
                evidence_id=evidence_id,
            )
        )

    order_links, orders, document = schema.coverage_order, schema.regulatory_order, schema.document
    orders_by_listing: dict[int, list[OrderView]] = defaultdict(list)
    order_rows = conn.execute(
        sa.select(order_links.c.coverage_id, orders, document.c.text_status)
        .select_from(order_links.join(orders, orders.c.order_id == order_links.c.order_id).outerjoin(document, document.c.document_id == orders.c.document_id))
        .where(order_links.c.coverage_id.in_(list(rows)))
        .order_by(order_links.c.coverage_id, order_links.c.ordinal)
    ).mappings()
    for order in order_rows:
        number = order["so_number"] or order["gsr_number"]
        evidence_id = evidence.add_record(
            "regulatory_order",
            order,
            record_id=order["order_id"],
            title=order["title"],
            snippet=" · ".join(str(part) for part in (order["order_kind"], number, order["order_date"]) if part),
            url=order["url"],
        )
        orders_by_listing[order["coverage_id"]].append(
            OrderView(
                order_id=order["order_id"],
                title=order["title"],
                kind=order["order_kind"],
                so_number=order["so_number"],
                gsr_number=order["gsr_number"],
                order_date=order["order_date"],
                url=order["url"],
                text_indexed=order["text_status"] in ("text_extracted", "parsed"),
                evidence_id=evidence_id,
            )
        )

    views = []
    for coverage_id in coverage_ids:
        row = rows.get(coverage_id)
        if row is None:
            continue
        effect, days = listing_effect(row["listing_status"], row["enforcement_date"], today)
        candidate = (candidates or {}).get(coverage_id)
        scheme_name = row["scheme_name"] or ("Upcoming QCOs" if row["page_kind"] == "upcoming_qco" else None)
        evidence_id = evidence.add_record(
            "coverage_listing",
            row,
            record_id=coverage_id,
            title=f"{scheme_name or row['page_kind']} — {row['product_name']}",
            snippet=" ".join(
                part for part in (row["status_basis"], f"Standard: {row['standard_ref_raw']}." if row["standard_ref_raw"] else None) if part
            ),
        )
        locator = row["source_locator"] or ""
        views.append(
            ListingView(
                coverage_id=coverage_id,
                scheme_id=row["scheme_id"],
                scheme_name=scheme_name,
                page_kind=row["page_kind"],
                section_label=row["section_label"],
                category=row["category"],
                product_name=row["product_name"],
                parent_coverage_id=row["parent_coverage_id"],
                parent_product_name=parents.get(row["parent_coverage_id"]),
                listing_status=row["listing_status"],
                status_basis=row["status_basis"],
                effect=effect,
                days_to_enforcement=days,
                enforcement_date=row["enforcement_date"],
                enforcement_date_raw=row["enforcement_date_raw"],
                ministry_department=row["ministry_department"],
                essential_requirement=row["essential_requirement"],
                specific_requirement=row["specific_requirement"],
                notification_text=row["notification_text_raw"],
                standards=tuple(standards_by_listing[coverage_id]),
                orders=tuple(orders_by_listing[coverage_id]),
                page_url=locator.split("#", 1)[0] if locator.startswith("http") else None,
                retrieved_at=row["retrieved_at"],
                evidence_id=evidence_id,
                token_coverage=candidate.token_coverage if candidate else None,
                matched_via=candidate.matched_via if candidate else (),
            )
        )
    return views


def _product_key(name: str) -> str:
    return "".join(norm_match(name).split())


def _lead_with_future_enforcement(listings: list[ListingView]) -> tuple[list[ListingView], bool]:
    """A product listed on a scheme page and also on the upcoming-QCO page with a future enforcement date leads
    with the upcoming listing: the enforcement date is the fact the user needs, and both listings stay visible."""
    compulsory = {_product_key(view.product_name) for view in listings if view.effect == COMPULSORY}
    twins = {_product_key(view.product_name): view for view in listings if view.effect == UPCOMING and _product_key(view.product_name) in compulsory}
    if not twins:
        return listings, False
    ordered: list[ListingView] = []
    emitted: set[int] = set()
    for view in listings:
        if view.coverage_id in emitted:
            continue
        twin = twins.get(_product_key(view.product_name)) if view.effect == COMPULSORY else None
        if twin is not None and twin.coverage_id not in emitted:
            ordered.append(twin)
            emitted.add(twin.coverage_id)
        ordered.append(view)
        emitted.add(view.coverage_id)
    # The caveat concerns the lead listing only; another matched product's twin must not colour this answer.
    return ordered, ordered[0].coverage_id in {twin.coverage_id for twin in twins.values()}


def _identifier_views(resolutions: list[Resolution]) -> list[IdentifierView]:
    return [
        IdentifierView(
            ref_raw=resolution.ref_raw,
            kind=resolution.kind,
            std_key=resolution.designation.std_key if resolution.designation else None,
            family_key=resolution.family_key,
            standard_ids=resolution.standard_ids,
            note=resolution.note,
        )
        for resolution in resolutions
    ]


def _families(conn: Connection, resolutions: list[Resolution]) -> set[str]:
    # An ambiguous reference ("IS 2062" when only its parts are published) keeps its own family key too: listings that
    # cite the older, undivided standard are linked under that key.
    families = {resolution.family_key for resolution in resolutions if resolution.family_key}
    ambiguous_ids = [standard_id for resolution in resolutions if resolution.kind == FAMILY_AMBIGUOUS for standard_id in resolution.standard_ids]
    if ambiguous_ids:
        table = schema.standard
        families |= {row.family_key for row in conn.execute(sa.select(table.c.family_key).where(table.c.standard_id.in_(ambiguous_ids)))}
    return families


def _linked_listing_ids(conn: Connection, families: set[str]) -> list[int]:
    links, coverage = schema.coverage_standard, schema.scheme_coverage
    rows = conn.execute(
        sa.select(links.c.coverage_id)
        .select_from(links.join(coverage, coverage.c.coverage_id == links.c.coverage_id))
        .where(links.c.family_key.in_(sorted(families)), coverage.c.is_current.is_(True))
        .distinct()
    )
    return [row.coverage_id for row in rows]


def assess(
    conn: Connection,
    *,
    text: str | None = None,
    std_key: str | None = None,
    coverage_id: int | None = None,
    today: date | None = None,
    evidence: EvidenceBuilder | None = None,
    vectors=None,
    limit: int = 6,
) -> Assessment:
    today = today or clock.today()
    evidence = evidence or EvidenceBuilder(conn)
    resolver = StandardResolver(conn)
    candidates: list[CoverageCandidate] = []
    standards: list[StandardCandidate] = []
    synonyms: list[tuple[str, str]] = []
    resolutions: list[Resolution] = []
    basis = "none"
    listing_ids: list[int] = []

    if text:
        matches = find_product_matches(conn, text, limit=12, vectors=vectors, resolver=resolver)
        candidates, standards, synonyms = matches.coverage, matches.standards, list(matches.synonyms_used)
        resolutions = list(matches.identifiers)
    if std_key:
        resolutions = resolver.resolve_text(std_key) + [item for item in resolutions if item.ref_raw != std_key]
        if not text:
            standards = standard_candidates(conn, std_key, tuple(resolutions), limit)
    usable = [resolution for resolution in resolutions if resolution.kind in _USABLE_RESOLUTIONS]

    if coverage_id is not None:
        basis, listing_ids = "selected_listing", [coverage_id]
    elif usable:
        basis, listing_ids = "standard_reference", _linked_listing_ids(conn, _families(conn, usable))
    elif candidates:
        basis = "product_text"
        listing_ids = [candidate.coverage_id for candidate in candidates if candidate.token_coverage >= WEAK_COVERAGE][:limit]
    elif standards:
        basis = "standard_title"

    by_id = {candidate.coverage_id: candidate for candidate in candidates}
    listings = load_listings(conn, listing_ids, evidence, today, by_id)
    if basis == "standard_reference":
        listings.sort(key=lambda view: (_EFFECT_ORDER.get(view.effect, 9), view.product_name))
        listings = listings[: max(limit, 1) * 2]
    listings, also_upcoming = _lead_with_future_enforcement(listings)
    effects = [view.effect for view in listings]

    if basis in ("selected_listing", "standard_reference"):
        if listings:
            label = CONFIRMED if effects[0] in IN_FORCE_OR_NOTIFIED and not _conflicting(effects) else NEEDS_VERIFICATION
        else:
            label = CONFIRMED if basis == "standard_reference" and any(item.standard_ids for item in usable) else UNKNOWN
    elif basis == "product_text" and listings:
        top = candidates[0]
        rival = next(
            (
                candidate
                for candidate in candidates[1:]
                if candidate.token_coverage >= STRONG_COVERAGE and norm_match(candidate.product_name) != norm_match(top.product_name)
            ),
            None,
        )
        strong = top.token_coverage >= STRONG_COVERAGE and (rival is None or top.score - rival.score >= CLEAR_MARGIN)
        label = LIKELY_APPLICABLE if strong else CANDIDATE
        strong_effects = [view.effect for view in listings if (view.token_coverage or 0) >= STRONG_COVERAGE]
        if listings[0].effect not in IN_FORCE_OR_NOTIFIED or _conflicting(strong_effects):
            label = NEEDS_VERIFICATION
    elif standards:
        label = CANDIDATE
    else:
        label = UNKNOWN

    compulsory = listings[0].effect if listings else NO_LISTING_FOUND
    caveats = ["listing_snapshot"]
    if compulsory == NO_LISTING_FOUND:
        caveats.append("absence_not_proof")
    if label in (LIKELY_APPLICABLE, CANDIDATE):
        caveats.append("confirm_product")
    if label == NEEDS_VERIFICATION:
        caveats.append("status_needs_verification")
    if any(link.resolution == VERSION_NOT_IN_MASTER for view in listings for link in view.standards) or any(
        item.kind == VERSION_NOT_IN_MASTER for item in resolutions
    ):
        caveats.append("version_not_in_published_list")
    if synonyms:
        caveats.append("matched_via_synonym")
    if also_upcoming:
        caveats.append("listed_and_upcoming")

    return Assessment(
        label=label,
        compulsory=compulsory,
        basis=basis,
        listings=listings,
        candidates=candidates,
        standards=standards,
        identifiers=_identifier_views(resolutions),
        synonyms_used=synonyms,
        caveats=caveats,
        checked_on=today,
        evidence=evidence,
    )
