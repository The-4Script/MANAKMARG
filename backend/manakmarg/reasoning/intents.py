"""Query understanding: intent and entities from transparent rules (spec §4, data flow).

Rules only route a question to the right services. They never decide a fact: identifiers are resolved against the
database and every answer is assembled from official records. An optional LLM may help parse low-confidence
questions (``manakmarg.llm``), but its output goes through the same resolvers.
"""

import re
from dataclasses import dataclass, field
from dataclasses import replace

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from manakmarg.db import schema
from manakmarg.normalize.geo import STATES_AND_UTS, compact_district
from manakmarg.normalize.is_number import extract_designations
from manakmarg.normalize.orders import extract_so_number
from manakmarg.normalize.text import norm_match
from manakmarg.search.fts_search import PRODUCT_STOP_WORDS

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
    INTENT_GAP: ("gap analysis", "compare my", "datasheet", "data sheet", "my test report", "my document"),
    INTENT_HALLMARKING: (
        "hallmark", "hallmarking", "hallmarked", "huid", "jewellery", "jewelry", "jeweller", "jewellers", "jeweler",
        "gold", "silver", "ahc", "ahcs", "assaying", "karat", "carat",
        "हॉलमार्क", "हॉलमार्किंग", "सोना", "सोने", "चांदी", "गहने", "गहनों", "आभूषण", "आभूषणों", "ज्वेलरी",
    ),
    INTENT_LABS: (
        "lab", "labs", "laboratory", "laboratories", "testing facility", "test centre", "test center", "get tested",
        "where to test", "प्रयोगशाला", "लैब",
    ),
    INTENT_UPCOMING: ("upcoming", "new qco", "new qcos", "coming into force", "due for implementation"),
    INTENT_TESTS: (
        "which tests", "what tests", "tests required", "test requirements", "tests are required", "scheme of inspection",
        "sampling", "test equipment", "परीक्षण",
    ),
    INTENT_PROCESS: (
        "how to apply", "how do i apply", "how can i apply", "apply for", "application", "procedure", "process", "steps",
        "documents required", "fees", "manakonline", "आवेदन", "प्रक्रिया",
    ),
    INTENT_STATUS: (
        "mandatory", "compulsory", "qco", "qcos", "quality control order", "is it required", "need bis",
        "enforcement", "deadline", "notified", "अनिवार्य", "ज़रूरी", "जरूरी",
    ),
    INTENT_STANDARD: (
        "which standard", "which indian standard", "applicable standard", "standard applies", "standard for",
        "which is applies", "standard", "मानक", "बीआईएस मानक",
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
    क्या में के की का को से पर है हैं हो और या कौन कौनसा कैसे कहाँ कहां लिए मेरे मेरा मेरी मुझे बताएं बताइए चाहिए""".split()
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
}
_STATE_PHRASES = {norm_match(name): name for name in STATES_AND_UTS} | {
    norm_match(name): state for name, state in _HINDI_STATES.items()
} | {"jammu kashmir": "Jammu and Kashmir", "orissa": "Odisha", "pondicherry": "Puducherry", "new delhi": "Delhi"}

_DEVANAGARI = re.compile("[ऀ-ॿ]")
_RECOGNITION = re.compile(r"\b[A-Z]{2,4}/RAHC/R-\d{3,8}\b", re.IGNORECASE)
_BARE_NUMBER = re.compile(r"(?<![\w./:-])\d{2,5}(?![\w/:-])")
_MALFORMED_IS = re.compile(r"\bIS\s+\d+[A-Za-z]+\d+\b", re.IGNORECASE)


@dataclass
class Gazetteer:
    """Place names known from the official records: hallmarking districts (with aliases) and laboratory cities."""

    districts: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    cities: dict[str, tuple[str, str | None]] = field(default_factory=dict)

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
        return cls(districts, cities)


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
    material: str | None = None
    product: str | None = None
    application: str | None = None
    in_scope: bool = True
    clarification: str | None = None


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
    padded = _padded(text)
    tokens = norm_match(text).split()
    hits = _cue_hits(padded)

    recognition_nos = tuple(dict.fromkeys(match.group(0).upper() for match in _RECOGNITION.finditer(text)))
    if recognition_nos:
        hits[INTENT_HALLMARKING].append("recognition number")
    lab_or_standard_context = bool(hits[INTENT_LABS] or hits[INTENT_TESTS] or hits[INTENT_STANDARD])
    designations = extract_designations(_RECOGNITION.sub(" ", text))
    malformed_is = bool(_MALFORMED_IS.search(text))
    if malformed_is:
        designations = tuple(designation for designation in designations if not designation.raw.upper().startswith("IS "))
    if not designations and lab_or_standard_context:
        designations = extract_designations(" ".join(_BARE_NUMBER.findall(text)), assume_is_prefix=True)
    standard_refs = tuple(dict.fromkeys(designation.std_key for designation in designations))
    doc_numbers = tuple(dict.fromkeys(designation.number for designation in designations if designation.number))
    so_number = extract_so_number(text)

    state, state_tokens = _find_state(text, tokens)
    remaining = [token for token in tokens if token not in state_tokens]
    district, district_state, city, place_tokens = _find_place(remaining, gazetteer or Gazetteer())

    metal = None
    if any(word in padded for word in (" gold ", " सोना ", " सोने ")):
        metal = "gold"
    elif any(word in padded for word in (" silver ", " चांदी ")):
        metal = "silver"

    material = _find_entity(text, "material")
    product = _find_entity(text, "product")
    application = _find_entity(text, "application")

    cue_tokens = {token for cues in hits.values() for cue in cues for token in norm_match(cue).split()}
    identifier_tokens = {norm_match(part) for designation in designations for part in designation.raw.split()}
    identifier_tokens |= {"is", "part", "sec", *doc_numbers}
    product_words = [
        token
        for token in tokens
        if token not in cue_tokens
        and token not in identifier_tokens
        and token not in state_tokens
        and token not in place_tokens
        and token not in PRODUCT_STOP_WORDS
        and token not in QUESTION_WORDS
        and not token.isdigit()
    ]
    product_text = " ".join(product_words) or None
    in_scope = _has_domain_signal(text, (material, product, application, *standard_refs, *recognition_nos)) or any(hits.values())
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
        material=material,
        product=product,
        application=application,
        in_scope=in_scope,
        clarification=clarification,
    )


def district_key(name: str) -> str:
    return compact_district(name)
