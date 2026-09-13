from datetime import date

import pytest

from manakmarg.normalize.dates import find_dates, parse_date


@pytest.mark.parametrize(
    "text, expected",
    [
        ("04 Aug 2026", date(2026, 8, 4)),
        ("30 September 2026", date(2026, 9, 30)),
        ("01 October, 2026", date(2026, 10, 1)),
        ("  05 June 2027 ", date(2027, 6, 5)),
        ("23rd June, 2021", date(2021, 6, 23)),
        ("Order Dated 4th April, 2022", date(2022, 4, 4)),
        ("11 th November 2020", date(2020, 11, 11)),
        ("31 Dec, 2026", date(2026, 12, 31)),
        ("06 Sept 2025", date(2025, 9, 6)),
        ("31/07/2028", date(2028, 7, 31)),
        ("14.02.2027", date(2027, 2, 14)),
        ("17-11-2017", date(2017, 11, 17)),
        ("Dt. 17 Feb 2003", date(2003, 2, 17)),
    ],
)
def test_parse_date_formats_used_by_bis_sources(text, expected):
    assert parse_date(text) == expected


@pytest.mark.parametrize("text", [None, "", "-", "NULL", "31/02/2026", "Sr No", "2026", "Order, 2020"])
def test_parse_date_rejects_non_dates(text):
    assert parse_date(text) is None


def test_find_dates_in_notification_text():
    text = (
        "Cookware and Utensils (Quality Control) Order, 2023 S.O. 3583(E), dated 9th August 2023 "
        "Cookware, Utensils and Cans for foods and beverages (Quality Control) Order , 2024 "
        "S.O. 1365(E), dated 14th March 2024"
    )
    assert find_dates(text) == [date(2023, 8, 9), date(2024, 3, 14)]


def test_find_dates_with_wef_prefix_and_numeric_formats():
    assert find_dates("- Included w.e.f.12.03.2025") == [date(2025, 3, 12)]
    text = "Suspension revoked w.e.f. 23-08-2024 (Present status operative) Suspended w.e.f. 05-04-2024."
    assert find_dates(text) == [date(2024, 8, 23), date(2024, 4, 5)]


def test_find_dates_tolerates_line_break_inside_numeric_date():
    assert find_dates("Suspended w.e.f. 05- 04-2024") == [date(2024, 4, 5)]


def test_parse_date_month_first_textual_dates_on_bis_pages():
    assert parse_date("Last Updated on April 15, 2026") == date(2026, 4, 15)
    assert parse_date("February 3, 2026") == date(2026, 2, 3)
    assert find_dates("Last Updated on April 15, 2026") == [date(2026, 4, 15)]
    assert find_dates("Dated 31 July, 2025 and 5 March 2026") == [date(2025, 7, 31), date(2026, 3, 5)]


def test_find_dates_ignores_order_years_and_notification_numbers():
    assert find_dates("Steel and Steel Products (Quality Control) Order, 2020 S.O. 1673(E)") == []
