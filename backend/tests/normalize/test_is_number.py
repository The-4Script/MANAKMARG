"""IS designation parsing. Cases are taken from formats observed in the supplied BIS exports,
the compulsory-certification pages, Product Specific Guidelines and LIMS (spec §2.1, §6.1)."""

import openpyxl
import pytest

from manakmarg.core import paths
from manakmarg.normalize.is_number import extract_designations, parse_designation


def _parsed(raw, **kwargs):
    designation = parse_designation(raw, **kwargs)
    assert designation is not None, raw
    return designation


# --------------------------------------------------------------------------- canonical keys


@pytest.mark.parametrize(
    "raw, std_key, family_key",
    [
        ("IS 14756:2024", "IS 14756:2024", "IS 14756"),
        ("IS 1281 : 2025", "IS 1281:2025", "IS 1281"),
        ("IS 16722  : 2018", "IS 16722:2018", "IS 16722"),
        ("IS 26: 2024", "IS 26:2024", "IS 26"),
        ("IS 1489 (Part 1)  : 2015", "IS 1489 (Part 1):2015", "IS 1489 (Part 1)"),
        ("IS 1554(Part 1) : 1988", "IS 1554 (Part 1):1988", "IS 1554 (Part 1)"),
        ("IS 9573(Part 1):2017", "IS 9573 (Part 1):2017", "IS 9573 (Part 1)"),
        ("IS/ISO/IEC 30118 (Part 12):2021", "IS/ISO/IEC 30118 (Part 12):2021", "IS/ISO/IEC 30118 (Part 12)"),
        ("IS/IEC 60793 (Part 1/Sec 46):2024", "IS/IEC 60793 (Part 1/Sec 46):2024", "IS/IEC 60793 (Part 1/Sec 46)"),
        ("IS 1554 (Part 1/Sec 2/Sub-Sec 3):2019", "IS 1554 (Part 1/Sec 2/Sub-Sec 3):2019", "IS 1554 (Part 1/Sec 2/Sub-Sec 3)"),
        ("IS 1554 (Part 1/Sec 2/SubSec 3):2019", "IS 1554 (Part 1/Sec 2/Sub-Sec 3):2019", "IS 1554 (Part 1/Sec 2/Sub-Sec 3)"),
        ("IS 10052 : Part 1 : Sec 6 : 2022", "IS 10052 (Part 1/Sec 6):2022", "IS 10052 (Part 1/Sec 6)"),
        ("IS/IEC 62368: Part 1: 2023", "IS/IEC 62368 (Part 1):2023", "IS/IEC 62368 (Part 1)"),
        ("IS/IEC 60947 : Part 5 : Sec 5 : 2016", "IS/IEC 60947 (Part 5/Sec 5):2016", "IS/IEC 60947 (Part 5/Sec 5)"),
        ("IS/ISO 18369 :Part1 : 2017", "IS/ISO 18369 (Part 1):2017", "IS/ISO 18369 (Part 1)"),
        ("IS/IEC/TR 62051:Part 1 : 2004", "IS/IEC/TR 62051 (Part 1):2004", "IS/IEC/TR 62051 (Part 1)"),
        ("IS 15449 : Part 1 : 2004", "IS 15449 (Part 1):2004", "IS 15449 (Part 1)"),
        ("IS 16444 Part 1", "IS 16444 (Part 1)", "IS 16444 (Part 1)"),
        ("IS 3055 (Pt 1): 1994", "IS 3055 (Part 1):1994", "IS 3055 (Part 1)"),
        ("IS 2062 (PART 2) : 2010", "IS 2062 (Part 2):2010", "IS 2062 (Part 2)"),
        ("IS 1391 (Part-1): 2017", "IS 1391 (Part 1):2017", "IS 1391 (Part 1)"),
        ("IS 504 (Part 1 To 12):2002", "IS 504 (Part 1 to 12):2002", "IS 504 (Part 1 to 12)"),
        ("IS 15642 (Part 1 AND 2):2006", "IS 15642 (Part 1 and 2):2006", "IS 15642 (Part 1 and 2)"),
        ("IS/ISO 105 (Part C12):2024", "IS/ISO 105 (Part C12):2024", "IS/ISO 105 (Part C12)"),
        ("IS/ISO/IEC/IEEE 8802 (Part 1X):2013", "IS/ISO/IEC/IEEE 8802 (Part 1X):2013", "IS/ISO/IEC/IEEE 8802 (Part 1X)"),
        ("IS 802.15.4:2021", "IS 802.15.4:2021", "IS 802.15.4"),
        ("IS H16500:2012", "IS H16500:2012", "IS H16500"),
        ("SP 1:1967", "SP 1:1967", "SP 1"),
        ("SP 15 (Part 1):1989", "SP 15 (Part 1):1989", "SP 15 (Part 1)"),
        ("IS/ISO5006:2017", "IS/ISO 5006:2017", "IS/ISO 5006"),
        ("IS/IEC61196 (Part 1/Sec 310):2005", "IS/IEC 61196 (Part 1/Sec 310):2005", "IS/IEC 61196 (Part 1/Sec 310)"),
        ("IS 12330", "IS 12330", "IS 12330"),
    ],
)
def test_canonical_keys(raw, std_key, family_key):
    designation = _parsed(raw)
    assert designation.std_key == std_key
    assert designation.family_key == family_key


def test_plain_designation_fields_and_no_flags():
    designation = _parsed("IS 1608 (Part 5):2026")
    assert designation.prefix == "IS"
    assert designation.number == "1608"
    assert designation.part == "5"
    assert designation.section is None
    assert designation.year == 2026
    assert designation.suffix is None
    assert designation.number_key == "1608"
    assert designation.flags == ()


def test_designation_without_year():
    designation = _parsed("IS 12330")
    assert designation.year is None
    assert designation.match_key == "IS 12330"


# --------------------------------------------------------------------------- prefixes


@pytest.mark.parametrize(
    "raw, std_key, flag",
    [
        ("Is 18889:2024", "IS 18889:2024", "prefix_case"),
        ("IS/IEc 62232:2022", "IS/IEC 62232:2022", "prefix_case"),
        ("IS ISO 6204:2024", "IS/ISO 6204:2024", "prefix_repaired"),
        ("IS/IEC/IEE 63195 (Part 1):2022", "IS/IEC/IEEE 63195 (Part 1):2022", "prefix_repaired"),
        ("IS/IEc IEEE 63195 (Part 2):2022", "IS/IEC/IEEE 63195 (Part 2):2022", "prefix_repaired"),
        ("IS/ISO/IECTR 20226:2025", "IS/ISO/IEC/TR 20226:2025", "prefix_repaired"),
        ("IS/ISO/IECTS 12791:2024", "IS/ISO/IEC/TS 12791:2024", "prefix_repaired"),
        ("IS/IEC TS 61400 (Part 29):2023", "IS/IEC/TS 61400 (Part 29):2023", "prefix_repaired"),
    ],
)
def test_prefix_irregularities_are_normalized_and_flagged(raw, std_key, flag):
    designation = _parsed(raw)
    assert designation.std_key == std_key
    assert flag in designation.flags


@pytest.mark.parametrize(
    "raw, prefix",
    [
        ("IS/QC 301800:2001", "IS/QC"),
        ("IS/ISO/IEC GUIDE 99:2007", "IS/ISO/IEC/GUIDE"),
        ("IS/ISO/IEC Guide 14:2018", "IS/ISO/IEC/GUIDE"),
        ("IS/CISPR TR 29:2020", "IS/CISPR/TR"),
        ("IS/IWA 31:2020", "IS/IWA"),
        ("IS/ISO/PAS 50010:2023", "IS/ISO/PAS"),
        ("IS/ISO/TS 13143-2:2011", "IS/ISO/TS"),
        ("ISO/SAE 21434:2021", "ISO/SAE"),
        ("IEC 61000 (Part 5/Sec 2):2026", "IEC"),
        ("ISO 24342:2024", "ISO"),
    ],
)
def test_recognised_prefixes(raw, prefix):
    assert _parsed(raw).prefix == prefix


def test_prefix_is_part_of_identity():
    indigenous = _parsed("IS 13450:2020")
    adopted = _parsed("IS/ISO 13450:2020")
    assert indigenous.std_key != adopted.std_key
    assert indigenous.family_key != adopted.family_key
    assert indigenous.match_key != adopted.match_key
    assert indigenous.number_key == adopted.number_key == "13450"


def test_prefix_is_assumed_only_when_requested():
    assert parse_designation("4003 (Part 1):1978") is None
    designation = _parsed("4003 (Part 1):1978", assume_is_prefix=True)
    assert designation.std_key == "IS 4003 (Part 1):1978"
    assert "prefix_assumed" in designation.flags
    assert _parsed("4003(Part 2):1986", assume_is_prefix=True).std_key == "IS 4003 (Part 2):1986"
    assert _parsed("14756:2022", assume_is_prefix=True).std_key == "IS 14756:2022"


@pytest.mark.parametrize("text", ["", "   ", "Stainless steel utensils", "Clause 4.2.2", "2023", "S.O. 3583(E)"])
def test_non_designations_return_none(text):
    assert parse_designation(text) is None


# --------------------------------------------------------------------------- hyphen / underscore parts


def test_iso_hyphen_part_keeps_identity_but_matches_part_form():
    designation = _parsed("IS/ISO 80000-9:2019")
    assert designation.part == "9"
    assert designation.std_key == "IS/ISO 80000-9:2019"
    assert designation.family_key == "IS/ISO 80000-9"
    assert designation.match_key == "IS/ISO 80000 (Part 9)"
    assert _parsed("IS/ISO 80000 (Part 9):2019").match_key == designation.match_key


def test_letter_coded_hyphen_part():
    designation = _parsed("IS/ISO 105-E04:2013")
    assert designation.part == "E04"
    assert designation.match_key == "IS/ISO 105 (Part E04)"
    assert _parsed("IS/ISO 105 (Part E04):2013").match_key == designation.match_key


def test_multi_level_hyphen_parts():
    designation = _parsed("IS/IEC 60794-1-2:2021")
    assert (designation.part, designation.section) == ("1", "2")
    assert designation.std_key == "IS/IEC 60794-1-2:2021"
    assert designation.match_key == "IS/IEC 60794 (Part 1/Sec 2)"


def test_is_302_hyphen_style_matches_part_section_form():
    assert _parsed("IS 302-2-76:1999").match_key == _parsed("IS 302 (Part 2/Sec 76):1999").match_key
    assert _parsed("IS 302-1 : 2008").match_key == "IS 302 (Part 1)"


def test_hyphen_part_with_space_before_hyphen():
    assert _parsed("IS/IEC 61730 -1").match_key == "IS/IEC 61730 (Part 1)"


def test_colon_separated_letter_part_is_repaired():
    designation = _parsed("IS/ISO 105:B01:2014")
    assert designation.part == "B01"
    assert designation.year == 2014
    assert designation.std_key == "IS/ISO 105 (Part B01):2014"
    assert "malformed_repaired" in designation.flags


def test_underscore_parts_are_repaired():
    designation = _parsed("IS/IEC 60371_3_9:1995")
    assert (designation.part, designation.section) == ("3", "9")
    assert designation.std_key == "IS/IEC 60371-3-9:1995"
    assert designation.match_key == "IS/IEC 60371 (Part 3/Sec 9)"
    assert "malformed_repaired" in designation.flags


# --------------------------------------------------------------------------- years


def test_lims_parenthesized_year_with_part():
    designation = _parsed("IS 2062 (Part 2) (2026)")
    assert designation.std_key == "IS 2062 (Part 2):2026"
    assert "year_in_parentheses" in designation.flags


def test_lims_parenthesized_year_only():
    assert _parsed("IS 16415 (2015)").std_key == "IS 16415:2015"


def test_lims_colon_part_with_parenthesized_year():
    assert _parsed("IS 1554 : Part 1 (1988)").std_key == "IS 1554 (Part 1):1988"


def test_missing_colon_before_year():
    designation = _parsed("IS 16910 (Part 2/Sec 11)2026")
    assert designation.std_key == "IS 16910 (Part 2/Sec 11):2026"
    assert "missing_year_colon" in designation.flags


def test_duplicated_year():
    designation = _parsed("IS 6560:2017:2017")
    assert designation.std_key == "IS 6560:2017"
    assert "duplicate_year" in designation.flags


def test_year_out_of_range_is_flagged():
    assert "year_out_of_range" in _parsed("IS 1234:2099").flags
    assert "year_out_of_range" in _parsed("IS 1234:1800").flags


# --------------------------------------------------------------------------- suffixes, ranges, repairs


@pytest.mark.parametrize(
    "raw, std_key, family_key, match_key, suffix",
    [
        ("IS 6882:2026 P", "IS 6882 P:2026", "IS 6882 P", "IS 6882", "P"),
        ("IS 19257 P:2025", "IS 19257 P:2025", "IS 19257 P", "IS 19257", "P"),
        ("IS 19877T:2026", "IS 19877 T:2026", "IS 19877 T", "IS 19877", "T"),
        ("IS 17899 T:2024", "IS 17899 T:2024", "IS 17899 T", "IS 17899", "T"),
        ("IS 667 Supplement:1981", "IS 667 Supplement:1981", "IS 667 Supplement", "IS 667", "Supplement"),
        ("SP 25(S&T):1984", "SP 25 (S&T):1984", "SP 25 (S&T)", "SP 25", "(S&T)"),
        ("SP 64 (S & T):2001", "SP 64 (S&T):2001", "SP 64 (S&T)", "SP 64", "(S&T)"),
        ("SP 57 (QAWSM):1993", "SP 57 (QAWSM):1993", "SP 57 (QAWSM)", "SP 57", "(QAWSM)"),
    ],
)
def test_suffixes_stay_in_identity(raw, std_key, family_key, match_key, suffix):
    designation = _parsed(raw)
    assert designation.std_key == std_key
    assert designation.family_key == family_key
    assert designation.match_key == match_key
    assert designation.suffix == suffix
    assert "suffix" in designation.flags


def test_number_range():
    designation = _parsed("IS 4864 to 4870:1968")
    assert designation.std_key == "IS 4864 to 4870:1968"
    assert designation.number_key == "4864"
    assert "number_range" in designation.flags


@pytest.mark.parametrize(
    "raw, std_key",
    [
        ("IS):7779 ( (Part 1/Sec 1)):1975", "IS 7779 (Part 1/Sec 1):1975"),
        ("IS 5887 (Part 5/Sec 1)):2023", "IS 5887 (Part 5/Sec 1):2023"),
        ("IS 16502 (Part 3):):2020", "IS 16502 (Part 3):2020"),
        ("IS 6398):Part 2):2020", "IS 6398 (Part 2):2020"),
        ("IS/ISO 7507):Part 2):2005", "IS/ISO 7507 (Part 2):2005"),
        ("IS/IEC 60794 (Part 1):Sec):1):2023", "IS/IEC 60794 (Part 1/Sec 1):2023"),
    ],
)
def test_malformed_designations_are_repaired_and_flagged(raw, std_key):
    designation = _parsed(raw)
    assert designation.std_key == std_key
    assert "malformed_repaired" in designation.flags


def test_unrecognised_designation_keeps_a_stable_key():
    designation = _parsed("ISIHB MMAW:1965")
    assert "unparsed" in designation.flags
    assert designation.std_key == "ISIHB MMAW:1965"
    assert designation.year == 1965


# --------------------------------------------------------------------------- extraction from text


def _keys(designations):
    return [designation.std_key for designation in designations]


def test_extract_dual_reference():
    assert _keys(extract_designations("IS 13422: 2024 / ISO 10282: 2023")) == ["IS 13422:2024", "ISO 10282:2023"]


def test_parse_designation_returns_the_primary_reference():
    assert _parsed("IS 13422: 2024 / ISO 10282: 2023").std_key == "IS 13422:2024"
    assert _parsed("IS 2403 :2014 / ISO 606 : 2004").std_key == "IS 2403:2014"
    assert _parsed("IS 18471 (Part 1) : 2023/ ISO 15481").std_key == "IS 18471 (Part 1):2023"


def test_extract_multiple_is_references():
    assert _keys(extract_designations("IS 14286 IS/IEC 61730 -1 IS/IEC 61730 -2")) == [
        "IS 14286",
        "IS/IEC 61730-1",
        "IS/IEC 61730-2",
    ]


def test_extract_is_with_iec_reference():
    assert _keys(extract_designations("IS 302 (Part 1) : 2024 IEC 60335-1:2020")) == [
        "IS 302 (Part 1):2024",
        "IEC 60335-1:2020",
    ]


def test_extract_from_requirement_sentence():
    text = (
        "Made from BIS standard marked Grain Oriented Electrical Steel Sheet and Strip conforming to "
        "IS 3024:2015 or Cold rolled non-oriented electrical steel sheet and strip conforming to IS 648:2006 "
        "or Magnetic materials specification for individual material Fe based amorphous strip delivered in "
        "the semi-processed state conforming to IS 16585 : 2016"
    )
    assert _keys(extract_designations(text)) == ["IS 3024:2015", "IS 648:2006", "IS 16585:2016"]


def test_extract_ignores_clause_numbers():
    assert _keys(extract_designations("Clause 4.2.2 of IS 10613: 2023")) == ["IS 10613:2023"]


def test_extract_type_a_standard():
    text = "Type A Standard IS 16189:2018/ ISO 12100:2010 (Safety of Machinery General Principles)"
    assert _keys(extract_designations(text)) == ["IS 16189:2018", "ISO 12100:2010"]


def test_extract_repeated_parts_of_one_family():
    assert _keys(extract_designations("IS 12933 (Part 1): 2003 IS 12933 (Part 2): 2003")) == [
        "IS 12933 (Part 1):2003",
        "IS 12933 (Part 2):2003",
    ]


def test_extract_deduplicates_identical_references():
    assert _keys(extract_designations("IS 269 and again IS 269")) == ["IS 269"]


def test_extract_with_assumed_prefix():
    assert _keys(extract_designations("4003 (Part 1):1978", assume_is_prefix=True)) == ["IS 4003 (Part 1):1978"]
    assert extract_designations("4003 (Part 1):1978") == []


# --------------------------------------------------------------------------- real supplied data

_EXPORTS = [paths.DATA_DIR / "1.xlsx", paths.DATA_DIR / "2.xlsx"]


@pytest.mark.skipif(not all(path.exists() for path in _EXPORTS), reason="supplied BIS exports not present")
def test_every_supplied_designation_parses_without_key_collisions():
    raw_values = set()
    for path in _EXPORTS:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for row in workbook.worksheets[0].iter_rows(min_row=3, values_only=True):
            if row[1]:
                raw_values.add(str(row[1]).strip())
        workbook.close()

    by_key: dict[str, set[str]] = {}
    unparsed = []
    for raw in raw_values:
        designation = parse_designation(raw)
        assert designation is not None, raw
        if "unparsed" in designation.flags:
            unparsed.append(raw)
        by_key.setdefault(designation.std_key, set()).add(raw)

    collisions = {key: values for key, values in by_key.items() if len(values) > 1}
    assert len(unparsed) <= 3, unparsed
    assert collisions == {}
