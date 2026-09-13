"""Indian geography normalisation.

The state/UT names, abbreviations and address layouts below are curated matching aids (registry
source ``curated_geography``); they never override what an official record says.
"""

import re
from dataclasses import dataclass

STATES_AND_UTS = (
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Assam",
    "Bihar",
    "Chhattisgarh",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Madhya Pradesh",
    "Maharashtra",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Odisha",
    "Punjab",
    "Rajasthan",
    "Sikkim",
    "Tamil Nadu",
    "Telangana",
    "Tripura",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal",
    "Andaman and Nicobar Islands",
    "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi",
    "Jammu and Kashmir",
    "Ladakh",
    "Lakshadweep",
    "Puducherry",
)


def _state_key(value: str) -> str:
    return re.sub(r"[^a-z]", "", value.lower().replace("&", "and"))


_STATE_VARIANTS = {
    "up": "Uttar Pradesh",
    "mp": "Madhya Pradesh",
    "wb": "West Bengal",
    "hp": "Himachal Pradesh",
    "ap": "Andhra Pradesh",
    "tn": "Tamil Nadu",
    "chhattisgargh": "Chhattisgarh",
    "chattisgarh": "Chhattisgarh",
    "pondichery": "Puducherry",
    "pondicherry": "Puducherry",
    "jk": "Jammu and Kashmir",
    "jandk": "Jammu and Kashmir",
    "andamanandnicobar": "Andaman and Nicobar Islands",
    "dadraandnagarhaveli": "Dadra and Nagar Haveli and Daman and Diu",
    "damananddiu": "Dadra and Nagar Haveli and Daman and Diu",
    "newdelhi": "Delhi",
    "nctofdelhi": "Delhi",
    "orissa": "Odisha",
    "uttaranchal": "Uttarakhand",
    "uttrakhand": "Uttarakhand",
    "pubjab": "Punjab",
    "tamilnadu": "Tamil Nadu",
}

_STATE_LOOKUP = {_state_key(name): name for name in STATES_AND_UTS} | _STATE_VARIANTS


@dataclass(frozen=True)
class Address:
    lines: str | None = None
    area: str | None = None
    city: str | None = None
    district: str | None = None
    state: str | None = None
    state_raw: str | None = None
    pincode: str | None = None


def normalize_state(value: str | None) -> str | None:
    if not value:
        return None
    key = _state_key(value)
    return _STATE_LOOKUP.get(key) if key else None


def norm_district(value: str | None) -> str:
    text = (value or "").lower()
    text = re.sub(r"\bdistrict\b|\bdistt?\b\.?", " ", text)
    text = re.sub(r"[\W_]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact_district(value: str | None) -> str:
    return norm_district(value).replace(" ", "")


# Well-known official renamings and common alternative spellings (compact lower-case names). Matching aids only:
# official records keep their own spelling and results found through an equivalent are labelled.
CURATED_DISTRICT_EQUIVALENTS = (
    frozenset({"gurgaon", "gurugram"}),
    frozenset({"allahabad", "prayagraj"}),
    frozenset({"belgaum", "belagavi"}),
    frozenset({"bangaloreurban", "bengaluruurban"}),
    frozenset({"bangalore", "bengaluru"}),
    frozenset({"mysore", "mysuru"}),
    frozenset({"gulbarga", "kalaburagi"}),
    frozenset({"shimoga", "shivamogga"}),
    frozenset({"tumkur", "tumakuru"}),
    frozenset({"hissar", "hisar"}),
    frozenset({"rohatak", "rohtak"}),
    frozenset({"kochbihar", "coochbehar", "koochbehar"}),
    frozenset({"pondichery", "pondicherry", "puducherry"}),
)


def district_equivalents(value: str | None) -> set[str]:
    """Compact names equivalent to ``value`` under the curated renames (including itself)."""
    compact = compact_district(value)
    names = {compact} if compact else set()
    for group in CURATED_DISTRICT_EQUIVALENTS:
        if compact in group:
            names |= group
    return names


def _display(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip(" ,")
    if not value:
        return None
    return value.title() if value.isupper() or value.islower() else value


def _comma_parts(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


_AHC_PINCODE = re.compile(r",?\s*(\d{6})\s*$")
_LIMS_TAIL = re.compile(r",?\s*India\s*-\s*(\d{6})?\s*$", re.IGNORECASE)


def parse_ahc_address(value: str | None) -> Address:
    """Manakonline AHC layout: ``<street>, DISTRICT, AREA, STATE ,PINCODE``."""
    text = re.sub(r"\s+", " ", value or "").strip()
    pincode = None
    match = _AHC_PINCODE.search(text)
    if match:
        pincode = match.group(1)
        text = text[: match.start()]
    # Positions matter: the area may be published blank ("…, BARDHAMAN, , WEST BENGAL"), so empty parts are
    # only dropped from the street lines.
    parts = [part.strip() for part in text.split(",")]
    while parts and not parts[-1]:
        parts.pop()
    if len(parts) < 3:
        return Address(lines=text or None, pincode=pincode)
    return Address(
        lines=", ".join(part for part in parts[:-3] if part) or None,
        area=_display(parts[-2]),
        district=_display(parts[-3]),
        state=normalize_state(parts[-1]),
        state_raw=parts[-1],
        pincode=pincode,
    )


def parse_lims_address(value: str | None) -> Address:
    """LIMS layout: ``<street>, City, District, State, India - PINCODE``."""
    text = re.sub(r"\s+", " ", value or "").strip()
    pincode = None
    match = _LIMS_TAIL.search(text)
    if match:
        pincode = match.group(1)
        text = text[: match.start()]
    parts = _comma_parts(text)
    state = normalize_state(parts[-1]) if parts else None
    if state is None:
        return Address(lines=text or None, pincode=pincode)
    return Address(
        lines=", ".join(parts[:-3]) or None,
        city=_display(parts[-3]) if len(parts) >= 3 else None,
        district=_display(parts[-2]) if len(parts) >= 2 else None,
        state=state,
        state_raw=parts[-1],
        pincode=pincode,
    )
