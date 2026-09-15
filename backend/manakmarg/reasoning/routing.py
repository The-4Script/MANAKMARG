"""Deterministic routing of an understood question to one answer flow.

Each rule is checked in order and the first that applies wins; the returned ``Route`` names the rule so every answer
can explain why it took the path it did. Routing never produces a fact — it only decides which official records are
consulted. In particular, a process, scheme or general question is never sent to product search, so it cannot show
unrelated standards as an "Applicable Indian Standard".

To extend: add a cue in ``manakmarg.reasoning.intents.CUES`` or a rule below, and a test in
``tests/reasoning/test_routing.py``.
"""

import re
from dataclasses import dataclass

from manakmarg.normalize.text import norm_match
from manakmarg.reasoning.intents import (
    INTENT_GAP,
    INTENT_HALLMARKING,
    INTENT_LABS,
    INTENT_PROCESS,
    INTENT_STANDARD,
    INTENT_STATUS,
    INTENT_TESTS,
    INTENT_UPCOMING,
    Gazetteer,
    QueryUnderstanding,
)
from manakmarg.search.fts_search import stem

ROUTE_PRODUCT = "product_standard"
ROUTE_CERTIFICATION = "certification"
ROUTE_SCHEME_I = "scheme_i"
ROUTE_SCHEME_II = "scheme_ii"
ROUTE_SCHEME_IV = "scheme_iv"
ROUTE_SCHEME_X = "scheme_x"
ROUTE_QCO = "qco_mandatory"
ROUTE_LAB = "lab_testing"
ROUTE_HALLMARKING = "hallmarking"
ROUTE_AHC = "ahc"
ROUTE_GAP = "gap_analysis"
ROUTE_UPCOMING = "upcoming_qco"
ROUTE_GENERAL = "general"
ROUTE_OUT_OF_SCOPE = "out_of_scope"
ROUTE_INVALID_IDENTIFIER = "invalid_identifier"
ROUTE_UNKNOWN_LOCATION = "unknown_location"
ROUTE_HSN = "hsn_lookup"
_HSN_CUES = (" hsn ", " hs code ", " hsn code ", " tariff code ", " itc hs ")

SCHEME_ROUTES = {ROUTE_SCHEME_I: "SCHEME_I", ROUTE_SCHEME_II: "SCHEME_II", ROUTE_SCHEME_IV: "SCHEME_IV", ROUTE_SCHEME_X: "SCHEME_X"}
_SCHEME_NUMBERS = {"i": ROUTE_SCHEME_I, "1": ROUTE_SCHEME_I, "ii": ROUTE_SCHEME_II, "2": ROUTE_SCHEME_II, "iv": ROUTE_SCHEME_IV, "4": ROUTE_SCHEME_IV, "x": ROUTE_SCHEME_X, "10": ROUTE_SCHEME_X}
_SCHEME = re.compile(r" scheme (i|ii|iv|x|1|2|4|10) ")
_SCHEME_NAMES = ((" isi mark scheme ", ROUTE_SCHEME_I), (" registration scheme ", ROUTE_SCHEME_II))
_AHC_WORDS = (" ahc ", " ahcs ", " assaying ", " centre ", " center ", " centres ", " centers ")


@dataclass(frozen=True)
class Route:
    category: str
    reason: str
    scheme_id: str | None = None


def _scheme(padded: str) -> str | None:
    match = _SCHEME.search(padded)
    if match:
        return _SCHEME_NUMBERS[match.group(1)]
    return next((route for phrase, route in _SCHEME_NAMES if phrase in padded), None)


def grounded_product(understanding: QueryUnderstanding, gazetteer: Gazetteer | None) -> bool:
    """True when the remaining words name something in the listed product vocabulary (or no vocabulary is loaded)."""
    if not understanding.product_text:
        return False
    if gazetteer is None or not gazetteer.product_words:
        return True
    return any(stem(token) in gazetteer.product_words for token in understanding.product_text.split())


def route_query(understanding: QueryUnderstanding, gazetteer: Gazetteer | None = None) -> Route:
    intents = set(understanding.intents)
    padded = f" {norm_match(understanding.normalized_text or understanding.text)} "
    has_place = bool(understanding.district or understanding.city or understanding.state)
    product = grounded_product(understanding, gazetteer)
    asks_standard_or_status = bool(intents & {INTENT_STANDARD, INTENT_STATUS})

    if understanding.invalid_refs and not understanding.standard_refs:
        return Route(ROUTE_INVALID_IDENTIFIER, f"malformed IS number {understanding.invalid_refs[0]!r}")
    if any(cue in padded for cue in _HSN_CUES):
        return Route(ROUTE_HSN, "HSN code cue (local HSN lookup; separate from BIS compliance)")
    if understanding.recognition_nos:
        return Route(ROUTE_AHC, "AHC recognition number")
    if INTENT_GAP in intents:
        return Route(ROUTE_GAP, "gap-analysis cue")
    if INTENT_HALLMARKING in intents:
        if any(word in padded for word in _AHC_WORDS):
            return Route(ROUTE_AHC, "hallmarking centre cue")
        return Route(ROUTE_HALLMARKING, "hallmarking cue")
    if INTENT_UPCOMING in intents:
        return Route(ROUTE_UPCOMING, "upcoming-QCO cue")
    if INTENT_LABS in intents and not (product and asks_standard_or_status):
        return Route(ROUTE_LAB, "laboratory cue")
    if INTENT_TESTS in intents and understanding.standard_refs and (has_place or understanding.unresolved_place) and not asks_standard_or_status:
        return Route(ROUTE_LAB, "testing cue with a standard and a location")
    scheme = _scheme(padded)
    if scheme and not understanding.standard_refs:
        return Route(scheme, "named certification scheme", SCHEME_ROUTES[scheme])
    if INTENT_PROCESS in intents and not (product or understanding.standard_refs):
        return Route(ROUTE_CERTIFICATION, "licence/process cue without a product")
    if understanding.unresolved_place and not (product or understanding.standard_refs):
        return Route(ROUTE_UNKNOWN_LOCATION, f"unrecognised location {understanding.unresolved_place!r}")
    if understanding.standard_refs:
        return Route(ROUTE_PRODUCT, "Indian Standard number")
    if product:
        return Route(ROUTE_PRODUCT, "words match listed products")
    if understanding.product_text and intents & {INTENT_STANDARD, INTENT_STATUS, INTENT_TESTS}:
        return Route(ROUTE_PRODUCT, "standard/status question about an unlisted product")
    if INTENT_STATUS in intents:
        return Route(ROUTE_QCO, "compulsory-certification question without a product")
    if INTENT_PROCESS in intents or INTENT_TESTS in intents or INTENT_STANDARD in intents:
        return Route(ROUTE_GENERAL, "general BIS question")
    return Route(ROUTE_OUT_OF_SCOPE, "no BIS cue, identifier, place or listed product")
