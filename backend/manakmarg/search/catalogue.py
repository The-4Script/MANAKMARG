"""Published Indian Standards *for* a product, from the whole standards catalogue.

The compulsory listings cover about a thousand products; the published catalogue has every Indian Standard. A
"which standard / IS for X" question is answered from the catalogue, ranked so that the standard whose subject *is*
the product comes first:

* English titles put the thing a standard is about last in their subject ("Packaged Pasteurized **Milk**" is milk,
  "**Milk** Boiler" is a boiler), so a subject equal to or ending with the product words ranks above one that merely
  mentions them;
* product specifications rank above test methods, sampling plans, codes of practice and glossaries;
* one entry per standard family (its latest current version), then newer and shorter titles first.

Only titles containing every product word are returned. Ranking orders candidates; it never decides whether a
standard is compulsory (that comes from the listings).
"""

import re
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from manakmarg.normalize.text import norm_match
from manakmarg.search.fts_search import PRODUCT_STOP_WORDS, stem

TIER_EXACT = 0  # the title's subject is the product ("Ghee - Specification")
TIER_KIND_OF = 1  # the subject ends with the product ("Packaged Pasteurized Milk")
TIER_SUBJECT = 2  # the product is part of the subject ("Milk Powder", "Milk Cans")
TIER_MENTION = 3  # the product is mentioned elsewhere in the title
_NOT_A_SPECIFICATION = re.compile(
    r"\b(method|methods|sampling|test|tests|testing|code of practice|glossary|terminology|recommendations?|guide|guidelines|sensory evaluation|determination|analysis|preparation|vocabulary|specimens?|dimensions|marking|identification)\b",
    re.IGNORECASE,
)
_SUBJECT_PREFIX = re.compile(r"^(specification|requirements|standard)\s+(for|of)\s+")
_PURPOSE = re.compile(r"\s(?:for|of|used in|used for|intended for)\s")
_TITLE_PARTS = re.compile(r"\s+[-–—]+\s+|\s*[–—:]\s*|\s+--\s+")
_FILLER = frozenset("and or of the a an with".split())
CANDIDATE_LIMIT = 400


@dataclass(frozen=True)
class CatalogueMatch:
    standard_id: int
    std_key: str
    family_key: str | None
    title: str
    tier: int
    specification: bool


def _words(text: str | None) -> list[str]:
    return [stem(token) for token in norm_match(text).split() if token not in PRODUCT_STOP_WORDS and not token.isdigit()]


def _segment_tier(words: set[str], segment: str) -> tuple[int, int, int] | None:
    """(tier, subject length) of one title part. The subject is cut at "for"/"used in": "Settling Tanks for Ghee" is a
    tank, "Polish for Canvas Footwear" is a polish, "Sugar of Milk" is sugar."""
    segment = _SUBJECT_PREFIX.sub("", norm_match(segment))
    thing_text = _PURPOSE.split(segment, maxsplit=1)[0]
    thing = [stem(token) for token in thing_text.split() if token not in _FILLER]
    tokens = segment.split()
    everything = {stem(token) for token in tokens}
    if not words <= everything:
        return None
    # (tier, words in the subject, words in the whole part): "Groundnut oil" ranks above "Groundnut oil for cosmetic
    # industry", which names a narrower use.
    if set(thing) == words:
        return TIER_EXACT, len(thing), len(tokens)
    if len(thing) >= len(words) and set(thing[-len(words):]) == words:
        return TIER_KIND_OF, len(thing), len(tokens)
    if words <= set(thing):
        return TIER_SUBJECT, len(thing), len(tokens)
    return TIER_MENTION, len(thing), len(tokens)


def _tier(words: list[str], title: str) -> tuple[int, int, int] | None:
    wanted = set(words)
    if not wanted <= {stem(token) for token in norm_match(title).split()}:
        return None
    tiers = [tier for part in _TITLE_PARTS.split(title) if part.strip() for tier in [_segment_tier(wanted, part)] if tier]
    return min(tiers) if tiers else (TIER_MENTION + 1, 99, 99)


def subject_tier(product: str | None, title: str | None) -> int | None:
    """How directly ``title`` names ``product`` (``TIER_*``), or ``None`` when it does not contain every product word.
    Also used for listing names: "Square Tins … for Ghee" is about tins, not ghee."""
    words = list(dict.fromkeys(_words(product)))
    if not words or not title:
        return None
    found = _tier(words, title)
    return found[0] if found else None


def short_subject(title: str, product: str | None = None) -> str:
    """The part of a title that names the product, for compact mentions: "Pulverized fuel ash - Lime bricks" →
    "Lime bricks", "Specification for acid resistant bricks" → "acid resistant bricks"."""
    parts = [part.strip() for part in _TITLE_PARTS.split(title) if part.strip()]
    words = set(_words(product))
    named = [part for part in parts if words and words <= {stem(token) for token in norm_match(part).split()}]
    chosen = (named or parts or [title])[0]
    return re.sub(r"^(specification|requirements|standard)\s+(for|of)\s+", "", chosen, flags=re.IGNORECASE)


def standards_for_product(conn: Connection, text: str | None, *, limit: int = 5) -> list[CatalogueMatch]:
    """Current published standards whose titles contain every product word, best-matching subject first."""
    return search_product(conn, text, limit=limit)[0]


def search_product(conn: Connection, text: str | None, *, limit: int = 5) -> tuple[list[CatalogueMatch], str | None]:
    """Like ``standards_for_product``, but when no title contains every word, leading describing words are dropped one
    at a time ("children milk bottles" → "milk bottles"), keeping the head noun English puts last. Returns the matches
    and the phrase that matched, so the answer names what was actually found."""
    tokens = [token for token in norm_match(text).split() if token not in PRODUCT_STOP_WORDS and not token.isdigit()]
    # A multi-word product is never reduced to one generic word ("solar panel" → "panel" would be another product).
    for start in range(max(len(tokens) - 1, 1)):
        phrase = " ".join(tokens[start:])
        found = _standards(conn, phrase, limit)
        if found:
            return found, phrase
    return [], None


def _standards(conn: Connection, text: str, limit: int) -> list[CatalogueMatch]:
    words = list(dict.fromkeys(_words(text)))
    if not words:
        return []
    match = " AND ".join(f'"{word}"*' for word in words)
    try:
        rows = conn.execute(
            sa.text(
                "SELECT s.standard_id, s.std_key, s.family_key, s.title_clean, s.title, s.year FROM standard_fts f "
                "JOIN standard s ON s.standard_id = f.rowid WHERE standard_fts MATCH :match AND s.is_current = 1 LIMIT :limit"
            ),
            {"match": match, "limit": CANDIDATE_LIMIT},
        ).mappings().all()
    except sa.exc.OperationalError:  # an FTS syntax problem must never break an answer
        return []
    best: dict[str, tuple[tuple, CatalogueMatch]] = {}
    for row in rows:
        title = row["title_clean"] or row["title"] or ""
        found_tier = _tier(words, title)
        if found_tier is None:
            continue
        tier, subject_length, part_length = found_tier
        specification = not _NOT_A_SPECIFICATION.search(title)
        found = CatalogueMatch(row["standard_id"], row["std_key"], row["family_key"], title, tier, specification)
        # Specifications first, then how directly the subject names the product, then the most general subject.
        rank = (not specification, tier, subject_length, part_length, -(row["year"] or 0), len(title))
        family = row["family_key"] or row["std_key"]
        # One entry per family: its best-ranked (normally latest) version.
        if family not in best or rank < best[family][0]:
            best[family] = (rank, found)
    return [found for _, found in sorted(best.values(), key=lambda item: item[0])][:limit]
