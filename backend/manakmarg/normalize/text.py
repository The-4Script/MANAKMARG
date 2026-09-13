"""Text helpers: whitespace, matching normalisation, standard-title parts and attributed snippets."""

import re
import unicodedata
from dataclasses import dataclass

_WHITESPACE = re.compile(r"\s+")
_NON_WORD = re.compile(r"[\W_]+")
_ORDINALS = (
    "first",
    "second",
    "third",
    "fourth",
    "fifth",
    "sixth",
    "seventh",
    "eighth",
    "ninth",
    "tenth",
    "eleventh",
    "twelfth",
)
_REVISION = re.compile(r"\b(" + "|".join(_ORDINALS) + r")\s+revision\b", re.IGNORECASE)
_AMENDMENT = re.compile(r"\bamendment\s*(?:no\.?)?\s*[-:]?\s*(\d+)\b", re.IGNORECASE)


@dataclass(frozen=True)
class TitleParts:
    title_clean: str
    revision_label: str | None
    amendment_label: str | None


def clean_ws(value: str | None) -> str:
    if value is None:
        return ""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", value)).strip()


def norm_match(value: str | None) -> str:
    """Lower-case, punctuation-free form used for matching names.

    Letters, digits and combining marks of every script are kept: Devanagari vowel signs are marks, and treating
    them as separators would split words such as "राजस्थान"."""
    text = unicodedata.normalize("NFKC", value or "").lower()
    kept = "".join(char if unicodedata.category(char)[0] in "LNM" else " " for char in text)
    return _WHITESPACE.sub(" ", kept).strip()


def split_title(title: str | None) -> TitleParts:
    clean = clean_ws(title)
    clean = re.sub(r"\(\s+", "(", clean)
    clean = re.sub(r"\s+\)", ")", clean)
    revision = _REVISION.search(clean)
    amendment = _AMENDMENT.search(clean)
    return TitleParts(
        title_clean=clean,
        revision_label=f"{revision.group(1).capitalize()} Revision" if revision else None,
        amendment_label=f"Amendment {amendment.group(1)}" if amendment else None,
    )


def snippet(value: str | None, limit: int = 300) -> str:
    """Whitespace-normalised text cut at a word boundary to at most ``limit`` characters."""
    text = clean_ws(value)
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:-") + "…"
