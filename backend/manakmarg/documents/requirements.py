"""Requirement and product-value extraction from uploaded documents (spec §11, steps 3–4).

Requirements are read only from documents the user marked as a *requirement source* and only where the text states
a numeric limit ("shall be not less than 50 mm", "maximum 1.5 mm", "≥ 0.5 mm", a Min/Max table row). Nothing is
generated. Product values are read from datasheets and test reports as "parameter: value unit" statements or table
rows. Every item keeps its document, page, clause (when printed) and the exact source line.
"""

import re
from dataclasses import dataclass

from manakmarg.documents.extract import ExtractedDoc
from manakmarg.documents.units import NUMBER, UNIT_TOKEN, lookup_unit
from manakmarg.normalize.text import clean_ws

MIN_WORDS = r"(?:shall\s+(?:be\s+)?)?(?:not\s+less\s+than|at\s+least|minimum(?:\s+of)?|min\.?|no\s+less\s+than|≥|>=)"
MAX_WORDS = r"(?:shall\s+(?:be\s+)?)?(?:not\s+more\s+than|shall\s+not\s+exceed|not\s+exceeding|maximum(?:\s+of)?|max\.?|up\s+to|≤|<=)"
RANGE_WORDS = r"(?:shall\s+(?:be\s+)?)?(?:between|from|within)?"

_UNIT = rf"(?P<unit>{UNIT_TOKEN})?"
_MIN = re.compile(rf"^(?P<param>.+?)\s*[:,-]?\s*{MIN_WORDS}\s*(?P<value>{NUMBER})\s*{_UNIT}", re.IGNORECASE)
_MAX = re.compile(rf"^(?P<param>.+?)\s*[:,-]?\s*{MAX_WORDS}\s*(?P<value>{NUMBER})\s*{_UNIT}", re.IGNORECASE)
_RANGE = re.compile(
    rf"^(?P<param>.+?)\s*[:,-]?\s*{RANGE_WORDS}\s*(?P<low>{NUMBER})\s*(?P<unit_low>{UNIT_TOKEN})?\s*(?:and|to|–|—|-)\s*(?P<high>{NUMBER})\s*{_UNIT}",
    re.IGNORECASE,
)
_VALUE = re.compile(rf"^(?P<param>[A-Za-z][^:=|]{{1,90}}?)\s*(?:[:=]|\.{{3,}}|\s-\s)\s*(?P<value>{NUMBER})\s*(?:(?:to|–|—|-)\s*(?P<high>{NUMBER})\s*)?{_UNIT}\s*(?P<rest>.*)$")
_CLAUSE = re.compile(r"^(?P<clause>\d+(?:\.\d+){0,4})\.?\s+(?P<rest>\S.*)$")
_TABLE_LABEL = re.compile(r"^(?P<label>(?:Table|Annex)\s+[A-Z0-9]+)\b", re.IGNORECASE)
_PARAM_NOISE = re.compile(r"^(?:the|a|an)\s+|\s+(?:of\s+the\s+(?:product|article|item))$|\s+shall(?:\s+be)?$|\s+(?:is|are)$", re.IGNORECASE)
_REQUIREMENT_HINT = re.compile(r"\bshall\b|\bminimum\b|\bmaximum\b|\bmin\.?\b|\bmax\.?\b|not\s+(?:less|more)\s+than|≥|≤|>=|<=|\bbetween\b", re.IGNORECASE)
_HEADER_WORDS = {"parameter", "characteristic", "property", "requirement", "test", "description", "item"}


@dataclass(frozen=True)
class Requirement:
    parameter: str
    operator: str
    value: float
    value_max: float | None
    unit: str | None
    unit_raw: str | None
    clause: str | None
    page: int
    raw_text: str
    document: str


@dataclass(frozen=True)
class ProductValue:
    parameter: str
    value: float
    value_max: float | None
    unit: str | None
    unit_raw: str | None
    page: int
    raw_text: str
    document: str
    role: str


def _number(text: str) -> float:
    return float(text.replace(",", "."))


def _parameter(text: str) -> str:
    value = clean_ws(text).strip(" :,-–—")
    for _ in range(3):
        value = _PARAM_NOISE.sub("", value).strip(" :,-–—")
    return value


def _unit(raw: str | None) -> tuple[str | None, str | None]:
    raw = (raw or "").strip() or None
    found = lookup_unit(raw)
    return (found[0] if found else None), raw


def _requirement_from_line(line: str, clause: str | None, page: int, document: str) -> Requirement | None:
    for operator, pattern in (("range", _RANGE), ("min", _MIN), ("max", _MAX)):
        match = pattern.match(line)
        if not match:
            continue
        parameter = _parameter(match.group("param"))
        if len(parameter) < 3 or parameter.lower() in {"shall", "value", "it"}:
            continue
        if operator == "range":
            unit, unit_raw = _unit(match.group("unit") or match.group("unit_low"))
            low, high = _number(match.group("low")), _number(match.group("high"))
            if high < low:
                continue
            return Requirement(parameter, "range", low, high, unit, unit_raw, clause, page, line, document)
        unit, unit_raw = _unit(match.group("unit"))
        return Requirement(parameter, operator, _number(match.group("value")), None, unit, unit_raw, clause, page, line, document)
    return None


def extract_requirements(doc: ExtractedDoc) -> list[Requirement]:
    found: list[Requirement] = []
    for page in doc.pages:
        clause = None
        for line in page.lines:
            clause_match = _CLAUSE.match(line)
            text = line
            if clause_match:
                clause, text = clause_match.group("clause"), clause_match.group("rest")
            elif (label := _TABLE_LABEL.match(line)) is not None:
                clause = label.group("label")
            if not _REQUIREMENT_HINT.search(text):
                continue
            requirement = _requirement_from_line(text, clause, page.number, doc.filename)
            if requirement:
                found.append(requirement)
    found.extend(_table_requirements(doc))
    return found


def _column(header: list[str], *names: str) -> int | None:
    for index, cell in enumerate(header):
        words = set(re.findall(r"[a-z]+", cell.lower()))
        if words & set(names):
            return index
    return None


def _table_requirements(doc: ExtractedDoc) -> list[Requirement]:
    found: list[Requirement] = []
    for table in doc.tables:
        if len(table.rows) < 2:
            continue
        header = [cell.lower() for cell in table.rows[0]]
        min_index, max_index = _column(header, "min", "minimum"), _column(header, "max", "maximum")
        if min_index is None and max_index is None:
            continue
        unit_index = _column(header, "unit", "units")
        clause_index = _column(header, "clause", "cl")
        for row in table.rows[1:]:
            cells = list(row) + [""] * len(header)
            parameter = _parameter(cells[0])
            if not parameter or parameter.lower() in _HEADER_WORDS:
                continue
            unit_cell = cells[unit_index] if unit_index is not None else ""
            low = re.match(rf"\s*(?P<value>{NUMBER})\s*(?P<unit>{UNIT_TOKEN})?", cells[min_index]) if min_index is not None else None
            high = re.match(rf"\s*(?P<value>{NUMBER})\s*(?P<unit>{UNIT_TOKEN})?", cells[max_index]) if max_index is not None else None
            if not low and not high:
                continue
            unit, unit_raw = _unit(unit_cell or (low or high).group("unit"))
            clause = cells[clause_index] if clause_index is not None and cells[clause_index] else f"table (page {table.page})"
            raw = " | ".join(cell for cell in row if cell)
            if low and high:
                found.append(Requirement(parameter, "range", _number(low.group("value")), _number(high.group("value")), unit, unit_raw, clause, table.page, raw, doc.filename))
            elif low:
                found.append(Requirement(parameter, "min", _number(low.group("value")), None, unit, unit_raw, clause, table.page, raw, doc.filename))
            else:
                found.append(Requirement(parameter, "max", _number(high.group("value")), None, unit, unit_raw, clause, table.page, raw, doc.filename))
    return found


def extract_values(doc: ExtractedDoc, role: str) -> list[ProductValue]:
    found: list[ProductValue] = []
    for page in doc.pages:
        for line in page.lines:
            text = _CLAUSE.match(line).group("rest") if _CLAUSE.match(line) else line
            match = _VALUE.match(text)
            if not match or _REQUIREMENT_HINT.search(match.group("param")):
                continue
            unit, unit_raw = _unit(match.group("unit"))
            high = _number(match.group("high")) if match.group("high") else None
            found.append(ProductValue(_parameter(match.group("param")), _number(match.group("value")), high, unit, unit_raw, page.number, line, doc.filename, role))
    for table in doc.tables:
        if len(table.rows) < 2:
            continue
        header = [cell.lower() for cell in table.rows[0]]
        value_index = _column(header, "result", "results", "observed", "measured", "value", "declared", "observation")
        unit_index = _column(header, "unit", "units")
        if value_index is None:
            continue
        for row in table.rows[1:]:
            cells = list(row) + [""] * len(header)
            parameter = _parameter(cells[0])
            match = re.match(rf"\s*(?P<value>{NUMBER})\s*(?:(?:to|–|—|-)\s*(?P<high>{NUMBER})\s*)?(?P<unit>{UNIT_TOKEN})?", cells[value_index])
            if not parameter or not match or parameter.lower() in _HEADER_WORDS:
                continue
            unit, unit_raw = _unit((cells[unit_index] if unit_index is not None else "") or match.group("unit"))
            high = _number(match.group("high")) if match.group("high") else None
            found.append(ProductValue(parameter, _number(match.group("value")), high, unit, unit_raw, table.page, " | ".join(cell for cell in row if cell), doc.filename, role))
    return found
