"""Turns reasoning results (dataclasses, rows, dates) into JSON-ready structures with evidence attached."""

import dataclasses
from collections.abc import Mapping
from datetime import date, datetime

from manakmarg.reasoning.evidence import EvidenceBuilder


def plain(value):
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: plain(getattr(value, field.name))
            for field in dataclasses.fields(value)
            if not isinstance(getattr(value, field.name), EvidenceBuilder)
        }
    if isinstance(value, EvidenceBuilder):
        return None
    if isinstance(value, Mapping):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [plain(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def with_evidence(result, evidence: EvidenceBuilder | None = None, **extra) -> dict:
    body = plain(result)
    if not isinstance(body, dict):
        body = {"result": body}
    evidence = evidence or getattr(result, "evidence", None)
    if isinstance(evidence, EvidenceBuilder):
        body["evidence"] = [item.to_dict() for item in evidence.items]
        body["sources"] = evidence.sources()
    body.update(extra)
    return body
