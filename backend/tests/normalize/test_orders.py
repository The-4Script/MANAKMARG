from datetime import date

import pytest

from manakmarg.normalize.orders import (
    classify_order_kind,
    extract_gsr_number,
    extract_so_number,
    order_identity,
    parse_order_links,
)

SCHEME_I_URL = (
    "https://www.bis.gov.in/product-certification/products-under-compulsory-certification/"
    "scheme-i-mark-scheme/?lang=en"
)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Cement (Quality Control)Order, 2003 S.O. No. 191(E) Dt. 17 Feb 2003", "S.O. 191(E)"),
        ("Tin Ingot (Quality Control) Order, 2025 S.O. 1769 (E) Dated 17 April, 2025", "S.O. 1769(E)"),
        ("Notification No. S.O. 2357(E) dated 07 September 2012", "S.O. 2357(E)"),
        ("(S.O. 2290(E) dated 07/07/2020)", "S.O. 2290(E)"),
        ("SO No 2357 (E)", "S.O. 2357(E)"),
        ("Order, 2020", None),
    ],
)
def test_extract_so_number(text, expected):
    assert extract_so_number(text) == expected


def test_extract_gsr_number():
    assert extract_gsr_number("Gas Cylinder Rules, 2016 G.S.R. No. 1081(E) Dt. 22-11-2016") == "G.S.R. 1081(E)"
    assert extract_gsr_number("Gas Cylinders (Amendment) Rules, 2026 G.S.R. 315(E) Dated 28 April, 2026") == "G.S.R. 315(E)"
    assert extract_gsr_number("S.O. 191(E)") is None


@pytest.mark.parametrize(
    "text, kind",
    [
        ("Cement (Quality Control)Order, 2003 S.O. No. 191(E) Dt. 17 Feb 2003", "qco"),
        ("Tin Ingot (Quality Control) Amendment Order, 2025", "amendment"),
        ("Corrigendum for Bicycles Retro-Reflective Devices (Quality Control) Amendment Order, 2023", "corrigendum"),
        (
            "Deferment of upcoming phase implementation of the Electrical Equipment (Quality Control) Order 2020",
            "deferment",
        ),
        (
            "Order on extension in the date of enforcement of Quality Control Order on Stamping Laminations Cores "
            "of Transformers",
            "extension",
        ),
        ("Extension Order", "extension"),
        (
            "Rescind Machinery and Electrical Equipment Safety (Omnibus Technical Regulation) Order, 2024. "
            "S.O. 239(E) Dated 16 January, 2026",
            "rescission",
        ),
        (
            "Superseded by Electronics and Information Technology Goods (Requirement of Compulsory Registration) "
            "Order, 2021",
            "superseding_order",
        ),
        ("Gas Cylinder Rules, 2016 G.S.R. No. 1081(E) Dt. 22-11-2016", "rules"),
        ("Migration to IS/IEC 62368 : Part 1 : 2023 from IS 13252 : Part 1 : 2010", "other"),
    ],
)
def test_classify_order_kind(text, kind):
    assert classify_order_kind(text) == kind


def test_parse_order_links_builds_deduplicated_order_refs():
    links = [
        (
            "1. Cement (Quality Control)Order, 2003 S.O. No. 191(E) Dt. 17 Feb 2003",
            "https://www.bis.gov.in/MandatoryProducts/QCOrder/SO-No-191(E).pdf",
        ),
        ("Extension Order", "/wp-content/uploads/2020/10/Extension.pdf"),
        ("", "#"),
        ("Cement order again", "https://www.bis.gov.in/MandatoryProducts/QCOrder/SO-No-191(E).pdf"),
    ]
    refs = parse_order_links(links, page_url=SCHEME_I_URL)

    assert len(refs) == 2
    cement, extension = refs
    assert cement.title == "Cement (Quality Control)Order, 2003 S.O. No. 191(E) Dt. 17 Feb 2003"
    assert cement.kind == "qco"
    assert cement.so_number == "S.O. 191(E)"
    assert cement.order_date == date(2003, 2, 17)
    assert cement.url == "https://www.bis.gov.in/MandatoryProducts/QCOrder/SO-No-191(E).pdf"
    assert extension.url == "https://www.bis.gov.in/wp-content/uploads/2020/10/Extension.pdf"
    assert extension.kind == "extension"
    assert extension.order_date is None


def test_same_pdf_url_with_different_notification_numbers_stays_two_orders():
    pdf = "https://www.bis.gov.in/wp-content/uploads/2020/01/Cables_28012020.pdf"
    refs = parse_order_links(
        [
            ("(S.O.2019(E) dated 23/06/2020)", pdf, "Domestic Pressure Cooker (Quality Control) (Amendment) Order, 2020"),
            ("(S.O. 294 (E) dated 21/01/2020 )", pdf, "49. Cables (Quality Control) Order, 2020"),
            ("(S.O. 294 (E) dated 21/01/2020 )", pdf, "Cables (Quality Control) Order, 2020"),
        ],
        page_url=SCHEME_I_URL,
    )
    assert [ref.so_number for ref in refs] == ["S.O. 2019(E)", "S.O. 294(E)"]
    assert order_identity(refs[0].url, refs[0].so_number, None) != order_identity(refs[1].url, refs[1].so_number, None)
    assert all(ref.url == pdf for ref in refs)


def test_order_identity_without_a_number_is_the_url():
    assert order_identity("https://x/a.pdf", None, None) == "https://x/a.pdf"
    assert order_identity("https://x/a.pdf", None, "G.S.R. 843(E)") == "https://x/a.pdf#G.S.R. 843(E)"


def test_parse_order_links_uses_file_name_when_anchor_text_is_empty():
    refs = parse_order_links([("  ", "https://www.bis.gov.in/wp-content/uploads/2022/01/QCO-on-Polyphosphoric-Acid.pdf")], page_url=SCHEME_I_URL)
    assert refs[0].title == "QCO-on-Polyphosphoric-Acid.pdf"


def test_anchor_with_only_a_notification_number_takes_the_order_name_from_its_context_line():
    [ref] = parse_order_links(
        [
            (
                "S.O. No. 191(E) Dt. 17 Feb 2003",
                "https://www.bis.gov.in/MandatoryProducts/QCOrder/SO-No-191(E).pdf",
                "1. Cement (Quality Control)Order, 2003",
            )
        ],
        page_url=SCHEME_I_URL,
    )
    assert ref.kind == "qco"
    assert ref.title == "Cement (Quality Control)Order, 2003 — S.O. No. 191(E) Dt. 17 Feb 2003"
    assert ref.context == "Cement (Quality Control)Order, 2003"
    assert ref.so_number == "S.O. 191(E)"
    assert ref.order_date == date(2003, 2, 17)


def test_amendment_heading_context_classifies_the_notification():
    [ref] = parse_order_links(
        [("S.O. 165(E) dated 5 Feb 2004", "https://www.bis.gov.in/MandatoryProducts/QCOrder/SO-No-165(E).pdf", "Subsequent Amendments:")],
        page_url=SCHEME_I_URL,
    )
    assert ref.kind == "amendment"
    assert ref.order_date == date(2004, 2, 5)


def test_so_number_is_read_from_an_official_file_name_that_states_it():
    [ref] = parse_order_links(
        [
            (
                "No. 189(E) dated 17 Feb 2003",
                "https://www.bis.gov.in/MandatoryProducts/QCOrder/SO-No-189(E).pdf",
                "2. Electrical Wires, Cables, Appliances and Protection Devices and Accessories (Quality Control) Order, 2003",
            )
        ],
        page_url=SCHEME_I_URL,
    )
    assert ref.kind == "qco"
    assert ref.so_number == "S.O. 189(E)"


def test_file_name_without_so_marker_gives_no_so_number():
    [ref] = parse_order_links(
        [("SO 516(E), dated 25th May 1987", "https://bis.gov.in/MandatoryProducts/QCOrder/516_E.pdf")], page_url=SCHEME_I_URL
    )
    assert ref.so_number == "S.O. 516(E)"
    [unmarked] = parse_order_links([("Order copy", "https://bis.gov.in/MandatoryProducts/QCOrder/516_E.pdf")], page_url=SCHEME_I_URL)
    assert unmarked.so_number is None


def test_self_describing_anchor_keeps_its_own_title_and_records_context():
    [ref] = parse_order_links(
        [
            (
                "Extension Order",
                "https://www.bis.gov.in/wp-content/uploads/2020/10/Extension.pdf",
                "1. Steel and Steel Products (Quality Control) Order, 2020",
            )
        ],
        page_url=SCHEME_I_URL,
    )
    assert ref.kind == "extension"
    assert ref.title == "Extension Order"
    assert ref.context == "Steel and Steel Products (Quality Control) Order, 2020"
