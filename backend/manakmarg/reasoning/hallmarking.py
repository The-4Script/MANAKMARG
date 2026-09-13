"""Hallmarking advisor (spec §9.4): district coverage and AHC operability, computed against the clock.

* District coverage comes from BIS's phase-wise list, matched through official spellings, Gazette spellings and
  curated renames. A district that the Gazette annex does not list is flagged for verification, not confirmed.
* An AHC is presented as operative only when the Manakonline list says "Operative", its recognition validity has
  not ended and neither official list records a cancellation or suspension (``effective_ahc_status``).
* Licensed jewellers are not collected because the official report is CAPTCHA-protected; users get its link.
"""

import difflib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from manakmarg.core import clock
from manakmarg.db import schema
from manakmarg.ingest.hallmarking import OPERATIVE, AhcEventRecord, effective_ahc_status
from manakmarg.ingest.sources import REGISTRY
from manakmarg.normalize.geo import compact_district, district_equivalents, norm_district, normalize_state
from manakmarg.reasoning.evidence import EvidenceBuilder

COVERED = "COVERED"
COVERED_NEEDS_VERIFICATION = "COVERED_NEEDS_VERIFICATION"
AMBIGUOUS = "AMBIGUOUS"
NOT_IN_LIST = "NOT_IN_LIST"

GAZETTE_SOURCE = REGISTRY["bis_hm_gazette_2026_08_03"]
JEWELLER_SOURCE = REGISTRY["manak_jewellers_report"]


@dataclass(frozen=True)
class DistrictMatch:
    district_id: int
    state: str
    district: str
    phase_no: int | None
    phase_label: str | None
    phase_order_date: date | None
    phase_order_date_raw: str | None
    gazette_validated: bool | None
    gazette_note: str | None
    matched_name: str
    match_basis: str
    evidence_ids: tuple[str, ...]


@dataclass
class DistrictCheck:
    query_district: str
    query_state: str | None
    status: str
    matches: list[DistrictMatch]
    suggestions: list[dict]
    evidence: EvidenceBuilder
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AhcView:
    ahc_id: int
    recognition_no: str
    name: str
    address: str | None
    district: str | None
    state: str | None
    pincode: str | None
    gold: bool | None
    silver: bool | None
    scope_text: str | None
    validity_date: date | None
    list_status_raw: str | None
    effective_status: str
    reasons: tuple[str, ...]
    org_phone: str | None
    org_email: str | None
    evidence_ids: tuple[str, ...]


@dataclass
class AhcSearchResult:
    state: str | None
    district: str | None
    checked_on: date
    operative: list[AhcView]
    inactive: list[AhcView]
    counts: dict[str, int]
    evidence: EvidenceBuilder


def _district_names(conn: Connection, district: str) -> dict[str, str]:
    """Compact names that identify the district, each with the basis for using it."""
    names = {name: "curated_rename" for name in district_equivalents(district)}
    compact = compact_district(district)
    if compact:
        names[compact] = "as_entered"
    aliases = schema.district_alias
    ids = [row.district_id for row in conn.execute(sa.select(aliases.c.district_id).where(aliases.c.alias_norm.in_(sorted(names))))]
    if ids:
        for row in conn.execute(sa.select(aliases.c.alias_norm, aliases.c.basis).where(aliases.c.district_id.in_(ids))):
            names.setdefault(row.alias_norm.replace(" ", ""), row.basis)
    return names


def _district_rows(conn: Connection, names: set[str]):
    district = schema.hallmarking_district
    rows = conn.execute(sa.select(district).where(district.c.is_current.is_(True))).mappings().all()
    return [row for row in rows if compact_district(row["district"]) in names or row["district_norm"].replace(" ", "") in names]


def _suggestions(conn: Connection, district: str, state: str | None) -> list[dict]:
    table = schema.hallmarking_district
    query = sa.select(table.c.district, table.c.state, table.c.district_norm).where(table.c.is_current.is_(True))
    if state:
        query = query.where(table.c.state == state)
    rows = conn.execute(query).all()
    by_norm = defaultdict(list)
    for row in rows:
        by_norm[row.district_norm].append(row)
    close = difflib.get_close_matches(norm_district(district), list(by_norm), n=5, cutoff=0.75)
    return [{"district": row.district, "state": row.state} for name in close for row in by_norm[name]]


def check_district(
    conn: Connection, district: str, state: str | None = None, *, evidence: EvidenceBuilder | None = None
) -> DistrictCheck:
    evidence = evidence or EvidenceBuilder(conn)
    state_name = normalize_state(state) if state else None
    names = _district_names(conn, district) if compact_district(district) else {}
    rows = _district_rows(conn, set(names))
    if state_name:
        rows = [row for row in rows if row["state"] == state_name]

    matches = []
    for row in sorted(rows, key=lambda item: (item["state"], item["district"])):
        compact = compact_district(row["district"])
        basis = "official_name" if compact == compact_district(district) else names.get(compact, "alias")
        gazette_only = row["phase_no"] is None
        if gazette_only:
            title = f"{row['district']}, {row['state']} — listed in the Gazette district annex"
            snippet = row["gazette_note"]
        else:
            title = f"{row['district']}, {row['state']} — mandatory hallmarking phase {row['phase_no']}"
            snippet = f"{row['phase_label']} — {row['phase_order_date_raw']}. Listed as: {row['state_raw']} / {row['district_raw']}."
        ids = [evidence.add_record("hallmarking_district", row, record_id=row["district_id"], title=title, snippet=snippet)]
        if row["gazette_note"] and not gazette_only:
            ids.append(
                evidence.add(
                    kind="gazette_cross_check",
                    record_id=row["district_id"],
                    title=f"Cross-check against {GAZETTE_SOURCE.name}",
                    source_id=GAZETTE_SOURCE.source_id,
                    snippet=row["gazette_note"],
                    url=GAZETTE_SOURCE.url,
                    authority="derived",
                )
            )
        matches.append(
            DistrictMatch(
                district_id=row["district_id"],
                state=row["state"],
                district=row["district"],
                phase_no=row["phase_no"],
                phase_label=row["phase_label"],
                phase_order_date=row["phase_order_date"],
                phase_order_date_raw=row["phase_order_date_raw"],
                gazette_validated=row["gazette_validated"],
                gazette_note=row["gazette_note"],
                matched_name=row["district"],
                match_basis=basis,
                evidence_ids=tuple(ids),
            )
        )

    notes: list[str] = []
    suggestions: list[dict] = []
    if not matches:
        status = NOT_IN_LIST
        suggestions = _suggestions(conn, district, state_name)
    elif len({match.state for match in matches}) > 1:
        status = AMBIGUOUS
    elif all(match.phase_no is None for match in matches):
        status = COVERED_NEEDS_VERIFICATION
        notes.append("gazette_only")
    elif any(match.gazette_validated for match in matches) or all(match.gazette_validated is None for match in matches):
        status = COVERED
        if all(match.gazette_validated is None for match in matches):
            notes.append("gazette_not_checked")
    else:
        status = COVERED_NEEDS_VERIFICATION
    return DistrictCheck(district, state_name, status, matches, suggestions, evidence, notes)


def _event_records(conn: Connection, recognition_numbers: list[str]) -> dict[str, list]:
    table = schema.ahc_status_event
    events: dict[str, list] = defaultdict(list)
    if not recognition_numbers:
        return events
    rows = conn.execute(
        sa.select(table).where(table.c.is_current.is_(True), table.c.recognition_no.in_(recognition_numbers))
    ).mappings()
    for row in rows:
        events[row["recognition_no"]].append(row)
    return events


def find_ahcs(
    conn: Connection,
    *,
    state: str | None = None,
    district: str | None = None,
    metal: str | None = None,
    include_inactive: bool = False,
    today: date | None = None,
    evidence: EvidenceBuilder | None = None,
) -> AhcSearchResult:
    """AHCs by state/district. Operative centres are returned by default; others only with ``include_inactive``,
    always counted, and each carries the reasons for its status."""
    today = today or clock.today()
    evidence = evidence or EvidenceBuilder(conn)
    table = schema.ahc
    state_name = normalize_state(state) if state else None
    query = sa.select(table).where(table.c.is_current.is_(True))
    if state_name:
        query = query.where(table.c.state == state_name)
    rows = conn.execute(query.order_by(table.c.name)).mappings().all()
    if district and compact_district(district):
        names = set(_district_names(conn, district))
        rows = [row for row in rows if compact_district(row["district"]) in names]
    if metal in ("gold", "silver"):
        rows = [row for row in rows if row[metal]]

    events = _event_records(conn, [row["recognition_no"] for row in rows])
    operative, inactive, counts = [], [], Counter()
    for row in rows:
        event_rows = events.get(row["recognition_no"], [])
        records = [
            AhcEventRecord(
                recognition_no=event["recognition_no"],
                status=event["status"],
                event_date=event["event_date"],
                event_date_raw=event["event_date_raw"],
                region=event["region"],
                center_type=event["center_type"],
                name_address_raw=event["name_address_raw"],
                locator=event["source_locator"],
            )
            for event in event_rows
        ]
        status, reasons = effective_ahc_status(row["list_status_raw"], row["validity_date"], records, today=today)
        counts[status] += 1
        if status != OPERATIVE and not include_inactive:
            continue
        ids = [
            evidence.add_record(
                "ahc",
                row,
                record_id=row["recognition_no"],
                title=f"{row['name']} ({row['recognition_no']})",
                snippet=f"Status: {row['list_status_raw']}; validity {row['validity_raw']}; {row['scope_text'] or ''}",
            )
        ]
        ids += [
            evidence.add_record(
                "ahc_status_event",
                event,
                record_id=event["event_key"],
                title=f"{event['recognition_no']} — {event['status']}",
                snippet=f"{event['status']} dated {event['event_date_raw']}",
            )
            for event in event_rows
        ]
        view = AhcView(
            ahc_id=row["ahc_id"],
            recognition_no=row["recognition_no"],
            name=row["name"],
            address=row["address_raw"],
            district=row["district"],
            state=row["state"],
            pincode=row["pincode"],
            gold=row["gold"],
            silver=row["silver"],
            scope_text=row["scope_text"],
            validity_date=row["validity_date"],
            list_status_raw=row["list_status_raw"],
            effective_status=status,
            reasons=tuple(reasons),
            org_phone=row["org_phone"],
            org_email=row["org_email"],
            evidence_ids=tuple(ids),
        )
        (operative if status == OPERATIVE else inactive).append(view)
    inactive.sort(key=lambda view: (view.effective_status, view.name))
    return AhcSearchResult(state_name, district, today, operative, inactive, dict(counts), evidence)


def jeweller_guidance() -> dict:
    return {
        "url": JEWELLER_SOURCE.url,
        "access_status": JEWELLER_SOURCE.access_status,
        "note": JEWELLER_SOURCE.access_notes,
    }
