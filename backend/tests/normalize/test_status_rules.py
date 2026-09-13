from datetime import date

from manakmarg.normalize.status_rules import classify_listing, upcoming_effect


def test_denotified_listing_is_detected_from_listing_text():
    decision = classify_listing(
        "scheme_i",
        "Food & Related Products De-notified from compulsory BIS certification",
        "Packaged Drinking Water (Other than Packaged Natural Mineral Water) De-notified from compulsory BIS certification",
        "Food Safety & Standards Prohibition & Restriction on Sales, Regulation, 2011",
    )
    assert decision.status == "DENOTIFIED"
    assert "De-notified from compulsory BIS certification" in decision.basis


def test_rescinded_notification_is_detected_and_quoted():
    decision = classify_listing(
        "scheme_x",
        "Machinery and Electrical Equipment covered under Omnibus Technical Regulation",
        "All types of Pumps for handling liquids, liquid elevators and (or)their assemblies",
        "Machinery and Electrical Equipment Safety (Omnibus Technical Regulation) Second Amendment Order, 2025 "
        "S.O. 5179(E) Dated 13 November, 2025 Rescind Machinery and Electrical Equipment Safety (Omnibus Technical "
        "Regulation) Order, 2024. S.O. 239(E) Dated 16 January, 2026",
    )
    assert decision.status == "RESCINDED"
    assert "Rescind" in decision.basis
    assert "S.O. 239(E)" in decision.basis


def test_upcoming_page_rows_are_upcoming():
    decision = classify_listing("upcoming_qco", "", "Linear Alkyl Benzene", "")
    assert decision.status == "UPCOMING"
    assert "Upcoming QCOs" in decision.basis


def test_scheme_rows_default_to_listed_compulsory_with_page_basis():
    decision = classify_listing(
        "scheme_i",
        "Cement (any variety of cement manufactured or sold in India) such as",
        "Ordinary Portland Cement",
        "1. Cement (Quality Control)Order, 2003 S.O. No. 191(E) Dt. 17 Feb 2003",
    )
    assert decision.status == "LISTED_COMPULSORY"
    assert "ISI Mark Scheme" in decision.basis


def test_denotified_takes_precedence_over_rescission():
    decision = classify_listing("scheme_i", "Items De-notified from compulsory BIS certification", "X", "Rescind order")
    assert decision.status == "DENOTIFIED"


def test_deferred_phase_needs_verification():
    decision = classify_listing(
        "scheme_x",
        "Low – Voltage switchgear and controlgear – Notified by Ministry of Heavy Industries",
        "AC Circuit – Breakers (Category – A)- All ratings above 630A , upto 440V AC",
        "Deferment of upcoming phase implementation of the Electrical Equipment (Quality Control) Order 2020 and "
        "subsequent amendments from time to time S.O. 5038(E), dated 6 November 2025",
    )
    assert decision.status == "NEEDS_VERIFICATION"
    assert "Deferment" in decision.basis
    assert "S.O. 5038(E)" in decision.basis


def test_rescission_takes_precedence_over_deferment():
    decision = classify_listing("scheme_x", "", "Pumps", "Deferment of phase S.O. 1(E) Rescind Order S.O. 2(E)")
    assert decision.status == "RESCINDED"


def test_upcoming_effect_is_computed_against_today():
    today = date(2026, 9, 13)
    assert upcoming_effect(date(2026, 10, 1), today=today) == "NOT_YET_IN_FORCE"
    assert upcoming_effect(date(2026, 9, 13), today=today) == "ENFORCEMENT_DATE_REACHED"
    assert upcoming_effect(date(2026, 9, 1), today=today) == "ENFORCEMENT_DATE_REACHED"
    assert upcoming_effect(None, today=today) == "DATE_UNKNOWN"
