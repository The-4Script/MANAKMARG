"""Sound-alike recovery of product words that speech-to-text misheard.

Transcripts of Hindi speech often differ from the intended word in ways that do not change how it sounds to a
listener: aspiration (घी heard as गी, "ghee" written "gee"), retroflex and dental consonants (दूध / डूध), vowel length
(ी / ि), nukta, a stray trailing "s", and a postposition glued to the word ("ghee ka" → "geeka", "घी का" → "गीका").
``sound_alike`` maps such a word to the English record term of the one lexicon entry with the same phonetic key.

Only unambiguous matches are returned (a key shared by entries with different targets is dropped), keys shorter than
two sounds are ignored, and the caller applies this only to words no record could match — a known word is never
replaced.
"""

import re
from functools import lru_cache

from manakmarg.normalize.lexicon import PRODUCT_LEXICON

_DEVANAGARI_FOLD = str.maketrans(
    {
        "ख": "क", "घ": "ग", "छ": "च", "झ": "ज", "ठ": "त", "ढ": "द", "थ": "त", "ध": "द", "फ": "प", "भ": "ब",
        "ट": "त", "ड": "द", "ण": "न", "ष": "स", "श": "स", "ी": "ि", "ू": "ु", "ई": "इ", "ऊ": "उ", "ै": "े",
        "ौ": "ो", "ऐ": "ए", "औ": "ओ", "़": None, "ं": None, "ँ": None, "्": None, "ः": None, "ॉ": "ो",
    }
)
_LATIN_RULES = (
    (re.compile(r"([bcdgjkpt])h"), r"\1"),  # aspiration: ghee → gee, dhaga → daga, khaad → kaad
    (re.compile(r"ee|ii"), "i"),
    (re.compile(r"oo|uu"), "u"),
    (re.compile(r"aa"), "a"),
    (re.compile(r"w"), "v"),
    (re.compile(r"z"), "j"),
    (re.compile(r"(.)\1+"), r"\1"),
)
_POSTPOSITION_SUFFIX = re.compile(r"^(?P<word>.+?)(?:का|के|की|ka|ke|ki|kaa)$")
_DEVANAGARI = re.compile("[ऀ-ॿ]")


def phonetic_key(word: str) -> str:
    word = word.lower()
    if _DEVANAGARI.search(word):
        key = word.translate(_DEVANAGARI_FOLD)
    else:
        key = word
        for pattern, replacement in _LATIN_RULES:
            key = pattern.sub(replacement, key)
        key = key.rstrip("h")
    # A trailing plural/stray "s" does not change the word ("डूद्स" → "दूध").
    return key[:-1] if len(key) > 2 and key[-1] in "sस" else key


@lru_cache(maxsize=1)
def _index() -> dict[str, str]:
    targets: dict[str, set[str]] = {}
    for term, target in PRODUCT_LEXICON.items():
        if " " in term:
            continue
        # One-word English targets are indexed too, so a romanised mishearing of the English word ("gee") is recovered.
        forms = [term] if " " in target else [term, target]
        for form in forms:
            key = phonetic_key(form)
            if len(key) >= 2:
                targets.setdefault(key, set()).add(target)
    return {key: next(iter(found)) for key, found in targets.items() if len(found) == 1}


def sound_alike(word: str) -> str | None:
    """The English record term ``word`` most plausibly was, or ``None``. Tries the word as heard, then with a merged
    postposition removed ("geeka" → "gee" → "ghee")."""
    index = _index()
    candidates = [word]
    merged = _POSTPOSITION_SUFFIX.match(word.lower())
    if merged:
        candidates.append(merged.group("word"))
    for candidate in candidates:
        target = index.get(phonetic_key(candidate))
        if target:
            return target
    return None
