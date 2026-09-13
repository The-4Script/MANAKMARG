"""Indian Standard designation parsing and canonical keys (spec §6.1).

A designation such as ``IS 1489 (Part 1)  : 2015`` is parsed into prefix, number, part/section,
suffix and year, and three keys are derived:

* ``std_key``    — identity of one published version. Prefix and suffix are part of identity, and the
                   hyphen notation of adopted ISO/IEC parts (``IS/ISO 80000-9``) is preserved.
* ``family_key`` — ``std_key`` without the year: all versions of one standard.
* ``match_key``  — family rendered with ``(Part n/Sec m)`` and without suffix. Used only to resolve
                   references written in another notation; never used to merge records.

Irregularities are normalised but recorded in ``flags`` for the data-quality report.
"""

import re
import unicodedata
from dataclasses import dataclass

from manakmarg.core import clock

KNOWN_PREFIX_TOKENS = frozenset(
    {"IS", "SP", "ISO", "IEC", "IEEE", "CISPR", "QC", "TS", "TR", "PAS", "IWA", "GUIDE", "SAE"}
)
_TOKEN_REPAIRS = {"IEE": ("IEEE",), "IECTR": ("IEC", "TR"), "IECTS": ("IEC", "TS")}


@dataclass(frozen=True)
class Designation:
    raw: str
    prefix: str
    number: str
    part: str | None = None
    section: str | None = None
    subsection: str | None = None
    year: int | None = None
    suffix: str | None = None
    flags: tuple[str, ...] = ()
    hyphen_parts: bool = False

    def _render(self, *, parts_in_parentheses: bool, with_suffix: bool) -> str:
        text = f"{self.prefix} {self.number}" if self.prefix else self.number
        if self.part:
            if self.hyphen_parts and not parts_in_parentheses:
                text += "".join(f"-{piece}" for piece in (self.part, self.section, self.subsection) if piece)
            else:
                inner = f"Part {self.part}"
                if self.section:
                    inner += f"/Sec {self.section}"
                if self.subsection:
                    inner += f"/Sub-Sec {self.subsection}"
                text += f" ({inner})"
        if with_suffix and self.suffix:
            text += f" {self.suffix}"
        return text

    @property
    def family_key(self) -> str:
        return self._render(parts_in_parentheses=False, with_suffix=True)

    @property
    def std_key(self) -> str:
        return self.family_key if self.year is None else f"{self.family_key}:{self.year}"

    @property
    def match_key(self) -> str:
        return self._render(parts_in_parentheses=True, with_suffix=False)

    @property
    def number_key(self) -> str:
        return self.number.split()[0]


# --------------------------------------------------------------------------- grammar

_PART_VALUE = r"[A-Z]?\d+[A-Z]?(?:\s*(?i:to|and|&)\s*\d+)?"

_BODY_TEMPLATE = r"""
    (?P<prefix>
        (?:ISO|IEC|IS|Is|SP)(?![A-Za-z])
        (?:
            \s*/\s*(?i:[a-z]{2,6})(?![A-Za-z])
          | \s+(?i:ISO|IEC|IEEE|TS|TR|GUIDE)(?=[\s/])
        )*
    )__PREFIX_QUANTIFIER__
    \s*
    (?P<std_noise>Std\s*)?
    (?P<number>[A-Z]?\d+(?:\.\d+)*(?:\s+(?i:to)\s+\d+)?)(?!\d)
    (?:\s?-\s?(?P<hp1>[A-Z]?\d+[A-Z]?)(?:-(?P<hp2>\d+))?(?:-(?P<hp3>\d+))?)?
    (?:_(?P<up1>\d+)_(?P<up2>\d+)(?:_(?P<up3>\d+))?)?
    (?::(?P<clp>[A-Z]\d{2,3})(?=\s*:\s*\d{4}))?
    (?:\s*\(\s*(?i:part|pt\.?)\s*[-.]?\s*(?P<ppart>__PART__)
        (?:\s*/\s*(?i:sec(?:tion)?\.?)\s*(?P<psec>__PART__))?
        (?:\s*/\s*(?i:sub-?sec(?:tion)?\.?)\s*(?P<psub>__PART__))?
     \s*\))?
    (?:\s*:\s*(?i:part)\s*(?P<cpart>__PART__)
        (?:\s*:\s*(?i:sec(?:tion)?\.?)\s*(?P<csec>__PART__))?)?
    (?:\s+(?i:part)\s*(?P<bpart>\d+))?
    (?:\s*(?P<suffix>\(\s*(?:S\s*&\s*T|QAWSM)\s*\)|Supplement|Tm|[PT])(?![A-Za-z0-9]))?
    (?:
        \s*:\s*(?P<year>\d{4})(?!\d)(?:\s*:\s*(?P<dupyear>\d{4})(?!\d))?
      | \s*\(\s*(?P<pyear>\d{4})\s*\)
      | (?<=\))(?P<nyear>\d{4})(?!\d)
    )?
    (?:\s+(?P<tsuffix>[PT])(?![A-Za-z0-9]))?
""".replace("__PART__", _PART_VALUE)

_BODY_PREFIXED = _BODY_TEMPLATE.replace("__PREFIX_QUANTIFIER__", "")
_BODY_OPTIONAL_PREFIX = _BODY_TEMPLATE.replace("__PREFIX_QUANTIFIER__", "?")

_ANCHORED = re.compile(r"^\s*" + _BODY_PREFIXED, re.VERBOSE)
_ANCHORED_ASSUMED = re.compile(r"^\s*" + _BODY_OPTIONAL_PREFIX, re.VERBOSE)
_SCAN = re.compile(r"(?<![A-Za-z0-9])" + _BODY_PREFIXED, re.VERBOSE)
_SCAN_ASSUMED = re.compile(r"(?<![A-Za-z0-9./:])" + _BODY_OPTIONAL_PREFIX, re.VERBOSE)

_REMAINDER_OK = re.compile(r"^\s*(?:$|[/,;|&]|(?:and|or)\s|(?:ISO|IEC|IS|SP)(?![A-Za-z]))")

_UNPARSED = re.compile(r"^(?P<body>[A-Za-z].*?)\s*:\s*(?P<year>\d{4})\s*$")

_REPAIRS = (
    (re.compile(r"\)\s*:\s*Sec\s*\)\s*:\s*(\w+)\s*\)"), r"/Sec \1)"),
    (re.compile(r"^((?:IS|SP)[A-Za-z/ ]*?)\)\s*:\s*(?=\d)"), r"\1 "),
    (re.compile(r"(\d)\)\s*:\s*Part\s*(\w+)\s*\)"), r"\1 (Part \2)"),
    (re.compile(r"\(\s*\("), "("),
    (re.compile(r"\)\s*:\s*\)"), ")"),
    (re.compile(r"\)\s*\)"), ")"),
)

_CHARACTER_FIXES = str.maketrans({"–": "-", "—": "-", "‑": "-", "−": "-"})


# --------------------------------------------------------------------------- helpers


def _prepare(text: str) -> str:
    return unicodedata.normalize("NFKC", text).translate(_CHARACTER_FIXES).strip()


def _repair(text: str) -> tuple[str, bool]:
    repaired = text
    for pattern, replacement in _REPAIRS:
        repaired = pattern.sub(replacement, repaired)
    return repaired, repaired != text


def _normalize_prefix(raw_prefix: str) -> tuple[str | None, set[str]]:
    flags: set[str] = set()
    if any(character.islower() for character in raw_prefix):
        flags.add("prefix_case")
    if re.search(r"[A-Za-z]\s+[A-Za-z]", raw_prefix):
        flags.add("prefix_repaired")
    tokens: list[str] = []
    for piece in re.split(r"\s*/\s*|\s+", raw_prefix.strip()):
        if not piece:
            continue
        token = piece.upper()
        if token in _TOKEN_REPAIRS:
            tokens.extend(_TOKEN_REPAIRS[token])
            flags.add("prefix_repaired")
        elif token in KNOWN_PREFIX_TOKENS:
            tokens.append(token)
        else:
            return None, flags
    return "/".join(tokens), flags


def _normalize_part(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value.strip())
    value = re.sub(r"\s*\b[Tt][Oo]\b\s*", " to ", value)
    value = re.sub(r"\s*(?:\b[Aa][Nn][Dd]\b|&)\s*", " and ", value)
    return value.upper() if re.fullmatch(r"[A-Za-z]?\d+[A-Za-z]?", value) else value


def _normalize_suffix(value: str) -> str:
    value = value.strip()
    if value.startswith("("):
        return "(" + re.sub(r"\s+", "", value[1:-1]) + ")"
    return value


def _year_flags(year: int) -> set[str]:
    return set() if 1900 <= year <= clock.today().year + 1 else {"year_out_of_range"}


def _from_match(match: re.Match, raw: str, extra_flags: set[str]) -> Designation | None:
    flags = set(extra_flags)

    if match.group("prefix"):
        prefix, prefix_flags = _normalize_prefix(match.group("prefix"))
        if prefix is None:
            return None
        flags |= prefix_flags
    else:
        prefix = "IS"
        flags.add("prefix_assumed")

    if match.group("std_noise"):
        flags.add("malformed_repaired")
    number = match.group("number")
    if re.search(r"\s(?i:to)\s", number):
        number = re.sub(r"\s+(?i:to)\s+", " to ", number)
        flags.add("number_range")

    part = section = subsection = None
    hyphen_parts = False
    if match.group("hp1"):
        part, section, subsection = match.group("hp1"), match.group("hp2"), match.group("hp3")
        hyphen_parts = True
    elif match.group("up1"):
        part, section, subsection = match.group("up1"), match.group("up2"), match.group("up3")
        hyphen_parts = True
        flags.add("malformed_repaired")
    elif match.group("clp"):
        part = match.group("clp")
        flags.add("malformed_repaired")
    elif match.group("ppart"):
        part, section, subsection = match.group("ppart"), match.group("psec"), match.group("psub")
    elif match.group("cpart"):
        part, section = match.group("cpart"), match.group("csec")
    elif match.group("bpart"):
        part = match.group("bpart")

    suffix = match.group("suffix") or match.group("tsuffix")
    if suffix:
        suffix = _normalize_suffix(suffix)
        flags.add("suffix")

    year = None
    if match.group("year"):
        year = int(match.group("year"))
        if match.group("dupyear"):
            flags.add("duplicate_year")
    elif match.group("pyear"):
        year = int(match.group("pyear"))
        flags.add("year_in_parentheses")
    elif match.group("nyear"):
        year = int(match.group("nyear"))
        flags.add("missing_year_colon")
    if year is not None:
        flags |= _year_flags(year)

    return Designation(
        raw=raw.strip(),
        prefix=prefix,
        number=number,
        part=_normalize_part(part),
        section=_normalize_part(section),
        subsection=_normalize_part(subsection),
        year=year,
        suffix=suffix,
        flags=tuple(sorted(flags)),
        hyphen_parts=hyphen_parts,
    )


def _unparsed(raw: str, cleaned: str) -> Designation | None:
    match = _UNPARSED.match(cleaned)
    if match is None:
        return None
    year = int(match.group("year"))
    body = re.sub(r"\s+", " ", match.group("body")).strip()
    return Designation(
        raw=raw.strip(),
        prefix="",
        number=body,
        year=year,
        flags=tuple(sorted({"unparsed"} | _year_flags(year))),
    )


# --------------------------------------------------------------------------- public API


def parse_designation(text: str | None, *, assume_is_prefix: bool = False) -> Designation | None:
    """Parse the primary designation in ``text``; ``None`` when the text is not a designation.

    ``assume_is_prefix`` allows a bare number (``4003 (Part 1):1978``) and should only be used for
    cells known to hold Indian Standard numbers.
    """
    if not text or not text.strip():
        return None
    cleaned, repaired = _repair(_prepare(text))
    pattern = _ANCHORED_ASSUMED if assume_is_prefix else _ANCHORED
    match = pattern.match(cleaned)
    if match and _REMAINDER_OK.match(cleaned[match.end():]):
        designation = _from_match(match, text, {"malformed_repaired"} if repaired else set())
        if designation is not None:
            return designation
    return _unparsed(text, cleaned)


def extract_designations(text: str | None, *, assume_is_prefix: bool = False) -> list[Designation]:
    """All designations mentioned in free text, in order of appearance, without duplicates."""
    if not text:
        return []
    cleaned = _prepare(text)
    pattern = _SCAN_ASSUMED if assume_is_prefix else _SCAN
    found: list[Designation] = []
    seen: set[str] = set()
    for match in pattern.finditer(cleaned):
        designation = _from_match(match, match.group(0), set())
        if designation is None or designation.std_key in seen:
            continue
        seen.add(designation.std_key)
        found.append(designation)
    return found
