import pytest

from manakmarg.normalize.geo import (
    compact_district,
    district_equivalents,
    norm_district,
    normalize_state,
    parse_ahc_address,
    parse_lims_address,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("U.P.", "Uttar Pradesh"),
        ("UTTAR PRADESH", "Uttar Pradesh"),
        ("M.P.", "Madhya Pradesh"),
        ("W.B.", "West Bengal"),
        ("Tamilnadu", "Tamil Nadu"),
        ("Tamil Nadu", "Tamil Nadu"),
        ("Chhattisgargh", "Chhattisgarh"),
        ("PONDICHERY", "Puducherry"),
        ("Pondicherry", "Puducherry"),
        ("Jammu & Kashmir", "Jammu and Kashmir"),
        ("ANDAMAN & NICOBAR", "Andaman and Nicobar Islands"),
        ("DAMAN & DIU", "Dadra and Nagar Haveli and Daman and Diu"),
        ("New Delhi", "Delhi"),
        ("DELHI", "Delhi"),
        ("Orissa", "Odisha"),
        ("Telangana", "Telangana"),
        ("Pubjab", "Punjab"),
    ],
)
def test_normalize_state(raw, expected):
    assert normalize_state(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "India", "Sector 65", "-"])
def test_normalize_state_unknown(raw):
    assert normalize_state(raw) is None


def test_norm_district():
    assert norm_district("Jaunpur District") == "jaunpur"
    assert norm_district("  SOUTH  DELHI ") == "south delhi"
    assert norm_district("Kotputli-Behror") == "kotputli behror"


def test_district_equivalents_cover_curated_renames_only():
    assert compact_district("South East Delhi") == "southeastdelhi"
    assert district_equivalents("Gurugram") == {"gurugram", "gurgaon"}
    assert district_equivalents("Bengaluru Urban") == {"bengaluruurban", "bangaloreurban"}
    assert district_equivalents("Jaipur") == {"jaipur"}
    assert district_equivalents("") == set()


def test_parse_ahc_address_delhi():
    address = parse_ahc_address(
        "II-C/16 Lajpat Nagar Central Market New Delhi, SOUTH DELHI, LAJPAT NAGAR (SOUTH DELHI), DELHI ,110025"
    )
    assert address.district == "South Delhi"
    assert address.area == "Lajpat Nagar (South Delhi)"
    assert address.state == "Delhi"
    assert address.pincode == "110025"
    assert address.lines == "II-C/16 Lajpat Nagar Central Market New Delhi"


def test_parse_ahc_address_with_commas_in_street():
    address = parse_ahc_address(
        "2165-2166,4th FLOOR, CHAKSU KA CHOWKHALDIYON KA RASTA, JOHARI BAZAR JAIPUR, JAIPUR, JAIPUR CITY, "
        "RAJASTHAN ,302003"
    )
    assert (address.district, address.area, address.state, address.pincode) == (
        "Jaipur",
        "Jaipur City",
        "Rajasthan",
        "302003",
    )


def test_parse_ahc_address_suspended_list_format():
    address = parse_ahc_address("19, CHANDNI CHOWK, RATLAMRATLAM , M.P., RATLAM, RATLAM CITY, MADHYA PRADESH ,457001")
    assert (address.district, address.state, address.pincode) == ("Ratlam", "Madhya Pradesh", "457001")


def test_parse_ahc_address_keeps_positions_when_area_is_blank():
    address = parse_ahc_address(
        "HOLDING NO. 67/N,NACHAN ROAD,BENACHITY,DURGAPURDURGAPUR-713213, BARDHAMAN, , WEST BENGAL ,713213"
    )
    assert (address.district, address.area, address.state, address.pincode) == (
        "Bardhaman",
        None,
        "West Bengal",
        "713213",
    )
    assert address.lines == "HOLDING NO. 67/N, NACHAN ROAD, BENACHITY, DURGAPURDURGAPUR-713213"


def test_parse_lims_address_full():
    address = parse_lims_address("C - 57, Sector - 65, Noida, Gautam Buddha Nagar, Uttar Pradesh, India - 201301")
    assert address.city == "Noida"
    assert address.district == "Gautam Buddha Nagar"
    assert address.state == "Uttar Pradesh"
    assert address.pincode == "201301"
    assert address.lines == "C - 57, Sector - 65"


def test_parse_lims_address_delhi():
    address = parse_lims_address("19-University Road, Delhi 110007, Delhi, North, Delhi, India - 110007")
    assert (address.city, address.district, address.state, address.pincode) == ("Delhi", "North", "Delhi", "110007")


def test_parse_lims_address_without_pincode():
    address = parse_lims_address("Khordha, Odisha, India -")
    assert address.state == "Odisha"
    assert address.district == "Khordha"
    assert address.city is None
    assert address.pincode is None


def test_parse_lims_address_lowercase_city_is_title_cased():
    address = parse_lims_address(
        "Plot No D-53, IDA, Phase-1, Jeedimetla,Qutubullapur Mandal, hyderabad, Medchal Malkajgiri, Telangana, "
        "India - 500055"
    )
    assert address.city == "Hyderabad"
    assert address.district == "Medchal Malkajgiri"
    assert address.state == "Telangana"
