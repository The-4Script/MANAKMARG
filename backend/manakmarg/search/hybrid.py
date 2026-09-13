"""Hybrid product matching (spec §8): identifiers + FTS5 BM25 + LSA vectors + curated synonyms.

The combined score only orders candidate listings. Applicability and compulsory status are decided in
``manakmarg.reasoning`` from the official records; every candidate states how it was matched.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from manakmarg.db import schema
from manakmarg.normalize.text import norm_match
from manakmarg.search import fts_search
from manakmarg.search.fts_search import PRODUCT_STOP_WORDS, stem
from manakmarg.search.resolvers import Resolution, StandardResolver
from manakmarg.search.vectors import VectorIndex

SYNONYMS_PATH = Path(__file__).with_name("synonyms.json")
WEIGHTS = {"bm25": 0.3, "vector": 0.2, "coverage": 0.35, "exact": 0.1, "listing": 0.05}
IDENTIFIER_BONUS = 1.0
MIN_VECTOR_SIMILARITY = 0.2
_LISTING_PRIOR = {"LISTED_COMPULSORY": 1.0, "UPCOMING": 0.8, "NEEDS_VERIFICATION": 0.6, "DENOTIFIED": 0.4, "RESCINDED": 0.4}


@dataclass(frozen=True)
class Synonym:
    terms: tuple[str, ...]
    expands_to: tuple[str, ...]


@dataclass(frozen=True)
class CoverageCandidate:
    coverage_id: int
    product_name: str
    category: str | None
    scheme_id: str | None
    page_kind: str
    listing_status: str
    standard_ref_raw: str | None
    parent_coverage_id: int | None
    score: float
    token_coverage: float
    matched_via: tuple[str, ...]


@dataclass(frozen=True)
class StandardCandidate:
    standard_id: int
    std_key: str
    title: str
    standard_type: str | None
    score: float
    matched_via: tuple[str, ...]


@dataclass(frozen=True)
class ProductMatches:
    query: str
    content_tokens: tuple[str, ...]
    identifiers: tuple[Resolution, ...]
    synonyms_used: tuple[tuple[str, str], ...]
    coverage: list[CoverageCandidate]
    standards: list[StandardCandidate]


@lru_cache(maxsize=4)
def load_synonyms(path: Path = SYNONYMS_PATH) -> tuple[Synonym, ...]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return tuple(
        Synonym(tuple(norm_match(term) for term in item["terms"]), tuple(item["expands_to"])) for item in data["synonyms"]
    )


def content_tokens(text: str | None) -> list[str]:
    tokens: list[str] = []
    for token in norm_match(text).split():
        folded = stem(token)
        if token not in PRODUCT_STOP_WORDS and folded not in tokens:
            tokens.append(folded)
    return tokens


def expand_synonyms(text: str | None) -> list[tuple[str, str]]:
    """(matched term, expansion) pairs for curated synonyms found as whole words in the query."""
    padded = f" {norm_match(text)} "
    used: list[tuple[str, str]] = []
    for synonym in load_synonyms():
        term = next((term for term in synonym.terms if term and f" {term} " in padded), None)
        if term:
            used.extend((term, target) for target in synonym.expands_to)
    return used


def _query_variants(text: str, synonyms: list[tuple[str, str]]) -> list[set[str]]:
    base = content_tokens(text)
    variants = [set(base)] if base else []
    for term, target in synonyms:
        replaced = [token for token in base if token not in set(content_tokens(term))] + content_tokens(target)
        if replaced:
            variants.append(set(replaced))
    return variants


def _coverage_rows(conn: Connection, ids: set[int]):
    table = schema.scheme_coverage
    if not ids:
        return []
    return conn.execute(
        sa.select(
            table.c.coverage_id,
            table.c.product_name,
            table.c.category,
            table.c.product_category,
            table.c.scheme_id,
            table.c.page_kind,
            table.c.listing_status,
            table.c.standard_ref_raw,
            table.c.parent_coverage_id,
        ).where(table.c.coverage_id.in_(sorted(ids)), table.c.is_current.is_(True))
    ).all()


def _linked_coverage(conn: Connection, families: set[str]) -> set[int]:
    if not families:
        return set()
    links = schema.coverage_standard
    rows = conn.execute(sa.select(links.c.coverage_id).where(links.c.family_key.in_(sorted(families))))
    return {row.coverage_id for row in rows}


def find_product_matches(
    conn: Connection,
    text: str,
    *,
    limit: int = 10,
    vectors: dict[str, VectorIndex] | None = None,
    resolver: StandardResolver | None = None,
) -> ProductMatches:
    identifiers = tuple((resolver or StandardResolver(conn)).resolve_text(text))
    synonyms = expand_synonyms(text)
    expanded = " ".join([text, *dict.fromkeys(target for _, target in synonyms)])
    variants = _query_variants(text, synonyms)
    exact_names = {norm_match(text), *(norm_match(target) for _, target in synonyms)}
    synonym_tokens = {term: set(content_tokens(target)) for term, target in synonyms}

    bm25 = {hit.id: hit.score for hit in fts_search.search_coverage(conn, expanded, limit=50)}
    vector_scores: dict[int, float] = {}
    if vectors and "coverage" in vectors:
        vector_scores = {
            int(doc_id): similarity
            for doc_id, similarity in vectors["coverage"].query(expanded, k=50)
            if similarity >= MIN_VECTOR_SIMILARITY
        }
    families = {resolution.family_key for resolution in identifiers if resolution.family_key}
    by_identifier = _linked_coverage(conn, families)
    top_bm25 = max(bm25.values(), default=0.0) or 1.0

    candidates: list[CoverageCandidate] = []
    for row in _coverage_rows(conn, set(bm25) | set(vector_scores) | by_identifier):
        product_tokens = set(content_tokens(f"{row.product_name} {row.category or ''} {row.product_category or ''}"))
        coverage = max((len(variant & product_tokens) / len(variant) for variant in variants), default=0.0)
        if coverage == 0 and row.coverage_id not in bm25 and row.coverage_id not in by_identifier:
            continue  # vector-only neighbour sharing no query word: too weak to show as a candidate
        exact = 1.0 if norm_match(row.product_name) in exact_names else 0.0
        score = (
            WEIGHTS["bm25"] * max(bm25.get(row.coverage_id, 0.0), 0.0) / top_bm25
            + WEIGHTS["vector"] * vector_scores.get(row.coverage_id, 0.0)
            + WEIGHTS["coverage"] * coverage
            + WEIGHTS["exact"] * exact
            + WEIGHTS["listing"] * _LISTING_PRIOR.get(row.listing_status, 0.5)
            + (IDENTIFIER_BONUS if row.coverage_id in by_identifier else 0.0)
        )
        via = []
        if row.coverage_id in by_identifier:
            via.append("standard_reference")
        if row.coverage_id in bm25:
            via.append("full_text")
        if row.coverage_id in vector_scores:
            via.append("vector")
        via += [f"synonym:{term}" for term, tokens in synonym_tokens.items() if tokens & product_tokens]
        candidates.append(
            CoverageCandidate(
                coverage_id=row.coverage_id,
                product_name=row.product_name,
                category=row.category,
                scheme_id=row.scheme_id,
                page_kind=row.page_kind,
                listing_status=row.listing_status,
                standard_ref_raw=row.standard_ref_raw,
                parent_coverage_id=row.parent_coverage_id,
                score=round(score, 6),
                token_coverage=round(coverage, 4),
                matched_via=tuple(dict.fromkeys(via)),
            )
        )
    candidates.sort(key=lambda candidate: (-candidate.score, candidate.coverage_id))

    return ProductMatches(
        query=text,
        content_tokens=tuple(content_tokens(text)),
        identifiers=identifiers,
        synonyms_used=tuple(synonyms),
        coverage=candidates[:limit],
        standards=standard_candidates(conn, expanded, identifiers, limit),
    )


def standard_candidates(conn: Connection, text: str, identifiers: tuple[Resolution, ...], limit: int) -> list[StandardCandidate]:
    scores: dict[int, tuple[float, list[str]]] = {}
    for resolution in identifiers:
        for rank, standard_id in enumerate(resolution.standard_ids):
            score = IDENTIFIER_BONUS * 2 - rank * 0.01
            if standard_id not in scores or scores[standard_id][0] < score:
                scores[standard_id] = (score, [f"identifier:{resolution.kind}"])
    hits = fts_search.search_standards(conn, text, limit=limit)
    top = max((hit.score for hit in hits), default=0.0) or 1.0
    for hit in hits:
        if hit.id not in scores:
            scores[hit.id] = (max(hit.score, 0.0) / top, ["full_text"])
    if not scores:
        return []
    table = schema.standard
    rows = {
        row.standard_id: row
        for row in conn.execute(
            sa.select(table.c.standard_id, table.c.std_key, table.c.title_clean, table.c.title, table.c.standard_type).where(
                table.c.standard_id.in_(sorted(scores))
            )
        )
    }
    candidates = [
        StandardCandidate(
            standard_id=standard_id,
            std_key=rows[standard_id].std_key,
            title=rows[standard_id].title_clean or rows[standard_id].title,
            standard_type=rows[standard_id].standard_type,
            score=round(score, 6),
            matched_via=tuple(via),
        )
        for standard_id, (score, via) in scores.items()
        if standard_id in rows
    ]
    candidates.sort(key=lambda candidate: (-candidate.score, candidate.std_key))
    return candidates[:limit]
