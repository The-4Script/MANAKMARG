"""Deterministic requirement-vs-value comparison (spec §11, steps 5–7).

Statuses:

* ``PASS`` — a confidently matched value satisfies the requirement after unit conversion.
* ``POTENTIAL_GAP`` — a declared (datasheet) value violates the requirement, or the parameter match is uncertain.
* ``FAIL`` — a measured (test report) value violates the requirement: a non-conformity indication, not a verdict.
* ``UNKNOWN`` — the units cannot be compared (different dimensions or unrecognised).
* ``INSUFFICIENT_EVIDENCE`` — no product value was found for the requirement.
"""

import difflib
import re
from dataclasses import dataclass

from manakmarg.documents.requirements import ProductValue, Requirement
from manakmarg.documents.units import lookup_unit, to_base
from manakmarg.search.fts_search import stem

PASS = "PASS"
POTENTIAL_GAP = "POTENTIAL_GAP"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

CONFIDENT_MATCH = 0.75
MIN_MATCH = 0.5
_ROLE_PRIORITY = {"test_report": 0, "datasheet": 1}
_STOP = frozenset({"the", "of", "a", "an", "and", "for", "value", "product", "declared", "measured", "observed", "result", "total", "shall", "be"})


@dataclass(frozen=True)
class GapRow:
    requirement: Requirement
    value: ProductValue | None
    status: str
    code: str
    similarity: float | None
    compared: dict | None
    explanation: str


def _tokens(text: str) -> set[str]:
    return {stem(token) for token in re.findall(r"[a-z0-9]+", text.lower()) if token not in _STOP}


def parameter_similarity(first: str, second: str) -> float:
    a, b = _tokens(first), _tokens(second)
    if not a or not b:
        return 0.0
    jaccard = len(a & b) / len(a | b)
    ratio = difflib.SequenceMatcher(None, " ".join(sorted(a)), " ".join(sorted(b))).ratio()
    return round(max(jaccard, ratio * 0.9), 3)


def _unit_compatible(requirement: Requirement, value: ProductValue) -> bool:
    if requirement.unit is None and value.unit is None:
        return (requirement.unit_raw or "").lower() == (value.unit_raw or "").lower()
    first, second = lookup_unit(requirement.unit), lookup_unit(value.unit)
    return bool(first and second and first[1] == second[1])


def _satisfied(requirement: Requirement, low: float, high: float) -> bool:
    if requirement.operator == "min":
        return low >= requirement.value
    if requirement.operator == "max":
        return high <= requirement.value
    if requirement.operator == "range":
        return low >= requirement.value and high <= (requirement.value_max if requirement.value_max is not None else requirement.value)
    return abs(low - requirement.value) < 1e-9


def _limit_text(requirement: Requirement) -> str:
    unit = requirement.unit or requirement.unit_raw or ""
    if requirement.operator == "range":
        return f"{requirement.value:g}–{requirement.value_max:g} {unit}".strip()
    symbol = {"min": "≥", "max": "≤"}.get(requirement.operator, "=")
    return f"{symbol} {requirement.value:g} {unit}".strip()


def compare(requirement: Requirement, values: list[ProductValue]) -> GapRow:
    scored = sorted(
        ((parameter_similarity(requirement.parameter, value.parameter), value) for value in values),
        key=lambda item: (-item[0], _ROLE_PRIORITY.get(item[1].role, 9)),
    )
    candidates = [(score, value) for score, value in scored if score >= MIN_MATCH]
    if not candidates:
        return GapRow(requirement, None, INSUFFICIENT_EVIDENCE, "no_value", None, None, "No matching product value was found in the datasheet or test report.")
    best_score = candidates[0][0]
    close = [item for item in candidates if best_score - item[0] <= 0.05]
    similarity, value = min(close, key=lambda item: _ROLE_PRIORITY.get(item[1].role, 9))

    if not _unit_compatible(requirement, value):
        return GapRow(
            requirement,
            value,
            UNKNOWN,
            "units_not_comparable",
            similarity,
            None,
            f"Units cannot be compared ({requirement.unit or requirement.unit_raw or 'no unit'} vs {value.unit or value.unit_raw or 'no unit'}).",
        )
    low, low_unit = to_base(value.value, value.unit)
    high, _ = to_base(value.value_max if value.value_max is not None else value.value, value.unit)
    limit, limit_unit = to_base(requirement.value, requirement.unit)
    limit_max = to_base(requirement.value_max, requirement.unit)[0] if requirement.value_max is not None else None
    normalised = Requirement(requirement.parameter, requirement.operator, limit, limit_max, requirement.unit, requirement.unit_raw, requirement.clause, requirement.page, requirement.raw_text, requirement.document)
    compared = {"value_low": low, "value_high": high, "limit": limit, "limit_max": limit_max, "base_unit": low_unit or limit_unit or requirement.unit_raw}
    ok = _satisfied(normalised, low, high)
    shown = f"{value.value:g}{'–' + format(value.value_max, 'g') if value.value_max is not None else ''} {value.unit or value.unit_raw or ''}".strip()

    if ok and similarity >= CONFIDENT_MATCH:
        return GapRow(requirement, value, PASS, "satisfied", similarity, compared, f"{shown} meets {_limit_text(requirement)}.")
    if ok:
        return GapRow(requirement, value, POTENTIAL_GAP, "uncertain_match", similarity, compared, f"{shown} would meet {_limit_text(requirement)}, but confirm that “{value.parameter}” is the same parameter.")
    if value.role == "test_report":
        return GapRow(requirement, value, FAIL, "measured_violation", similarity, compared, f"Measured {shown} does not meet {_limit_text(requirement)}.")
    return GapRow(requirement, value, POTENTIAL_GAP, "declared_violation", similarity, compared, f"Declared {shown} does not meet {_limit_text(requirement)}.")


def compare_all(requirements: list[Requirement], values: list[ProductValue]) -> list[GapRow]:
    return [compare(requirement, values) for requirement in requirements]
