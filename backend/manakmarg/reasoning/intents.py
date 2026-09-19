"""Query understanding: intent and entities from transparent rules (spec §4, data flow).

Rules only route a question to the right services. They never decide a fact: identifiers are resolved against the
database and every answer is assembled from official records. An optional LLM may help parse low-confidence
questions (``manakmarg.llm``), but its output goes through the same resolvers.

Hindi and Hinglish questions first pass through ``manakmarg.normalize.aliases``, which replaces known domain words and
place names with the English terms used by the records; the rest of the question is left as written.
"""

import difflib
import re
from dataclasses import dataclass, field
from dataclasses import replace

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from manakmarg.db import schema
from manakmarg.normalize.aliases import PLACE_ALIASES, apply_aliases, clean_script
from manakmarg.normalize.geo import STATES_AND_UTS, compact_district
from manakmarg.normalize.is_number import extract_designations
from manakmarg.normalize.orders import extract_so_number
from manakmarg.normalize.text import norm_match
from manakmarg.search.fts_search import PRODUCT_STOP_WORDS, stem

INTENT_GAP = "gap_analysis"
INTENT_HALLMARKING = "hallmarking"
INTENT_LABS = "lab_search"
INTENT_UPCOMING = "upcoming_qco"
INTENT_TESTS = "tests_required"
INTENT_PROCESS = "certification_process"
INTENT_STATUS = "compulsory_status"
INTENT_STANDARD = "applicable_standard"
INTENT_PRODUCT = "product_compliance"
INTENT_GENERAL = "general_question"

INTENT_PRIORITY = (
    INTENT_GAP,
    INTENT_HALLMARKING,
    INTENT_LABS,
    INTENT_UPCOMING,
    INTENT_TESTS,
    INTENT_PROCESS,
    INTENT_STATUS,
    INTENT_STANDARD,
)

CUES = {
    INTENT_GAP: (
        "gap analysis", "compare my", "datasheet", "data sheet", "my test report", "my document", "check my",
        "my specification", "my product specification", "against the applicable requirements", "against the requirements",
    ),
    INTENT_HALLMARKING: (
        "hallmark", "hallmarking", "hallmarked", "huid", "jewellery", "jewelry", "jeweller", "jewellers", "jeweler",
        "gold", "silver", "ahc", "ahcs", "assaying", "karat", "carat", "hallmarking centre", "hallmarking center",
        "सोना", "सोने", "गहने", "गहनों", "आभूषण", "आभूषणों", "ज्वेलरी",
    ),
    INTENT_LABS: (
        "lab", "labs", "laboratory", "laboratories", "testing facility", "test centre", "test center", "get tested",
        "get it tested", "tested", "where to test", "प्रयोगशाला", "लैब",
    ),
    INTENT_UPCOMING: ("upcoming", "new qco", "new qcos", "coming into force", "due for implementation"),
    INTENT_TESTS: (
        "which tests", "what tests", "tests required", "test requirements", "tests are required", "scheme of inspection",
        "sampling", "test equipment", "testing", "sit", "product manual", "grouping", "grouping guideline",
    ),
    INTENT_PROCESS: (
        "how to apply", "how do i apply", "how can i apply", "apply for", "application", "procedure", "process", "steps",
        "documents required", "fee", "fees", "cost of", "charges", "how much", "how long", "how many days", "time taken", "timeline", "validity", "renewal", "renew", "kitna", "kitni",
        "kitne din", "कितना", "कितनी", "शुल्क", "फीस",
        "manakonline", "licence", "license", "obtain", "get certified", "आवेदन", "प्रक्रिया",
    ),
    INTENT_STATUS: (
        "mandatory", "compulsory", "qco", "qcos", "quality control order", "is it required", "need bis",
        "isi", "isi mark", "isi marked", "bis mark", "bis certification", "certification required", "आईएसआई",
        "enforcement", "deadline", "notified", "zaroori", "jaruri", "anivarya", "अनिवार्य", "ज़रूरी", "जरूरी",
    ),
    INTENT_STANDARD: (
        "which standard", "which indian standard", "applicable standard", "standard applies", "standard for",
        "which is applies", "standard", "bis standard", "kaunsa standard", "konsa standard", "standard batao", "manak",
        "मानक", "बीआईएस मानक",
    ),
}

_ENTITY_ALIASES = {
    "material": {
        "copper": ("copper", "तांबा", "तांबे"),
        "steel": ("steel", "स्टील", "इस्पात"),
        "stainless steel": ("stainless steel", "स्टेनलेस स्टील", "स्टेनलेस इस्पात"),
        "pvc": ("pvc", "पीवीसी"),
        "aluminium": ("aluminium", "aluminum", "एल्युमिनियम", "अल्यूमिनियम"),
        "plastic": ("plastic", "प्लास्टिक"),
        "cement": ("cement", "सीमेंट"),
        "gold": ("gold", "सोना", "सोने"),
        "silver": ("silver", "चांदी", "चाँदी"),
    },
    "product": {
        "wire": ("wire", "wires", "तार"),
        "cable": ("cable", "cables", "केबल"),
        "conductor": ("conductor", "conductors", "कंडक्टर"),
        "pipe": ("pipe", "pipes", "पाइप"),
        "tube": ("tube", "tubes", "ट्यूब"),
        "plate": ("plate", "plates", "प्लेट"),
        "utensils": ("utensil", "utensils", "बर्तन"),
        "cookware": ("cookware", "कुकवेयर"),
        "jewellery": ("jewellery", "jewelry", "ज्वेलरी", "आभूषण"),
        "structural steel": ("structural steel", "स्ट्रक्चरल स्टील"),
        "pressure cooker": ("pressure cooker", "pressure cookers", "प्रेशर कुकर"),
        "ceiling fan": ("ceiling fan", "ceiling fans", "सीलिंग फैन"),
    },
    "application": {
        "construction": ("construction", "निर्माण"),
        "industrial": ("industrial", "industry", "औद्योगिक"),
        "drinking water": ("drinking water", "पीने का पानी"),
    },
}

_DOMAIN_TERMS = frozenset(
    "bis standard standards certification licence license qco scheme compliance hallmark hallmarking lab labs "
    "testing test ahc mandatory compulsory product wire cable pipe tube plate steel copper pvc aluminium cement "
    "utensil cookware jewellery jewelry gold silver मानक प्रमाणन लाइसेंस क्यूको योजना अनुपालन हॉलमार्क प्रयोगशाला "
    "जाँच परीक्षण अनिवार्य स्टील तांबा तार केबल पाइप बर्तन सोना चांदी".split()
)

QUESTION_WORDS = frozenset(
    """about all am any applies apply applicable ask cover covered coverage details do does done find give help
    hai hain have hoga how kya list me mein near please show tell under what whether which ke ka ki ko se
    happen happens not also follow
    mujhe liye batao bataye bataiye batayein kaunsa konsa kaun sa lagu hota hoti mera meri mere kaise milega chahiye
    क्या में के की का को से पर है हैं हो और या कौन कौनसा कैसे कहाँ कहां लिए मेरे मेरा मेरी मुझे बताएं बताइए चाहिए
    सा सी लागू होता होती बताओ बताएँ करें करे मैं हम बनाता बनाती बनाते हूँ हूं वाले वाली बारे जानकारी दें दीजिए उत्पाद
    उत्पादों किस
    main mai hoon hun banata banati banate bana raha rahi rahe karta karti karte karna chahta chahti chahte
    bechna bechta bechti bechte bana rahe hamara hamari humara apna apni take takes taken milta milti milega lagta
    lagti lagega din बाताओ बताओ बताइये बतायें""".split()
)

# With no BIS word in the question, these mark it as about something else ("steel share price", "gold rate today",
# "cement company jobs") even though a product word appears in it.
_NON_BIS_TOPICS = frozenset(
    "price prices rate rates share shares stock stocks market job jobs salary vacancy recipe recipes ideas insurance "
    "loan news movie weather".split()
)
# Words that name BIS or its instruments outright; any one of them keeps a question in scope.
_STRONG_BIS_TERMS = frozenset(
    "bis isi qco qcos standard standards certification certificate licence license hallmark hallmarking huid ahc lims "
    "manakonline मानक प्रमाणन लाइसेंस हॉलमार्क हॉलमार्किंग बीआईएस आईएसआई क्यूसीओ".split()
)

_ABBREVIATED_STATES = {
    "UP": "Uttar Pradesh",
    "MP": "Madhya Pradesh",
    "WB": "West Bengal",
    "HP": "Himachal Pradesh",
    "AP": "Andhra Pradesh",
    "TN": "Tamil Nadu",
}
_HINDI_STATES = {
    "दिल्ली": "Delhi",
    "राजस्थान": "Rajasthan",
    "महाराष्ट्र": "Maharashtra",
    "गुजरात": "Gujarat",
    "उत्तर प्रदेश": "Uttar Pradesh",
    "मध्य प्रदेश": "Madhya Pradesh",
    "बिहार": "Bihar",
    "पश्चिम बंगाल": "West Bengal",
    "तमिलनाडु": "Tamil Nadu",
    "कर्नाटक": "Karnataka",
    "केरल": "Kerala",
    "पंजाब": "Punjab",
    "हरियाणा": "Haryana",
    "तेलंगाना": "Telangana",
    "आंध्र प्रदेश": "Andhra Pradesh",
    "ओडिशा": "Odisha",
    "झारखंड": "Jharkhand",
    "छत्तीसगढ़": "Chhattisgarh",
    "असम": "Assam",
    "उत्तराखंड": "Uttarakhand",
    "हिमाचल प्रदेश": "Himachal Pradesh",
    "गोवा": "Goa",
    "लक्षद्वीप": "Lakshadweep",
    "पुडुचेरी": "Puducherry",
    "लद्दाख": "Ladakh",
    "जम्मू और कश्मीर": "Jammu and Kashmir",
}
_STATE_PHRASES = {norm_match(name): name for name in STATES_AND_UTS} | {
    norm_match(name): state for name, state in _HINDI_STATES.items()
} | {"jammu kashmir": "Jammu and Kashmir", "orissa": "Odisha", "pondicherry": "Puducherry", "new delhi": "Delhi"}

_DEVANAGARI = re.compile("[ऀ-ॿ]")
_RECOGNITION = re.compile(r"\b[A-Z]{2,4}/RAHC/R-\d{3,8}\b", re.IGNORECASE)
_BARE_NUMBER = re.compile(r"(?<![\w./:-])\d{2,5}(?![\w/:-])")
# "IS 2O62": digits mixed with the letters O/I/l are a mistyped number, never a shorter valid one ("IS 2").
_MALFORMED_IS = re.compile(r"(?<![A-Za-z0-9])IS\s*[-:/]?\s*(?=[0-9OoIl]*[0-9])(?=[0-9OoIl]*[OoIl])[0-9OoIl]{2,}(?![A-Za-z0-9])")
_PLACE_AFTER_PREPOSITION = re.compile(r"\b(?:in|at|near|around)\s+((?:[A-Z][A-Za-z.\-]{2,})(?:\s+[A-Z][A-Za-z.\-]{2,}){0,2})")
_PLACE_BEFORE_DISTRICT = re.compile(r"\b([A-Za-z][A-Za-z.\-]{2,})\s+district\b", re.IGNORECASE)
_HINDI_PLACE = re.compile(r"([ऀ-ॿ]{2,})\s+(?:ज़िले|जिले|ज़िला|जिला|में)")
# "IS" on its own asks for the Indian Standard ("दूध का IS क्या है", "what is the IS for milk"). Upper case only, so the
# English verb "is" never counts; Hinglish "ka/ki/ke is" is accepted in any case. A number after it is an identifier.
_IS_WORD = re.compile(r"(?<![A-Za-z0-9])IS(?![A-Za-z0-9])(?!\s*[-:/.]?\s*\d)")
_HINGLISH_IS = re.compile(r"\b(?:ka|ki|ke|kaa)\s+is\b(?!\s*[-:/.]?\s*\d)", re.IGNORECASE)
_NOT_PLACES = frozenset({"is", "bis", "india", "indian", "scheme", "part", "qco", "qcos", "english", "hindi", "the", "this", "that", "my", "your", "any", "each", "every", "same", "which", "one"})


@dataclass
class Gazetteer:
    """Place names known from the official records (hallmarking districts with aliases, laboratory cities) and the
    product vocabulary of the compulsory-certification listings, used to tell product questions from other text."""

    districts: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    cities: dict[str, tuple[str, str | None]] = field(default_factory=dict)
    product_words: frozenset[str] = frozenset()
    # Stemmed words of every current published standard title: what the catalogue can match at all.
    catalogue_words: frozenset[str] = frozenset()

    @classmethod
    def load(cls, conn: Connection) -> "Gazetteer":
        districts: dict[str, list[tuple[str, str]]] = {}
        district, alias = schema.hallmarking_district, schema.district_alias
        rows = conn.execute(
            sa.select(alias.c.alias_norm, district.c.district, district.c.state)
            .select_from(alias.join(district, district.c.district_id == alias.c.district_id))
            .where(district.c.is_current.is_(True))
        )
        for row in rows:
            entries = districts.setdefault(row.alias_norm, [])
            if (row.district, row.state) not in entries:
                entries.append((row.district, row.state))
        cities: dict[str, tuple[str, str | None]] = {}
        lab = schema.laboratory
        for row in conn.execute(sa.select(lab.c.city, lab.c.state).where(lab.c.is_current.is_(True), lab.c.city.is_not(None))):
            cities.setdefault(norm_match(row.city), (row.city, row.state))
        return cls(districts, cities, product_vocabulary(conn), catalogue_vocabulary(conn))


def product_vocabulary(conn: Connection) -> frozenset[str]:
    """Stemmed words of the listed product names and categories plus the curated synonym terms."""
    from manakmarg.search.hybrid import load_synonyms

    words: set[str] = set()
    for (term,) in conn.execute(sa.select(schema.product_term.c.term_norm)):
        words.update(stem(token) for token in (term or "").split())
    for synonym in load_synonyms():
        for term in synonym.terms:
            words.update(stem(token) for token in term.split())
    return frozenset(word for word in words if len(word) > 2 and word not in PRODUCT_STOP_WORDS and not word.isdigit())


def catalogue_vocabulary(conn: Connection) -> frozenset[str]:
    """Stemmed words of the current published standard titles."""
    words: set[str] = set()
    for (title,) in conn.execute(sa.select(schema.standard.c.title_clean).where(schema.standard.c.is_current.is_(True))):
        words.update(stem(token) for token in norm_match(title).split())
    return frozenset(word for word in words if len(word) > 2 and not word.isdigit())


@dataclass(frozen=True)
class QueryUnderstanding:
    text: str
    language: str
    intent: str
    intents: tuple[str, ...]
    standard_refs: tuple[str, ...]
    doc_numbers: tuple[str, ...]
    recognition_nos: tuple[str, ...]
    so_numbers: tuple[str, ...]
    state: str | None
    district: str | None
    district_state: str | None
    city: str | None
    metal: str | None
    product_text: str | None
    confidence: float
    normalized_text: str = ""
    aliases_used: tuple[tuple[str, str], ...] = ()
    invalid_refs: tuple[str, ...] = ()
    unresolved_place: str | None = None
    material: str | None = None
    product: str | None = None
    application: str | None = None
    in_scope: bool = True
    clarification: str | None = None
    # The words left after cues, identifiers, places and question words are removed, kept even when the question is
    # judged out of scope: the interpretation step checks them against the English record vocabulary.
    candidate_words: tuple[str, ...] = ()
    # Set when the question was restated in English before retrieval (``manakmarg.reasoning.interpret``).
    interpreted_as: str | None = None
    interpretation_source: str | None = None


def apply_model_hints(understanding: QueryUnderstanding, hints: dict) -> QueryUnderstanding:
    """Apply only bounded routing hints; identifiers and legal facts remain local-only."""
    allowed_intents = set(INTENT_PRIORITY) | {INTENT_PRODUCT, INTENT_GENERAL}
    intent = hints.get("intent") if hints.get("intent") in allowed_intents else understanding.intent
    material = hints.get("material") if hints.get("material") in _ENTITY_ALIASES["material"] else understanding.material
    product = hints.get("product") if hints.get("product") in _ENTITY_ALIASES["product"] else understanding.product
    application = hints.get("application") if hints.get("application") in _ENTITY_ALIASES["application"] else understanding.application
    product_text = understanding.product_text
    if material and product:
        product_text = f"{material} {product}"
    return replace(
        understanding,
        intent=intent,
        intents=tuple(dict.fromkeys((intent, *understanding.intents))),
        material=material,
        product=product,
        application=application,
        product_text=product_text,
        confidence=max(understanding.confidence, min(float(hints.get("confidence", 0)), 0.85)),
    )


def _padded(text: str) -> str:
    return f" {norm_match(text)} "


def _cue_hits(padded: str) -> dict[str, list[str]]:
    return {intent: [cue for cue in cues if f" {norm_match(cue)} " in padded] for intent, cues in CUES.items()}


def _find_state(text: str, tokens: list[str]) -> tuple[str | None, set[str]]:
    for size in (3, 2, 1):
        for index in range(len(tokens) - size + 1):
            phrase = " ".join(tokens[index : index + size])
            if phrase in _STATE_PHRASES:
                return _STATE_PHRASES[phrase], set(tokens[index : index + size])
    for match in re.finditer(r"\b(U\.?P|M\.?P|W\.?B|H\.?P|A\.?P|T\.?N)\b\.?", text):
        abbreviation = match.group(1).replace(".", "")
        if abbreviation.isupper():
            return _ABBREVIATED_STATES[abbreviation], {abbreviation.lower()}
    return None, set()


def _find_place(tokens: list[str], gazetteer: Gazetteer) -> tuple[str | None, str | None, str | None, set[str]]:
    for size in (3, 2, 1):
        for index in range(len(tokens) - size + 1):
            words = tokens[index : index + size]
            phrase = " ".join(words)
            if len(phrase) < 3 or phrase in PRODUCT_STOP_WORDS:
                continue
            compact = phrase.replace(" ", "")
            district_hits = gazetteer.districts.get(phrase) or gazetteer.districts.get(compact)
            city = gazetteer.cities.get(phrase)
            if district_hits:
                name, state = district_hits[0] if len(district_hits) == 1 else (district_hits[0][0], None)
                return name, state, city[0] if city else None, set(words)
            if city:
                return None, city[1], city[0], set(words)
    return None, None, None, set()


def _unresolved_place(text: str, ignore: set[str]) -> str | None:
    """A location the user named explicitly ("in Timbuktu", "Gotham district", "टिम्बकटू में") that no record list
    resolved. Returned so the answer can say so instead of silently searching everywhere."""
    for pattern in (_PLACE_BEFORE_DISTRICT, _PLACE_AFTER_PREPOSITION, _HINDI_PLACE):
        for match in pattern.finditer(text):
            words = norm_match(match.group(1)).split()
            if words and not any(word in _NOT_PLACES or word in ignore or word in QUESTION_WORDS or word in PRODUCT_STOP_WORDS for word in words):
                return match.group(1)
    return None


_DEVANAGARI_PLACE_NAMES = {clean_script(name): target for name, target in {**PLACE_ALIASES, **_HINDI_STATES}.items()}


def suggest_place(place: str | None) -> str | None:
    """A known place whose Devanagari spelling is very close to an unrecognised one ("कोलकाटा" → "Kolkata"). Used only for
    a "did you mean" suggestion: the question is never answered as if the user had named that place."""
    if not place or not _DEVANAGARI.search(place):
        return None
    close = difflib.get_close_matches(clean_script(place).strip(), list(_DEVANAGARI_PLACE_NAMES), n=1, cutoff=0.8)
    return _DEVANAGARI_PLACE_NAMES[close[0]] if close else None


def _find_entity(text: str, category: str) -> str | None:
    normalized = _padded(text)
    for canonical, aliases in _ENTITY_ALIASES[category].items():
        if any(f" {norm_match(alias)} " in normalized for alias in aliases):
            return canonical
    return None


def _has_domain_signal(text: str, understanding_parts: tuple[str | None, ...]) -> bool:
    tokens = set(norm_match(text).split())
    return bool(tokens & _DOMAIN_TERMS) or any(understanding_parts)


def understand(text: str, *, gazetteer: Gazetteer | None = None) -> QueryUnderstanding:
    text = text or ""
    gazetteer = gazetteer or Gazetteer()
    aliased = apply_aliases(text)
    invalid_refs = tuple(dict.fromkeys(match.group(0) for match in _MALFORMED_IS.finditer(aliased.text)))
    work = _MALFORMED_IS.sub(" ", aliased.text)
    padded = _padded(work)
    tokens = norm_match(work).split()
    hits = _cue_hits(padded)
    if _IS_WORD.search(work) or _HINGLISH_IS.search(work):
        hits[INTENT_STANDARD].append("IS")

    recognition_nos = tuple(dict.fromkeys(match.group(0).upper() for match in _RECOGNITION.finditer(work)))
    if recognition_nos:
        hits[INTENT_HALLMARKING].append("recognition number")
    lab_or_standard_context = bool(hits[INTENT_LABS] or hits[INTENT_TESTS] or hits[INTENT_STANDARD])
    designations = extract_designations(_RECOGNITION.sub(" ", work))
    malformed_is = bool(invalid_refs)
    if not designations and lab_or_standard_context:
        designations = extract_designations(" ".join(_BARE_NUMBER.findall(work)), assume_is_prefix=True)
    standard_refs = tuple(dict.fromkeys(designation.std_key for designation in designations))
    doc_numbers = tuple(dict.fromkeys(designation.number for designation in designations if designation.number))
    so_number = extract_so_number(work)

    state, state_tokens = _find_state(work, tokens)
    remaining = [token for token in tokens if token not in state_tokens]
    district, district_state, city, place_tokens = _find_place(remaining, gazetteer)

    metal = None
    if any(word in padded for word in (" gold ", " सोना ", " सोने ")):
        metal = "gold"
    elif " silver " in padded:
        metal = "silver"

    # The aliased text too: speech-to-text writes English product words in Devanagari ("कॉपर वायर" → "copper wire").
    entity_text = f"{text} {aliased.text}"
    material = _find_entity(entity_text, "material")
    product = _find_entity(entity_text, "product")
    application = _find_entity(entity_text, "application")

    cue_tokens = {token for cues in hits.values() for cue in cues for token in norm_match(cue).split()}
    identifier_tokens = {norm_match(part) for designation in designations for part in designation.raw.split()}
    identifier_tokens |= {"is", "part", "sec", *doc_numbers}
    unresolved = None
    if not (state or district or city):
        unresolved = _unresolved_place(work, cue_tokens | identifier_tokens)
    unresolved_tokens = set(norm_match(unresolved).split()) | {"district"} if unresolved else set()
    product_words = [
        token
        for token in tokens
        if token not in cue_tokens
        and token not in identifier_tokens
        and token not in state_tokens
        and token not in place_tokens
        and token not in unresolved_tokens
        and token not in PRODUCT_STOP_WORDS
        and token not in QUESTION_WORDS
        and not token.isdigit()
    ]
    # Product words checked against the vocabulary of the official compulsory-certification listings (loaded from the
    # database). A question made only of listed product words ("electric iron", "Packaged Pasteurized Milk") is a product
    # question even without a BIS cue. Every word must be known, so "car insurance" or "weather today" stay out of scope.
    vocabulary = gazetteer.product_words
    names_listed_product = bool(vocabulary) and bool(product_words) and all(stem(token) in vocabulary for token in product_words)
    product_text = " ".join(product_words) or None
    in_scope = (
        _has_domain_signal(f"{text} {aliased.text}", (material, product, application, *standard_refs, *recognition_nos, *invalid_refs))
        or any(hits.values())
        or names_listed_product
    )
    all_tokens = set(norm_match(f"{text} {aliased.text}").split())
    if all_tokens & _NON_BIS_TOPICS and not (all_tokens & _STRONG_BIS_TERMS or standard_refs or recognition_nos):
        in_scope = False
    if malformed_is and not standard_refs:
        product_text = None
    if not in_scope:
        product_text = None

    intents = [intent for intent in INTENT_PRIORITY if hits[intent]]
    if product_text or standard_refs:
        intents.append(INTENT_PRODUCT)
    primary = intents[0] if intents else INTENT_GENERAL
    if not in_scope:
        primary = INTENT_GENERAL
        intents = [INTENT_GENERAL]
    confidence = 0.9 if (standard_refs or recognition_nos or (intents and primary != INTENT_PRODUCT)) else 0.6 if product_text else 0.3
    clarification = None
    if material and not product and not standard_refs:
        clarification = "Please specify the product type, such as wire, cable, pipe, tube or sheet."
    return QueryUnderstanding(
        text=text,
        language="hi" if _DEVANAGARI.search(text) else "en",
        intent=primary,
        intents=tuple(intents) or (INTENT_GENERAL,),
        standard_refs=standard_refs,
        doc_numbers=doc_numbers,
        recognition_nos=recognition_nos,
        so_numbers=(so_number,) if so_number else (),
        state=state or district_state,
        district=district,
        district_state=district_state,
        city=city,
        metal=metal,
        product_text=product_text,
        confidence=confidence,
        normalized_text=aliased.text,
        aliases_used=aliased.replacements,
        invalid_refs=invalid_refs,
        unresolved_place=unresolved,
        material=material,
        product=product,
        application=application,
        in_scope=in_scope,
        clarification=clarification,
        candidate_words=tuple(product_words),
    )


def district_key(name: str) -> str:
    return compact_district(name)
