"""Evidence assembly (spec §9.5).

Every statement in an answer cites evidence ids (``E1``, ``E2`` …). An evidence item points at a record: its
source, authority, official URL, locator inside the source, retrieval time and a short snippet (at most 300
characters). Items produced by MANAK MARG's own cross-checks carry the authority ``derived`` so they are never
mistaken for an official statement.
"""

from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from manakmarg.db import schema
from manakmarg.normalize.text import snippet as short_snippet

SNIPPET_LIMIT = 300

# Hosts whose pages are the official place to verify a record. An action link is offered only for these; the URL is
# always the one stored with the record or its registered source, never constructed.
OFFICIAL_HOSTS = ("bis.gov.in", "manakonline.in", "egazette.gov.in", "egazette.nic.in")
ACTION_BY_KIND = {
    "regulatory_order": "view_notification",
    "gazette_cross_check": "view_notification",
    "coverage_listing": "verify_on_bis",
    "certification_scheme": "verify_on_bis",
    "standard": "view_standard_portal",
    "guideline_section": "view_product_manual",
    "product_guideline": "view_product_manual",
    "lab_scope": "view_lims",
    "laboratory": "view_lims",
    "ahc": "view_hallmarking_source",
    "ahc_status_event": "view_hallmarking_source",
    "hallmarking_district": "view_hallmarking_source",
    "scheme_document": "open_official_document",
    "document_chunk": "open_official_document",
    "faq": "view_official_source",
    "process_step": "view_official_source",
}


def official_action(kind: str, url: str | None, authority: str | None) -> str | None:
    """The verification action for an evidence item, or ``None`` when its URL is not an official BIS/Gazette page."""
    if not url or authority != "official_primary":
        return None
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not any(host == allowed or host.endswith(f".{allowed}") for allowed in OFFICIAL_HOSTS):
        return None
    return ACTION_BY_KIND.get(kind, "view_official_source")


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
    action: str | None = None

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
        resolved_authority = authority or (source.authority if source else "unknown")
        resolved_url = url or url_from_locator(locator) or (source.url if source else None) or None
        evidence = Evidence(
            id=f"E{len(self._items) + 1}",
            kind=kind,
            title=title,
            snippet=short_snippet(snippet, SNIPPET_LIMIT) if snippet else None,
            source_id=source_id,
            source_name=source.name if source else source_id,
            authority=resolved_authority,
            url=resolved_url,
            locator=locator,
            retrieved_at=retrieved_at,
            page=page,
            clause=clause,
            record_id=None if record_id is None else str(record_id),
            action=official_action(kind, resolved_url, resolved_authority),
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
