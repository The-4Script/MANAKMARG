"""Query-side aliases: Hindi (Devanagari) and Hinglish domain words and place names mapped to the English terms the
indexed records use.

This is not translation. Only known entities and domain words are replaced, so the rule-based understanding and the
existing product search can match them; everything else in the question is left as written. Place names map to the
canonical spelling used by the official district and laboratory lists — they are resolved against those lists
afterwards, so an alias never creates a place that the records do not contain.

Typed and transcribed Hindi vary in spelling, so matching is tolerant of the variants that do not change a word:
chandrabindu/anusvara (जाँच/जांच), nukta (गाज़ियाबाद/गाजियाबाद), invisible joiners and Devanagari digits (२०६२).
Genuinely different spellings (कोलकत्ता, बंबई) and English words written in Devanagari by speech-to-text (कॉपर वायर)
are listed explicitly. Nothing is fuzzy-matched here.
"""

import re
import unicodedata
from dataclasses import dataclass

DOMAIN_ALIASES: dict[str, str] = {
    # products and materials
    "स्टेनलेस स्टील": "stainless steel",
    "स्टेनलेस": "stainless",
    "स्टील": "steel",
    "इस्पात": "steel",
    "संरचनात्मक": "structural",
    "बर्तनों": "utensils",
    "बर्तन": "utensils",
    "सीमेंट": "cement",
    "केबलों": "cables",
    "केबल": "cable",
    "पीवीसी": "pvc",
    "तारों": "wires",
    "तार": "wire",
    "थर्मामीटर": "thermometer",
    "हेलमेट": "helmet",
    "खिलौनों": "toys",
    "पाइप": "pipe",
    "टायर": "tyre",
    "तांबा": "copper",
    "तांबे": "copper",
    # English product words as speech-to-text writes them in Devanagari
    "कॉपर": "copper",
    "कोपर": "copper",
    "वायर": "wire",
    # certification, standards and testing
    "भारतीय मानक ब्यूरो": "BIS",
    "बीआईएस": "BIS",
    "बी आई एस": "BIS",
    "आईएसआई": "ISI",
    "आई एस आई": "ISI",
    "आईएस": "IS",
    "आई एस": "IS",
    "मानक": "standard",
    "स्टैंडर्ड": "standard",
    "स्टेंडर्ड": "standard",
    "लाइसेंस": "licence",
    "लायसेंस": "licence",
    "लाइसन्स": "licence",
    "लायसन्स": "licence",
    "लाईसेंस": "licence",
    "प्रमाणन": "certification",
    "सर्टिफिकेशन": "certification",
    "प्रमाणपत्र": "certificate",
    "सर्टिफिकेट": "certificate",
    "प्राप्त": "obtain",
    "जाँच": "testing",
    "जांच": "testing",
    "जाज": "testing",  # speech-to-text rendering of जाँच
    "परीक्षण": "testing",
    "टेस्टिंग": "testing",
    "लैब्स": "labs",
    "लाब": "lab",  # speech-to-text rendering of लैब
    "लैबोरेटरी": "laboratory",
    "लेबोरेटरी": "laboratory",
    "लेबोरेट्री": "laboratory",
    "प्रयोगशालाओं": "laboratories",
    "मैंडेटरी": "mandatory",
    "मेंडेटरी": "mandatory",
    "क्यूसीओ": "QCO",
    "स्कीम": "scheme",
    "योजना": "scheme",
    "आगामी": "upcoming",
    # hallmarking
    "हॉलमार्किंग": "hallmarking",
    "हालमार्किंग": "hallmarking",
    # speech-to-text often splits the word
    "हॉल मार्किंग": "hallmarking",
    "हाल मार्किंग": "hallmarking",
    "हॉल मार्क": "hallmark",
    "हाल मार्क": "hallmark",
    "हॉलमार्क": "hallmark",
    "हालमार्क": "hallmark",
    "चाँदी": "silver",
    "चांदी": "silver",
    "केंद्र": "centre",
    "केन्द्र": "centre",
    # HSN lookup
    "एचएसएन": "hsn",
    # Hinglish
    "jaanch": "testing",
    "janch": "testing",
    "praman patra": "certificate",
}

PLACE_ALIASES: dict[str, str] = {
    "नई दिल्ली": "New Delhi",
    "जयपुर": "Jaipur",
    "कोलकाता": "Kolkata",
    "कोलकत्ता": "Kolkata",
    "कोलकता": "Kolkata",
    "कलकत्ता": "Kolkata",
    "कलकता": "Kolkata",
    "मुंबई": "Mumbai",
    "मुम्बई": "Mumbai",
    "बंबई": "Mumbai",
    "बम्बई": "Mumbai",
    "चेन्नई": "Chennai",
    "चेन्नै": "Chennai",
    "बेंगलुरु": "Bengaluru",
    "बेंगलूरु": "Bengaluru",
    "बंगलौर": "Bengaluru",
    "बैंगलोर": "Bengaluru",
    "हैदराबाद": "Hyderabad",
    "पुणे": "Pune",
    "पूना": "Pune",
    "अहमदाबाद": "Ahmedabad",
    "सूरत": "Surat",
    "लखनऊ": "Lucknow",
    "कानपुर": "Kanpur",
    "जोधपुर": "Jodhpur",
    "उदयपुर": "Udaipur",
    "अजमेर": "Ajmer",
    "बीकानेर": "Bikaner",
    "कोटा": "Kota",
    "इंदौर": "Indore",
    "भोपाल": "Bhopal",
    "पटना": "Patna",
    "चंडीगढ़": "Chandigarh",
    "नागपुर": "Nagpur",
    "आगरा": "Agra",
    "वाराणसी": "Varanasi",
    "नोएडा": "Noida",
    "गुरुग्राम": "Gurugram",
    "गुड़गांव": "Gurugram",
    "गाजियाबाद": "Ghaziabad",
    "गाज़ियाबाद": "Ghaziabad",
    "राजकोट": "Rajkot",
    "वडोदरा": "Vadodara",
    "लुधियाना": "Ludhiana",
    "अमृतसर": "Amritsar",
    "गुवाहाटी": "Guwahati",
    "भुवनेश्वर": "Bhubaneswar",
    "रांची": "Ranchi",
    "रायपुर": "Raipur",
    "देहरादून": "Dehradun",
    "मेरठ": "Meerut",
    "नाशिक": "Nashik",
    "नासिक": "Nashik",
    "कोयंबटूर": "Coimbatore",
    "मदुरै": "Madurai",
}

_WORD = r"[\wऀ-ॿ]"
_INVISIBLE = re.compile("[​-‍⁠﻿]")
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


@dataclass(frozen=True)
class AliasedText:
    text: str
    replacements: tuple[tuple[str, str], ...]


def clean_script(text: str | None) -> str:
    """Canonical Unicode form without invisible joiners, with Devanagari digits as ASCII digits."""
    return _INVISIBLE.sub("", unicodedata.normalize("NFC", text or "")).translate(_DEVANAGARI_DIGITS)


def _spelling_variants(term: str) -> set[str]:
    """Spellings of ``term`` that differ only by chandrabindu/anusvara or nukta."""
    forms = {term}
    forms |= {form.replace("ँ", "ं") for form in forms} | {form.replace("ं", "ँ") for form in forms}
    forms |= {form.replace("़", "") for form in forms}
    return forms


def _compile(aliases: dict[str, str]) -> list[tuple[re.Pattern, str, str]]:
    entries: dict[str, tuple[str, str]] = {clean_script(term): (term, target) for term, target in aliases.items()}
    for form, (term, target) in list(entries.items()):
        for variant in _spelling_variants(form):
            entries.setdefault(variant, (term, target))  # a listed spelling always keeps its own target
    ordered = sorted(entries.items(), key=lambda item: -len(item[0]))
    return [(re.compile(rf"(?<!{_WORD}){re.escape(form)}(?!{_WORD})", re.IGNORECASE), term, target) for form, (term, target) in ordered]


_PATTERNS = _compile(PLACE_ALIASES) + _compile(DOMAIN_ALIASES)
# Speech-to-text writes "IS-2062" or "IS:2062"; the question form of the identifier is "IS 2062". Only the separator
# right after the prefix changes (a year suffix such as ":2011" is kept), and only in the user's question.
_IDENTIFIER_SEPARATOR = re.compile(r"(?<![A-Za-z0-9])(IS|SP)\s*[-:.]\s*(?=\d)")


def apply_aliases(text: str | None) -> AliasedText:
    """``text`` with known Hindi/Hinglish entities replaced by their English record terms (longest match first)."""
    result = clean_script(text)
    used: list[tuple[str, str]] = []
    for pattern, term, target in _PATTERNS:
        result, count = pattern.subn(f" {target} ", result)
        if count and (term, target) not in used:
            used.append((term, target))
    result = _IDENTIFIER_SEPARATOR.sub(r"\1 ", result)
    return AliasedText(re.sub(r"\s{2,}", " ", result).strip(), tuple(used))
