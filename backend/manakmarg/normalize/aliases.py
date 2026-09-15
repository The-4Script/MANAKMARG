"""Query-side aliases: Hindi (Devanagari) and Hinglish domain words and place names mapped to the English terms the
indexed records use.

This is not translation. Only known entities and domain words are replaced, so the rule-based understanding and the
existing product search can match them; everything else in the question is left as written. Place names map to the
canonical spelling used by the official district and laboratory lists — they are resolved against those lists
afterwards, so an alias never creates a place that the records do not contain.
"""

import re
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
    "थर्मामीटर": "thermometer",
    "हेलमेट": "helmet",
    "खिलौनों": "toys",
    "पाइप": "pipe",
    "टायर": "tyre",
    # certification and testing
    "लाइसेंस": "licence",
    "लायसेंस": "licence",
    "प्रमाणन": "certification",
    "प्रमाणपत्र": "certificate",
    "प्राप्त": "obtain",
    "जाँच": "testing",
    "जांच": "testing",
    "परीक्षण": "testing",
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
    "कलकत्ता": "Kolkata",
    "मुंबई": "Mumbai",
    "चेन्नई": "Chennai",
    "बेंगलुरु": "Bengaluru",
    "बंगलौर": "Bengaluru",
    "हैदराबाद": "Hyderabad",
    "पुणे": "Pune",
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
    "कोयंबटूर": "Coimbatore",
    "मदुरै": "Madurai",
}

_WORD = r"[\wऀ-ॿ]"


@dataclass(frozen=True)
class AliasedText:
    text: str
    replacements: tuple[tuple[str, str], ...]


def _compile(aliases: dict[str, str]) -> list[tuple[re.Pattern, str, str]]:
    ordered = sorted(aliases.items(), key=lambda item: -len(item[0]))
    return [(re.compile(rf"(?<!{_WORD}){re.escape(term)}(?!{_WORD})", re.IGNORECASE), term, target) for term, target in ordered]


_PATTERNS = _compile(PLACE_ALIASES) + _compile(DOMAIN_ALIASES)


def apply_aliases(text: str | None) -> AliasedText:
    """``text`` with known Hindi/Hinglish entities replaced by their English record terms (longest match first)."""
    result = text or ""
    used: list[tuple[str, str]] = []
    for pattern, term, target in _PATTERNS:
        result, count = pattern.subn(f" {target} ", result)
        if count:
            used.append((term, target))
    return AliasedText(re.sub(r"\s{2,}", " ", result).strip(), tuple(used))
