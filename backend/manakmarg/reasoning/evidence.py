"""Evidence assembly (spec §9.5).

Every statement in an answer cites evidence ids (``E1``, ``E2`` …). An evidence item points at a record: its
source, authority, official URL, locator inside the source, retrieval time and a short snippet (at most 300
characters). Items produced by MANAK MARG's own cross-checks carry the authority ``derived`` so they are never
mistaken for an official statement.
"""

from dataclasses import asdict, dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from manakmarg.db import schema
from manakmarg.normalize.text import snippet as short_snippet

SNIPPET_LIMIT = 300


@dataclass(frozen=True)
class Evidence:
    id: str
    kind: str
    title: str
    snippet: str | None
    source_id: str
    source_name: str
    authority: str
    url: str | None
    locator: str | None
    retrieved_at: str | None
    page: int | None = None
    clause: str | None = None
    record_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def url_from_locator(locator: str | None) -> str | None:
    if locator and locator.startswith(("http://", "https://")):
        return locator.split("#", 1)[0]
    return None


class EvidenceBuilder:
    """Collects evidence for one answer; the same record cited twice gets the same id."""

    def __init__(self, conn: Connection):
        source = schema.source
        self._sources = {
            row.source_id: row
            for row in conn.execute(sa.select(source.c.source_id, source.c.name, source.c.authority, source.c.url, source.c.as_of_label))
        }
        self._items: list[Evidence] = []
        self._ids: dict[tuple, str] = {}

    def add(
        self,
        *,
        kind: str,
        record_id,
        title: str,
        source_id: str,
        snippet: str | None = None,
        url: str | None = None,
        locator: str | None = None,
        retrieved_at: str | None = None,
        page: int | None = None,
        clause: str | None = None,
        authority: str | None = None,
    ) -> str:
        key = (kind, None if record_id is None else str(record_id), page, clause)
        if key in self._ids:
            return self._ids[key]
        source = self._sources.get(source_id)
        evidence = Evidence(
            id=f"E{len(self._items) + 1}",
            kind=kind,
            title=title,
            snippet=short_snippet(snippet, SNIPPET_LIMIT) if snippet else None,
            source_id=source_id,
            source_name=source.name if source else source_id,
            authority=authority or (source.authority if source else "unknown"),
            url=url or url_from_locator(locator) or (source.url if source else None),
            locator=locator,
            retrieved_at=retrieved_at,
            page=page,
            clause=clause,
            record_id=None if record_id is None else str(record_id),
        )
        self._items.append(evidence)
        self._ids[key] = evidence.id
        return evidence.id

    def add_record(
        self,
        kind: str,
        row,
        *,
        record_id,
        title: str,
        snippet: str | None = None,
        url: str | None = None,
        page: int | None = None,
        clause: str | None = None,
        prefix: str = "",
    ) -> str:
        """Evidence from a mapping row with provenance columns (optionally under a column-name prefix)."""
        return self.add(
            kind=kind,
            record_id=record_id,
            title=title,
            source_id=row[f"{prefix}source_id"],
            snippet=snippet,
            url=url,
            locator=row[f"{prefix}source_locator"],
            retrieved_at=row[f"{prefix}retrieved_at"],
            page=page,
            clause=clause,
        )

    def get(self, evidence_id: str) -> Evidence:
        return next(item for item in self._items if item.id == evidence_id)

    @property
    def items(self) -> list[Evidence]:
        return list(self._items)

    def ids(self) -> set[str]:
        return {item.id for item in self._items}

    def sources(self) -> list[dict]:
        """One entry per source cited: name, authority, official URL, evidence ids and retrieval times."""
        rollup: dict[str, dict] = {}
        for item in self._items:
            source = self._sources.get(item.source_id)
            entry = rollup.setdefault(
                item.source_id,
                {
                    "source_id": item.source_id,
                    "name": item.source_name,
                    "authority": source.authority if source else item.authority,
                    "url": source.url if source else item.url,
                    "as_of": source.as_of_label if source and source.as_of_label else None,
                    "evidence_ids": [],
                    "retrieved_at": [],
                },
            )
            entry["evidence_ids"].append(item.id)
            if item.retrieved_at and item.retrieved_at not in entry["retrieved_at"]:
                entry["retrieved_at"].append(item.retrieved_at)
        return list(rollup.values())
