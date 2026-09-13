"""Quantities and unit conversion for gap analysis.

Values are converted only within one physical dimension. An unrecognised or incompatible unit is never guessed:
the comparison is reported as UNKNOWN instead.
"""

import re
from dataclasses import dataclass

# alias (lower case, spaces removed) → (canonical symbol, dimension, factor to the dimension's base unit)
UNITS: dict[str, tuple[str, str, float]] = {}


def _define(symbol: str, dimension: str, factor: float, *aliases: str) -> None:
    for alias in (symbol, *aliases):
        UNITS[alias.lower().replace(" ", "")] = (symbol, dimension, factor)


for _args in (
    ("mm", "length", 1.0, "millimetre", "millimeter", "millimetres", "millimeters"),
    ("cm", "length", 10.0, "centimetre", "centimeter"),
    ("m", "length", 1000.0, "metre", "meter", "metres", "meters"),
    # NFKC text normalisation turns the micro sign (U+00B5) into Greek mu (U+03BC), so both spellings are units.
    ("µm", "length", 0.001, "μm", "um", "micron", "microns", "micrometre", "micrometer"),
    ("g", "mass", 1.0, "gm", "gram", "grams"),
    ("kg", "mass", 1000.0, "kilogram", "kilograms"),
    ("mg", "mass", 0.001, "milligram", "milligrams"),
    ("N", "force", 1.0, "newton", "newtons"),
    ("kN", "force", 1000.0),
    ("kgf", "force", 9.80665),
    ("MPa", "pressure", 1.0, "n/mm2", "n/mm²", "n/sq.mm"),
    ("kPa", "pressure", 0.001),
    ("Pa", "pressure", 0.000001),
    ("bar", "pressure", 0.1),
    ("kgf/cm²", "pressure", 0.0980665, "kgf/cm2"),
    ("%", "percent", 1.0, "percent", "per cent"),
    ("°C", "temperature", 1.0, "degc", "°c", "℃", "degreescelsius", "deg.c"),
    ("s", "time", 1.0, "sec", "secs", "second", "seconds"),
    ("min", "time", 60.0, "mins", "minute", "minutes"),
    ("h", "time", 3600.0, "hr", "hrs", "hour", "hours"),
    ("ml", "volume", 1.0, "millilitre", "milliliter"),
    ("l", "volume", 1000.0, "litre", "liter", "litres", "liters", "ltr"),
    ("V", "voltage", 1.0, "volt", "volts"),
    ("kV", "voltage", 1000.0),
    ("A", "current", 1.0, "amp", "amps", "ampere", "amperes"),
    ("mA", "current", 0.001),
    ("W", "power", 1.0, "watt", "watts"),
    ("kW", "power", 1000.0),
    ("Hz", "frequency", 1.0),
    ("Ω", "resistance", 1.0, "ohm", "ohms"),
    ("MΩ", "resistance", 1_000_000.0, "megohm", "megaohm", "megohms"),
    ("HV", "hardness_vickers", 1.0),
    ("HRC", "hardness_rockwell_c", 1.0),
    ("HB", "hardness_brinell", 1.0),
    ("dB", "sound_level", 1.0),
    ("lux", "illuminance", 1.0, "lx"),
):
    _define(*_args)

NUMBER = r"[-+]?\d+(?:[.,]\d+)?"
UNIT_TOKEN = r"(?:%|°\s?C|℃|[A-Za-zµμΩ]+(?:\s?/\s?(?:sq\.?\s?)?[A-Za-z]+[2²]?)?)"
_QUANTITY = re.compile(rf"(?P<value>{NUMBER})\s*(?P<unit>{UNIT_TOKEN})?")


@dataclass(frozen=True)
class Quantity:
    value: float
    unit: str | None
    unit_raw: str | None
    dimension: str | None


def _number(text: str) -> float:
    return float(text.replace(",", "."))


def lookup_unit(raw: str | None) -> tuple[str, str, float] | None:
    if not raw:
        return None
    return UNITS.get(raw.lower().replace(" ", ""))


def parse_quantity(text: str | None) -> Quantity | None:
    for match in _QUANTITY.finditer(text or ""):
        unit_raw = (match.group("unit") or "").strip() or None
        found = lookup_unit(unit_raw)
        return Quantity(_number(match.group("value")), found[0] if found else None, unit_raw, found[1] if found else None)
    return None


def to_base(value: float, unit: str | None) -> tuple[float, str | None]:
    """Value expressed in its dimension's base unit (mm, g, N, MPa, %, °C, s, ml, V, A, W, …)."""
    found = lookup_unit(unit)
    if found is None:
        return value, None
    base_symbol = next(symbol for symbol, dimension, factor in UNITS.values() if dimension == found[1] and factor == 1.0)
    return value * found[2], base_symbol


def compatible(first: str | None, second: str | None) -> bool:
    a, b = lookup_unit(first), lookup_unit(second)
    if a is None or b is None:
        return (first or "").strip().lower() == (second or "").strip().lower()
    return a[1] == b[1]
