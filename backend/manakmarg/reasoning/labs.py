"""Laboratory matching (spec §9.3): laboratories LIMS lists for an Indian Standard, filtered by location.

A laboratory appears only through a LIMS IS-wise scope row; its version, grade, charges, validity, remarks and
exclusions are shown verbatim. Status combines the Group-1 list remarks and the published validity dates against
the clock. Nothing beyond the scope row is claimed.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from manakmarg.core import clock
from manakmarg.db import schema
from manakmarg.ingest.sources import REGISTRY
from manakmarg.normalize.geo import compact_district, district_equivalents, normalize_state
from manakmarg.normalize.is_number import extract_designations, parse_designation
from manakmarg.normalize.text import norm_match
from manakmarg.reasoning.evidence import EvidenceBuilder

LAB_VALID = "VALID"
LAB_BIS = "BIS_LAB"
LAB_NEEDS_VERIFICATION = "NEEDS_VERIFICATION"
LAB_VALIDITY_UNKNOWN = "VALIDITY_UNKNOWN"
LAB_EXPIRED = "EXPIRED"
LAB_SUSPENDED = "SUSPENDED"
LAB_WITHDRAWN = "WITHDRAWN"

_STATUS_RANK = {
    LAB_VALID: 0,
    LAB_BIS: 0,
    LAB_NEEDS_VERIFICATION: 1,
    LAB_VALIDITY_UNKNOWN: 2,
    LAB_EXPIRED: 3,
    LAB_SUSPENDED: 4,
    LAB_WITHDRAWN: 5,
}
_LOCATION_RANK = {"district": 0, "city": 1, "state": 2, "any": 3, "outside_location": 4}
INACTIVE_STATUSES = frozenset({LAB_EXPIRED, LAB_SUSPENDED, LAB_WITHDRAWN})
LIMS_SEARCH_URL = REGISTRY["lims_is_scope_search"].url


@dataclass(frozen=True)
class LabMatch:
    scope_id: int
    lab_id: int | None
    lab_name: str
    lab_category: str | None
    osl_code: str | None
    address: str | None
    city: str | None
    district: str | None
    state: str | None
    pincode: str | None
    org_phone: str | None
    org_email: str | None
    is_ref_raw: str
    family_key: str | None
    version_year: int | None
    version_in_published_list: bool
    product: str | None
    grade_type: str | None
    charges_total: float | None
    validity_date: date | None
    remark: str | None
    exclusions: str | None
    tests: tuple[str, ...]
    test_count: int
    status: str
    status_reasons: tuple[str, ...]
    location_match: str
    evidence_ids: tuple[str, ...]


@dataclass
class LabSearchResult:
    query: str
    designations: list[str]
    doc_numbers: list[str]
    indexed_doc_numbers: list[str]
    lims_search_urls: list[str]
    location: dict
    location_fallback: bool
    checked_on: date
    matches: list[LabMatch]
    counts: dict
    evidence: EvidenceBuilder
    notes: list[str] = field(default_factory=list)


def _indexed(conn: Connection, doc_numbers: list[str]) -> list[str]:
    runs = schema.ingestion_run
    notes = {f"is_number__doc_no={number}": number for number in doc_numbers}
    rows = conn.execute(
        sa.select(runs.c.notes).where(
            runs.c.source_id == "lims_is_scope_search", runs.c.status == "success", runs.c.notes.in_(sorted(notes))
        )
    )
    return sorted({notes[row.notes] for row in rows})


def _matches_reference(row_ref: str, wanted) -> bool:
    found = parse_designation(row_ref)
    if found is None or found.number != wanted.number:
        return False
    if (wanted.prefix or "IS") != "IS" and found.prefix != wanted.prefix:
        return False
    return "(Part" not in wanted.match_key or found.match_key == wanted.match_key


def lab_status(row, entry, today: date) -> tuple[str, list[str]]:
    reasons: list[str] = []
    needs_verification = False
    if entry is not None:
        reasons.append(f"Group-{entry['group_no']} list (as on {entry['list_as_of']}): {entry['status_basis']}")
        if entry["derived_status"] == "SUSPENDED":
            return LAB_SUSPENDED, reasons
        if entry["derived_status"] == "WITHDRAWN":
            return LAB_WITHDRAWN, reasons
        needs_verification = entry["derived_status"] == "NEEDS_VERIFICATION"
    dates = [
        ("LIMS scope validity", row["validity_date"]),
        ("LIMS laboratory validity", row["lims_validity_date"]),
        ("Group list recognition valid up to", entry["valid_upto"] if entry is not None else None),
    ]
    for label, value in dates:
        if value is not None and value < today:
            reasons.append(f"{label} {value.isoformat()} has passed (checked on {today.isoformat()}).")
            return LAB_EXPIRED, reasons
    known = [value for _, value in dates if value is not None]
    if known:
        reasons.append(f"Valid until {min(known).isoformat()} per the published dates (checked on {today.isoformat()}).")
        return (LAB_NEEDS_VERIFICATION if needs_verification else LAB_VALID), reasons
    if row["lab_category"] == "BIS_LAB":
        reasons.append("BIS laboratory; LIMS publishes no validity date for BIS laboratories.")
        return LAB_BIS, reasons
    reasons.append("No validity date is published for this laboratory or scope row.")
    return LAB_VALIDITY_UNKNOWN, reasons


def _test_labels(conn: Connection, scope_ids: list[int]) -> dict[int, list[str]]:
    items = schema.lab_scope_item
    labels: dict[int, list[str]] = defaultdict(list)
    if not scope_ids:
        return labels
    rows = conn.execute(
        sa.select(items.c.scope_id, items.c.clause, items.c.parameter)
        .where(items.c.scope_id.in_(scope_ids))
        .order_by(items.c.scope_id, items.c.ordinal)
    )
    for row in rows:
        labels[row.scope_id].append(" — ".join(part for part in (row.clause, row.parameter) if part))
    return labels


def find_labs(
    conn: Connection,
    reference: str,
    *,
    state: str | None = None,
    district: str | None = None,
    city: str | None = None,
    include_inactive: bool = True,
    today: date | None = None,
    evidence: EvidenceBuilder | None = None,
    limit: int = 50,
) -> LabSearchResult:
    today = today or clock.today()
    evidence = evidence or EvidenceBuilder(conn)
    wanted = extract_designations(reference, assume_is_prefix=True)
    doc_numbers = sorted({designation.number for designation in wanted if designation.number})
    state_name = normalize_state(state) if state else None
    district_names = district_equivalents(district) if district else set()
    city_norm = norm_match(city) if city else ""
    location = {"state": state_name, "district": district, "city": city}
    result = LabSearchResult(
        query=reference,
        designations=[designation.std_key for designation in wanted],
        doc_numbers=doc_numbers,
        indexed_doc_numbers=_indexed(conn, doc_numbers),
        lims_search_urls=[f"{LIMS_SEARCH_URL}?is_number__doc_no={number}" for number in doc_numbers],
        location=location,
        location_fallback=False,
        checked_on=today,
        matches=[],
        counts={},
        evidence=evidence,
    )
    if not wanted:
        result.notes.append("no_standard_reference")
        return result

    scope, lab = schema.lab_scope, schema.laboratory
    rows = conn.execute(
        sa.select(
            scope,
            lab.c.name.label("lab_name"),
            lab.c.lab_category,
            lab.c.osl_code.label("lab_osl_code"),
            lab.c.address_raw,
            lab.c.city,
            lab.c.district,
            lab.c.state,
            lab.c.pincode,
            lab.c.org_phone,
            lab.c.org_email,
            lab.c.lims_validity_date,
            lab.c.source_id.label("lab_source_id"),
            lab.c.source_locator.label("lab_source_locator"),
            lab.c.retrieved_at.label("lab_retrieved_at"),
        )
        .select_from(scope.outerjoin(lab, sa.and_(lab.c.lab_id == scope.c.lab_id, lab.c.is_current.is_(True))))
        .where(scope.c.is_current.is_(True), scope.c.query_doc_no.in_(doc_numbers))
    ).mappings().all()
    rows = [row for row in rows if any(_matches_reference(row["is_ref_raw"], designation) for designation in wanted)]
    if not rows:
        result.notes.append("no_scope_rows" if result.indexed_doc_numbers else "scope_not_indexed")
        return result

    entries = {
        entry["osl_code"]: entry
        for entry in conn.execute(
            sa.select(schema.lab_list_entry).where(schema.lab_list_entry.c.is_current.is_(True), schema.lab_list_entry.c.osl_code.is_not(None))
        ).mappings()
    }

    def location_match(row) -> str | None:
        if district_names and compact_district(row["district"]) in district_names:
            return "district"
        if city_norm and (city_norm == norm_match(row["city"]) or city_norm in norm_match(row["address_raw"])):
            return "city"
        if state_name and row["state"] == state_name:
            return "state"
        if not (state_name or district_names or city_norm):
            return "any"
        return None

    located = [(row, location_match(row)) for row in rows]
    if not any(match for _, match in located):
        result.location_fallback = True
        located = [(row, "outside_location") for row, _ in located]
    else:
        located = [(row, match) for row, match in located if match]

    labels = _test_labels(conn, [row["scope_id"] for row, _ in located])
    counts = Counter()
    matches: list[LabMatch] = []
    for row, match in located:
        osl_code = row["osl_code_raw"] or row["lab_osl_code"]
        entry = entries.get(osl_code) if osl_code else None
        status, reasons = lab_status(row, entry, today)
        counts[status] += 1
        if status in INACTIVE_STATUSES and not include_inactive:
            continue
        ids = [
            evidence.add_record(
                "lab_scope",
                row,
                record_id=row["scope_id"],
                title=f"{row['lab_name_raw']} — {row['is_ref_raw']}",
                snippet=(
                    f"Product: {row['product'] or '-'}; grade/type: {row['grade_type'] or '-'}; charges: {row['charges_raw'] or '-'}; "
                    f"validity: {row['validity_raw'] or '-'}; remark: {row['remark_raw'] or '-'}"
                ),
            )
        ]
        if row["lab_source_id"]:
            ids.append(
                evidence.add_record(
                    "laboratory",
                    row,
                    record_id=row["lab_id"],
                    title=row["lab_name"],
                    snippet=row["address_raw"],
                    prefix="lab_",
                )
            )
        if entry is not None:
            ids.append(
                evidence.add_record(
                    "lab_list_entry", entry, record_id=entry["entry_key"], title=entry["name_raw"], snippet=entry["status_basis"]
                )
            )
        tests = labels.get(row["scope_id"], [])
        matches.append(
            LabMatch(
                scope_id=row["scope_id"],
                lab_id=row["lab_id"],
                lab_name=row["lab_name"] or row["lab_name_raw"],
                lab_category=row["lab_category"],
                osl_code=osl_code,
                address=row["address_raw"],
                city=row["city"],
                district=row["district"],
                state=row["state"],
                pincode=row["pincode"],
                org_phone=row["org_phone"],
                org_email=row["org_email"],
                is_ref_raw=row["is_ref_raw"],
                family_key=row["family_key"],
                version_year=row["version_year"],
                version_in_published_list=row["standard_id"] is not None,
                product=row["product"],
                grade_type=row["grade_type"],
                charges_total=row["charges_total"],
                validity_date=row["validity_date"],
                remark=row["remark_raw"],
                exclusions=row["exclusions_text"],
                tests=tuple(tests[:12]),
                test_count=len(tests),
                status=status,
                status_reasons=tuple(reasons),
                location_match=match,
                evidence_ids=tuple(ids),
            )
        )
    matches.sort(
        key=lambda item: (
            _LOCATION_RANK[item.location_match],
            _STATUS_RANK[item.status],
            0 if item.version_in_published_list else 1,
            1 if item.exclusions else 0,
            -(item.version_year or 0),
            item.lab_name,
        )
    )
    result.matches = matches[:limit]
    result.counts = {"rows": len(located), "by_status": dict(counts), "laboratories": len({m.lab_id or m.lab_name for m in matches})}
    return result
