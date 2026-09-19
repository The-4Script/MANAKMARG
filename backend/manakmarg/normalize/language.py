"""Response language: answer in the language the user wrote or spoke in.

Devanagari text is answered in Hindi and plain English in English. Romanised Hindi (Hinglish) and questions made only
of identifiers ("IS 2062") carry no reliable signal, so they keep the language selected in the interface. Only the
presentation changes: the records behind the answer are identical in both languages.
"""

import re

LANGUAGES = ("en", "hi")
# Devanagari letters and vowel signs; Devanagari digits (०-९) and the danda are not a language signal on their own.
_DEVANAGARI_LETTER = re.compile("[ऀ-ॣॱ-ॿ]")
_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
HINGLISH_WORDS = frozenset(
    """hai hain kya kyaa mein mei ke ka ki ko se mujhe muje liye lie batao bataye bataiye batayein btao kaunsa konsa
    kaun kaise kahan kahaan chahiye hota hoti hoga milega zaroori jaruri zaruri anivarya janch jaanch aur nahi nahin
    wala wale wali mera meri mere karna karni kare lagu""".split()
)
_IDENTIFIER_WORDS = frozenset({"is", "bis", "qco", "qcos", "hsn", "ahc", "ahcs", "huid", "so", "gsr", "sac", "isi", "part", "sec"})


def detect_language(text: str | None, fallback: str = "en") -> str:
    """``"hi"`` for Devanagari input, ``"en"`` for English input, otherwise ``fallback`` (the selected UI language)."""
    fallback = fallback if fallback in LANGUAGES else "en"
    text = text or ""
    if _DEVANAGARI_LETTER.search(text):
        return "hi"
    words = [word.lower() for word in _LATIN_WORD.findall(text)]
    if any(word in HINGLISH_WORDS for word in words):
        return fallback
    if any(word not in _IDENTIFIER_WORDS for word in words):
        return "en"
    return fallback
