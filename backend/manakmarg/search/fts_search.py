"""FTS5 BM25 search over the normalized tables (spec §8).

Scores only order candidates; status and applicability are decided elsewhere by deterministic rules. User text
is reduced to quoted FTS5 terms, so punctuation in a query (``IS 2062:2011``, quotes, hyphens) can never be read
as FTS5 syntax.
"""

import re
from dataclasses import dataclass

from sqlalchemy.engine import Connection

from manakmarg.normalize.text import clean_ws

_TOKEN = re.compile(r"\w+", re.UNICODE)

GENERAL_STOP_WORDS = frozenset(
    """a an and are as at be by can could do does for from how i if in is it its me my of on or our should so
    than that the their then there these they this those to was we were what when where which who why will with
    would you your""".split()
)
PRODUCT_STOP_WORDS = GENERAL_STOP_WORDS | frozenset(
    """applicable apply bis certificate certification certified compulsory control get import importing india indian
    licence license make making mandatory manufacture manufacturer manufacturing need needed order product products
    qco quality require required requirement requirements sell selling specification standard standards want""".split()
)


@dataclass(frozen=True)
class Hit:
    kind: str
    id: int
    score: float
    title: str
    snippet: str | None = None


def stem(token: str) -> str:
    """Light plural folding used on both query and record tokens (utensils → utensil, batteries → battery)."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith(("sses", "xes", "zes", "ches", "shes")):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def query_tokens(text: str | None, stop_words: frozenset[str] = GENERAL_STOP_WORDS) -> list[str]:
    tokens: list[str] = []
    for token in _TOKEN.findall(clean_ws(text).lower()):
        if token not in stop_words and token not in tokens:
            tokens.append(token)
    return tokens


def _term(token: str) -> str:
    if token.isdigit():
        return f'"{token}"'
    base = stem(token)
    if base.endswith("y") and len(base) > 4:
        base = base[:-1]
    return f'"{base}"*' if len(base) >= 3 else f'"{token}"'


def fts_query(text: str | None, *, mode: str = "any", stop_words: frozenset[str] = GENERAL_STOP_WORDS) -> str:
    """FTS5 MATCH expression of quoted terms joined with OR (``any``) or AND (``all``); empty if no terms."""
    terms = [_term(token) for token in query_tokens(text, stop_words)]
    return (" AND " if mode == "all" else " OR ").join(terms)


_SQL = {
    "standard": """
        SELECT s.standard_id, -bm25(standard_fts, 8.0, 8.0, 4.0, 1.0, 0.2),
               s.std_key || ' — ' || COALESCE(s.title_clean, s.title), snippet(standard_fts, 3, '', '', '…', 16)
          FROM standard_fts JOIN standard s ON s.standard_id = standard_fts.rowid
         WHERE standard_fts MATCH ? ORDER BY 2 DESC LIMIT ?""",
    "coverage": """
        SELECT c.coverage_id, -bm25(coverage_fts, 6.0, 1.5, 0.3, 1.5, 3.0, 0.8), c.product_name,
               snippet(coverage_fts, 0, '', '', '…', 16)
          FROM coverage_fts JOIN scheme_coverage c ON c.coverage_id = coverage_fts.rowid
         WHERE coverage_fts MATCH ? ORDER BY 2 DESC LIMIT ?""",
    "guideline": """
        SELECT g.guideline_id, -bm25(guideline_fts, 3.0, 4.0), g.is_ref_raw || ' — ' || g.title, NULL
          FROM guideline_fts JOIN product_guideline g ON g.guideline_id = guideline_fts.rowid
         WHERE guideline_fts MATCH ? ORDER BY 2 DESC LIMIT ?""",
    "faq": """
        SELECT f.faq_id, -bm25(faq_fts, 4.0, 1.0, 0.5), f.question, snippet(faq_fts, 1, '', '', '…', 24)
          FROM faq_fts JOIN faq f ON f.faq_id = faq_fts.rowid
         WHERE faq_fts MATCH ? ORDER BY 2 DESC LIMIT ?""",
    "chunk": """
        SELECT c.chunk_id, -bm25(chunk_fts, 2.0, 1.0), COALESCE(d.title, d.url), snippet(chunk_fts, 1, '', '', '…', 24)
          FROM chunk_fts JOIN document_chunk c ON c.chunk_id = chunk_fts.rowid
          JOIN document d ON d.document_id = c.document_id
         WHERE chunk_fts MATCH ? ORDER BY 2 DESC LIMIT ?""",
    "lab": """
        SELECT l.lab_id, -bm25(lab_fts, 4.0, 1.0, 3.0, 3.0, 2.0), l.name, NULL
          FROM lab_fts JOIN laboratory l ON l.lab_id = lab_fts.rowid
         WHERE lab_fts MATCH ? ORDER BY 2 DESC LIMIT ?""",
    "ahc": """
        SELECT a.ahc_id, -bm25(ahc_fts, 4.0, 1.0, 3.0, 2.0), a.name, NULL
          FROM ahc_fts JOIN ahc a ON a.ahc_id = ahc_fts.rowid
         WHERE ahc_fts MATCH ? ORDER BY 2 DESC LIMIT ?""",
}


def _run(conn: Connection, kind: str, match: str, limit: int) -> list[Hit]:
    if not match:
        return []
    rows = conn.exec_driver_sql(_SQL[kind], (match, limit)).all()
    return [Hit(kind, int(row[0]), float(row[1]), row[2], row[3]) for row in rows]


def search(
    conn: Connection, kind: str, text: str | None, *, limit: int = 20, stop_words: frozenset[str] = GENERAL_STOP_WORDS
) -> list[Hit]:
    """Records containing every query term first, then records containing any of them."""
    strict = fts_query(text, mode="all", stop_words=stop_words)
    loose = fts_query(text, mode="any", stop_words=stop_words)
    hits = _run(conn, kind, strict, limit)
    if loose != strict and len(hits) < limit:
        seen = {hit.id for hit in hits}
        hits += [hit for hit in _run(conn, kind, loose, limit) if hit.id not in seen][: limit - len(hits)]
    return hits


def search_standards(conn: Connection, text: str | None, *, limit: int = 20) -> list[Hit]:
    return search(conn, "standard", text, limit=limit, stop_words=PRODUCT_STOP_WORDS)


def search_coverage(conn: Connection, text: str | None, *, limit: int = 20) -> list[Hit]:
    return search(conn, "coverage", text, limit=limit, stop_words=PRODUCT_STOP_WORDS)


def search_guidelines(conn: Connection, text: str | None, *, limit: int = 20) -> list[Hit]:
    return search(conn, "guideline", text, limit=limit, stop_words=PRODUCT_STOP_WORDS)


def search_faq(conn: Connection, text: str | None, *, limit: int = 10) -> list[Hit]:
    return search(conn, "faq", text, limit=limit)


def search_faq_all_terms(conn: Connection, text: str | None, *, limit: int = 5) -> list[Hit]:
    """FAQs containing every query term (no any-term fallback): used to decide whether a question is in scope."""
    return _run(conn, "faq", fts_query(text, mode="all"), limit)


def search_chunks(conn: Connection, text: str | None, *, limit: int = 10) -> list[Hit]:
    return search(conn, "chunk", text, limit=limit)


def search_labs(conn: Connection, text: str | None, *, limit: int = 20) -> list[Hit]:
    return search(conn, "lab", text, limit=limit)


def search_ahcs(conn: Connection, text: str | None, *, limit: int = 20) -> list[Hit]:
    return search(conn, "ahc", text, limit=limit)
