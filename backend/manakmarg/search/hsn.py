"""Local HSN lookup over the supplied HSN master. No external service is involved.

* A code query (2-8 digits, spaces or dots allowed) returns the exact code and the codes filed under it.
* A text query uses SQLite FTS5 (BM25) and ranks by how many of the user's words the official description contains,
  with a small preference for the more specific 8-digit codes.
* Parent headings are shown only when those shorter codes are themselves rows of the dataset.

Results are classification candidates for the user to verify; they never decide GST, customs or BIS obligations.
"""

import re
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from manakmarg.db import schema
from manakmarg.normalize.text import norm_match
from manakmarg.search import fts_search
from manakmarg.search.fts_search import PRODUCT_STOP_WORDS, stem

SOURCE_ID = "hsn_master_workbook"
HSN_WORDS = frozenset({"hsn", "hs", "code", "codes", "tariff", "number", "classification", "एचएसएन", "कोड"})
_STOP = PRODUCT_STOP_WORDS | HSN_WORDS | frozenset({"kya", "hai", "ka", "ke", "ki", "batao", "find", "show", "tell"})
_CODE_ONLY = re.compile(r"[0-9][0-9 .]*")
_CODE_IN_TEXT = re.compile(r"(?<![\w.])(\d{2,8})(?![\w.])")
_MALFORMED = re.compile(r"(?=\S*\d)(?=\S*[A-Za-z])[0-9A-Za-z]{3,10}")
# A text match must contain every product word: a partial match ("PVC resin" for "PVC pipes") is not a plausible code.
MIN_COVERAGE = 1.0


@dataclass(frozen=True)
class HsnMatch:
    hsn_id: int
    code: str
    code_digits: str
    description: str
    match: str  # exact | within_code | text
    coverage: float
    score: float
    parents: tuple[dict, ...]
    source_id: str
    source_locator: str | None
    retrieved_at: str | None


@dataclass
class HsnSearch:
    query: str
    mode: str  # code | text | invalid | empty
    matches: list[HsnMatch]
    notes: list[str] = field(default_factory=list)


def _tokens(text: str) -> list[str]:
    return [stem(token) for token in norm_match(text).split() if token not in _STOP and not token.isdigit()]


def query_words(text: str | None) -> str:
    """The product words of an HSN question, without "HSN", "code" and question words."""
    return " ".join(token for token in norm_match(text).split() if token not in _STOP)


def _rows(conn: Connection, condition) -> list:
    table = schema.hsn_code
    return conn.execute(sa.select(table).where(table.c.is_current.is_(True), condition)).mappings().all()


def _parents(conn: Connection, digits_list: list[str]) -> dict[str, tuple[dict, ...]]:
    """Shorter codes of the dataset that contain each code. Rows whose description is only the placeholder "OMITTED"
    carry no heading text and are not shown as context (the row itself stays searchable, verbatim)."""
    prefixes = {digits[:size] for digits in digits_list for size in (2, 4, 6) if size < len(digits)}
    if not prefixes:
        return {}
    table = schema.hsn_code
    known = {
        row["code_digits"]: row
        for row in _rows(conn, table.c.code_digits.in_(sorted(prefixes)))
        if row["description"].strip().upper() != "OMITTED"
    }
    return {
        digits: tuple({"code": known[digits[:size]]["code"], "description": known[digits[:size]]["description"]} for size in (2, 4, 6) if size < len(digits) and digits[:size] in known)
        for digits in digits_list
    }


def _match(row, kind: str, coverage: float, score: float, parents: dict) -> HsnMatch:
    return HsnMatch(
        hsn_id=row["hsn_id"],
        code=row["code"],
        code_digits=row["code_digits"],
        description=row["description"],
        match=kind,
        coverage=round(coverage, 4),
        score=round(score, 6),
        parents=parents.get(row["code_digits"], ()),
        source_id=row["source_id"],
        source_locator=row["source_locator"],
        retrieved_at=row["retrieved_at"],
    )


def search_hsn(conn: Connection, query: str | None, *, limit: int = 8) -> HsnSearch:
    text = (query or "").strip()
    if not text:
        return HsnSearch(text, "empty", [])
    table = schema.hsn_code
    compact = text.replace(" ", "").replace(".", "")
    if _CODE_ONLY.fullmatch(text):
        if not 2 <= len(compact) <= 8:
            return HsnSearch(text, "invalid", [], ["hsn_code_length"])
        exact = _rows(conn, table.c.code_digits == compact)
        within = conn.execute(
            sa.select(table)
            .where(table.c.is_current.is_(True), table.c.code_digits.like(f"{compact}%"), table.c.code_digits != compact)
            .order_by(table.c.code_length, table.c.code_digits)
            .limit(limit)
        ).mappings().all()
        rows = list(exact) + list(within)
        parents = _parents(conn, [row["code_digits"] for row in rows])
        matches = [_match(row, "exact", 1.0, 1.0, parents) for row in exact] + [_match(row, "within_code", 1.0, 0.5, parents) for row in within]
        return HsnSearch(text, "code", matches[:limit], [] if matches else ["hsn_code_not_found"])
    if _MALFORMED.fullmatch(compact) and not query_words(text).replace(" ", "").isalpha():
        return HsnSearch(text, "invalid", [], ["hsn_code_malformed"])

    wanted = list(dict.fromkeys(_tokens(text)))
    if not wanted:
        return HsnSearch(text, "empty", [])
    hits = fts_search.search(conn, "hsn", " ".join(wanted), limit=80, stop_words=_STOP)
    if not hits:
        return HsnSearch(text, "text", [], ["hsn_no_match"])
    top = max(hit.score for hit in hits) or 1.0
    by_id = {row["hsn_id"]: row for row in _rows(conn, table.c.hsn_id.in_([hit.id for hit in hits]))}
    phrase = " ".join(wanted)
    scored = []
    for hit in hits:
        row = by_id.get(hit.id)
        if row is None:
            continue
        description_words = [stem(token) for token in norm_match(row["description"]).split()]
        description_tokens = set(description_words)
        coverage = sum(1 for token in wanted if token in description_tokens or any(word.startswith(token) for word in description_tokens)) / len(wanted)
        if coverage < MIN_COVERAGE:
            continue
        # The words in the user's order ("copper wire" → "COPPER WIRE") and a short, specific description rank first.
        in_order = 0.25 if f" {phrase} " in f" {' '.join(description_words)} " else 0.0
        brevity = 0.1 / max(len(description_words), 1)
        specificity = {8: 0.05, 6: 0.03, 4: 0.02}.get(row["code_length"], 0.0)
        scored.append((0.35 * max(hit.score, 0.0) / top + in_order + brevity + specificity, coverage, row))
    scored.sort(key=lambda item: (-item[0], item[2]["code_digits"]))
    chosen = scored[:limit]
    parents = _parents(conn, [row["code_digits"] for _, _, row in chosen])
    matches = [_match(row, "text", coverage, score, parents) for score, coverage, row in chosen]
    return HsnSearch(text, "text", matches, [] if matches else ["hsn_no_match"])


def code_in_text(text: str | None) -> str | None:
    match = _CODE_IN_TEXT.search(text or "")
    return match.group(1) if match else None
