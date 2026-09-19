"""Query interpretation: restate a question in the English the records use before anything is retrieved.

The standards catalogue, the compulsory listings, the FAQs and the lab scopes are all English. A question typed or
spoken in Hindi, Hinglish or with speech-to-text errors can only be answered once its product words are English
record terms. Interpretation happens in three layers, cheapest first:

1. **Lexicon** (always, offline): ``normalize.aliases`` / ``normalize.lexicon`` replace known Hindi and Hinglish
   words ("दूध" → "milk") while the question is understood. Most everyday questions need nothing more.
2. **Sound-alike recovery** (always, offline): a word no record matches is compared by sound with the lexicon
   (``normalize.phonetic``), which recovers typical speech-to-text slips — "geeka"/"गीका" is "ghee ka", "डूद्स" is
   "दूध". Only unambiguous matches are used.
3. **Model rewrite** (only when needed and a Groq key is configured): if words the records cannot match remain in a
   non-English or in-scope question, the question is restated in plain English by the language model and understood
   again. The rewrite is accepted only when it survives the checks in ``_validated``:
   - identifiers are local-only: an IS number the model added is removed, never searched;
   - every product word of the rewrite must exist in the record vocabulary (listing or catalogue titles);
   - the rewritten question must route somewhere in scope.
   The model therefore changes wording only; every fact still comes from the records, and the answer shows the
   restated question ("Searched as …") so the user can see what was searched.
"""

import re
from dataclasses import replace

from manakmarg.core.config import Settings
from manakmarg.normalize.is_number import extract_designations
from manakmarg.normalize.language import HINGLISH_WORDS
from manakmarg.normalize.phonetic import sound_alike
from manakmarg.normalize.text import norm_match
from manakmarg.reasoning import groq
from manakmarg.reasoning.intents import Gazetteer, QueryUnderstanding, understand
from manakmarg.reasoning.routing import (
    ROUTE_CERTIFICATION,
    ROUTE_GENERAL,
    ROUTE_LAB,
    ROUTE_OUT_OF_SCOPE,
    ROUTE_PRODUCT,
    ROUTE_QCO,
    ROUTE_UNKNOWN_LOCATION,
    Route,
    route_query,
)
from manakmarg.search.fts_search import stem

# Flows whose answer depends on what the product words mean. Identifier-driven flows (IS numbers, AHC numbers, HSN
# codes, schemes, hallmarking districts, upcoming QCOs, gap analysis) are already exact and are never rewritten.
_INTERPRETABLE_ROUTES = frozenset({ROUTE_PRODUCT, ROUTE_GENERAL, ROUTE_OUT_OF_SCOPE, ROUTE_QCO, ROUTE_LAB, ROUTE_UNKNOWN_LOCATION, ROUTE_CERTIFICATION})
_NON_LATIN_LETTER = re.compile(r"[^\W\d_A-Za-z]")
_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")


def unmatched_words(understanding: QueryUnderstanding, gazetteer: Gazetteer) -> list[str]:
    """Candidate product words that no English record could match (Hindi words the lexicon does not know, misheard or
    misspelt words). Empty when no vocabulary is loaded, so nothing is judged without the records."""
    vocabulary = gazetteer.product_words | gazetteer.catalogue_words
    if not vocabulary:
        return []
    return [word for word in understanding.candidate_words if stem(word) not in vocabulary]


def _non_english(text: str) -> bool:
    return bool(_NON_LATIN_LETTER.search(text)) or any(word.lower() in HINGLISH_WORDS for word in _LATIN_WORD.findall(text))


def needs_interpretation(query: str, understanding: QueryUnderstanding, route: Route, gazetteer: Gazetteer) -> bool:
    """True when the local understanding left words the records cannot match, in a question that is either written in
    another language or already recognised as a BIS question. Plain-English off-topic questions ("capital of France")
    never reach the model."""
    if route.category not in _INTERPRETABLE_ROUTES:
        return False
    if not unmatched_words(understanding, gazetteer):
        return False
    return _non_english(query) or understanding.in_scope


def _validated(query: str, original: QueryUnderstanding, rewrite: dict, gazetteer: Gazetteer) -> tuple[QueryUnderstanding, Route] | None:
    english = rewrite["english"]
    # Identifiers stay local-only: remove any IS number the user did not write.
    allowed = set(original.standard_refs)
    for designation in extract_designations(english):
        if designation.std_key not in allowed:
            english = english.replace(designation.raw, " ")
    english = re.sub(r"\s{2,}", " ", english).strip()
    if not english:
        return None
    restated = understand(english, gazetteer=gazetteer)
    vocabulary = gazetteer.product_words | gazetteer.catalogue_words
    words = restated.product_text.split() if restated.product_text else []
    if vocabulary and words and not all(stem(word) in vocabulary for word in words):
        # Keep only the words the records know; if none are left, the rewrite is not usable.
        known = [word for word in words if stem(word) in vocabulary]
        if not known:
            return None
        restated = replace(restated, product_text=" ".join(known))
    # The model's short product name ("paneer" for "paneer made from cow's milk") is used when it is part of its own
    # restatement and every word is known to the records; otherwise the words of the restatement stand.
    product = norm_match(rewrite.get("product") or "")
    product_words = product.split()
    restated_words = {stem(word) for word in (restated.product_text or "").split()}
    if product_words and all(stem(word) in vocabulary for word in product_words) and {stem(word) for word in product_words} <= restated_words:
        restated = replace(restated, product_text=product)
    route = route_query(restated, gazetteer)
    if route.category == ROUTE_OUT_OF_SCOPE:
        return None
    restated = replace(
        restated,
        text=original.text,
        language=original.language,
        # Places and identifiers found in the original question are kept even if the rewrite dropped them.
        standard_refs=restated.standard_refs or original.standard_refs,
        state=restated.state or original.state,
        district=restated.district or original.district,
        district_state=restated.district_state or original.district_state,
        city=restated.city or original.city,
        interpreted_as=english,
        interpretation_source="model",
    )
    return restated, route_query(restated, gazetteer)


def _recover_by_sound(understanding: QueryUnderstanding, gazetteer: Gazetteer) -> tuple[QueryUnderstanding, Route] | None:
    text = understanding.normalized_text or understanding.text
    changed = False
    for word in unmatched_words(understanding, gazetteer):
        target = sound_alike(word)
        if target:
            text, count = re.subn(rf"(?<![\wऀ-ॿ]){re.escape(word)}(?![\wऀ-ॿ])", target, text, flags=re.IGNORECASE)
            changed = changed or bool(count)
    if not changed:
        return None
    restated = understand(text, gazetteer=gazetteer)
    route = route_query(restated, gazetteer)
    if route.category == ROUTE_OUT_OF_SCOPE:
        return None
    restated = replace(restated, text=understanding.text, language=understanding.language, interpreted_as=text, interpretation_source="sound-alike")
    return restated, route


def interpret(query: str, understanding: QueryUnderstanding, route: Route, gazetteer: Gazetteer, settings: Settings) -> tuple[QueryUnderstanding, Route] | None:
    """The question understood again from a sound-alike correction or a validated English restatement, or ``None``
    when nothing needs interpreting or nothing usable was found (no key, model failure, rewrite failed validation)."""
    if not needs_interpretation(query, understanding, route, gazetteer):
        return None
    recovered = _recover_by_sound(understanding, gazetteer)
    if recovered is not None and not unmatched_words(recovered[0], gazetteer):
        return recovered
    rewrite = groq.interpret_query(query, settings)
    restated = _validated(query, understanding, rewrite, gazetteer) if rewrite else None
    return restated or recovered
