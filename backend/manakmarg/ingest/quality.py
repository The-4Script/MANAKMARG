"""Data-quality checks over the normalized database (plan Task 2.4; later milestones add checks).

Every check returns a ``Finding`` with a fixed severity, a count, a few examples and a plain-language
note, even when the count is zero, so the report shows what was verified.
"""

import collections
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from manakmarg.core import clock
from manakmarg.db import schema
from manakmarg.normalize.text import norm_match

PROVENANCE_TABLES = (
    "document",
    "standard",
    "standard_alias",
    "classification_node",
    "standard_classification",
    "standard_relation",
    "certification_scheme",
    "regulatory_order",
    "scheme_coverage",
    "product_guideline",
    "process_step",
    "scheme_document",
    "laboratory",
    "lab_list_entry",
    "lab_scope",
    "ahc",
    "ahc_status_event",
    "hallmarking_district",
    "jeweller",
    "faq",
)

_VALUE_GAP_CHECKS = {
    "missing_publication_date": ("warning", "Standards whose export row has no publication date."),
    "type_unspecified": ("info", "Standards whose 'Type of Standard' is '-' in the export; stored as unknown."),
    "equivalence_unspecified": ("info", "Standards whose 'Degree of Equivalence' is '-' in the export; stored as unknown."),
}
_DESIGNATION_FLAG_SEVERITY = {"unparsed": "warning", "malformed_repaired": "warning", "year_out_of_range": "warning"}
_DESIGNATION_FLAG_NOTES = {
    "prefix_case": "Designation prefix written with irregular letter case (e.g. 'Is'); normalised.",
    "prefix_repaired": "Designation prefix with irregular separators or a known typo (e.g. 'IS ISO', 'IEE'); normalised.",
    "suffix": "Designation carries a suffix such as P, T, Supplement or (S&T); kept as part of its identity.",
    "malformed_repaired": "Malformed designation punctuation repaired (e.g. 'IS):7779 ( (Part 1/Sec 1)):1975').",
    "duplicate_year": "Year written twice (e.g. ':2017:2017').",
    "missing_year_colon": "Year not separated by a colon (e.g. '(Part 2/Sec 11)2026').",
    "number_range": "Designation covering a range of numbers (e.g. 'IS 4864 to 4870').",
    "year_in_parentheses": "Year written in parentheses (LIMS style).",
    "unparsed": "Designation that could not be parsed; stored under its whitespace-normalised text.",
    "year_out_of_range": "Designation year outside 1900 to next year.",
    "prefix_assumed": "Bare number read as an Indian Standard because of its context.",
}


@dataclass(frozen=True)
class Finding:
    check: str
    severity: str
    count: int
    examples: list[str] = field(default_factory=list)
    note: str = ""


def _latest_runs(conn: Connection) -> list[dict]:
    runs = schema.ingestion_run
    latest = sa.select(runs.c.source_id, sa.func.max(runs.c.run_id).label("run_id")).group_by(runs.c.source_id).subquery()
    return [
        dict(row)
        for row in conn.execute(sa.select(runs).join(latest, runs.c.run_id == latest.c.run_id)).mappings()
    ]


def _provenance_findings(conn: Connection) -> Finding:
    total = 0
    examples = []
    for name in PROVENANCE_TABLES:
        table = schema.metadata.tables[name]
        missing = conn.execute(
            sa.select(sa.func.count())
            .select_from(table)
            .where(sa.or_(table.c.source_id.is_(None), table.c.source_locator.is_(None), table.c.retrieved_at.is_(None)))
        ).scalar()
        if missing:
            total += missing
            examples.append(f"{name}: {missing}")
    return Finding(
        "missing_provenance",
        "error",
        total,
        examples,
        "Rows without a source, locator or retrieval time. Every record must be traceable to its source.",
    )


def _standard_findings(conn: Connection, today: date) -> list[Finding]:
    standard = schema.standard
    rows = conn.execute(
        sa.select(
            standard.c.std_key,
            standard.c.family_key,
            standard.c.title_clean,
            standard.c.listing_status,
            standard.c.publication_date,
            standard.c.quality_flags,
        ).where(standard.c.is_current.is_(True))
    ).all()

    flag_examples: dict[str, list[str]] = collections.defaultdict(list)
    flag_counts: collections.Counter = collections.Counter()
    families: collections.Counter = collections.Counter()
    titles: dict[str, set[str]] = collections.defaultdict(set)
    ministry_only, future_dates = [], []
    for row in rows:
        for flag in json.loads(row.quality_flags) if row.quality_flags else []:
            flag_counts[flag] += 1
            if len(flag_examples[flag]) < 5:
                flag_examples[flag].append(row.std_key)
        families[row.family_key] += 1
        if row.title_clean:
            titles[norm_match(row.title_clean)].add(row.std_key)
        if row.listing_status == "ministry_export_only":
            ministry_only.append(row.std_key)
        if row.publication_date and row.publication_date > today:
            future_dates.append(row.std_key)

    findings = [
        Finding(
            "ministry_only_standards",
            "info",
            len(ministry_only),
            sorted(ministry_only)[:10],
            "Designations listed in a ministry export but absent from both full exports (often superseded "
            "versions); kept with listing_status 'ministry_export_only' and never shown as current.",
        ),
        Finding(
            "future_publication_dates",
            "warning",
            len(future_dates),
            sorted(future_dates)[:10],
            "Publication dates later than the check date.",
        ),
        Finding(
            "families_with_multiple_versions",
            "info",
            sum(1 for count in families.values() if count > 1),
            sorted(family for family, count in families.items() if count > 1)[:10],
            "Standard families with more than one version in the published list; references without a year "
            "resolve to the latest version and show the others.",
        ),
        Finding(
            "titles_shared_by_multiple_standards",
            "info",
            sum(1 for keys in titles.values() if len(keys) > 1),
            [" / ".join(sorted(keys)) for keys in titles.values() if len(keys) > 1][:5],
            "Identical normalised titles under different designations (revisions, indigenous vs adopted "
            "standards, possible typos). Records are kept separate.",
        ),
    ]
    for check, (severity, note) in _VALUE_GAP_CHECKS.items():
        findings.append(Finding(check, severity, flag_counts.get(check, 0), flag_examples.get(check, []), note))
    for flag, count in sorted(flag_counts.items()):
        if flag in _VALUE_GAP_CHECKS or flag in {"missing_title", "unparsed_publication_date"}:
            continue
        findings.append(
            Finding(
                f"designation_flag:{flag}",
                _DESIGNATION_FLAG_SEVERITY.get(flag, "info"),
                count,
                flag_examples[flag],
                _DESIGNATION_FLAG_NOTES.get(flag, "Designation format irregularity."),
            )
        )
    return findings


def _run_findings(conn: Connection) -> list[Finding]:
    latest = _latest_runs(conn)
    collisions, rejected_examples, failed = [], [], []
    rejected_total = 0
    for run in latest:
        errors = json.loads(run["errors_json"]) if run["errors_json"] else []
        collisions += [error["reason"] for error in errors if "canonical_collision" in (error.get("reason") or "")]
        rejected_total += run["rejected"] or 0
        rejected_examples += [
            f"{run['source_id']}: {error.get('locator')} — {error.get('reason')}" for error in errors if error.get("locator")
        ][:3]
        if run["status"] == "failed":
            failed.append(run["source_id"])
    return [
        Finding(
            "canonical_collisions",
            "error",
            len(collisions),
            collisions[:5],
            "Different raw designations normalising to the same key inside one source; rejected for review, never merged.",
        ),
        Finding(
            "rejected_records",
            "warning",
            rejected_total,
            rejected_examples[:10],
            "Records rejected by the latest run of each source.",
        ),
        Finding(
            "failed_runs",
            "error",
            len(failed),
            failed,
            "Sources whose latest ingestion run failed and was rolled back.",
        ),
    ]


def _classification_findings(conn: Connection) -> Finding:
    links = schema.standard_classification
    standard = schema.standard
    node = schema.classification_node
    orphans = conn.execute(
        sa.select(sa.func.count())
        .select_from(links.join(standard, links.c.standard_id == standard.c.standard_id).join(node, links.c.node_id == node.c.node_id))
        .where(links.c.is_current.is_(True), sa.or_(standard.c.is_current.is_(False), node.c.is_current.is_(False)))
    ).scalar()
    return Finding(
        "orphan_classification_links",
        "warning",
        orphans,
        [],
        "Current classification links pointing to a retired standard or node.",
    )


def run_quality_checks(conn: Connection, today: date | None = None) -> list[Finding]:
    today = today or clock.today()
    return [
        _provenance_findings(conn),
        *_run_findings(conn),
        *_standard_findings(conn, today),
        _classification_findings(conn),
    ]


def write_quality_report(findings: list[Finding], json_path: Path, markdown_path: Path, today: date | None = None) -> None:
    today = today or clock.today()
    json_path = Path(json_path)
    markdown_path = Path(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(
            {"generated_by": "manakmarg.ingest.quality", "checked_on": today.isoformat(), "findings": [asdict(f) for f in findings]},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    severity_order = {"error": 0, "warning": 1, "info": 2}
    lines = [
        "# Data-quality report",
        "",
        f"Checked on {today.isoformat()} by `manakmarg.ingest.quality`. Counts of zero are listed to show what was verified.",
        "",
        "| Check | Severity | Count | Examples | What it means |",
        "|---|---|---:|---|---|",
    ]
    for finding in sorted(findings, key=lambda item: (severity_order.get(item.severity, 3), item.check)):
        examples = "; ".join(finding.examples[:3]).replace("|", "\\|")
        lines.append(f"| {finding.check} | {finding.severity} | {finding.count:,} | {examples} | {finding.note} |")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
