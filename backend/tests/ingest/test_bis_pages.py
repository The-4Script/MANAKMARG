"""Certification-process, apply-for-licence, FAQ and overview page parsers on trimmed real snapshots."""

from datetime import date
from pathlib import Path

import pytest

from manakmarg.ingest.bis_pages import (
    parse_apply_licence,
    parse_certification_process_docs,
    parse_faq_page,
    parse_page_text,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "bis"
APPLY_URL = "https://www.bis.gov.in/apply-for-a-license/?lang=en"
PROCESS_URL = "https://www.bis.gov.in/product-certification/product-certification-process/?lang=en"
CERT_FAQ_URL = "https://www.bis.gov.in/product-certification/product-certification-faq/?lang=en"
OVERVIEW_URL = "https://www.bis.gov.in/product-certification/products-under-compulsory-certification/?lang=en"


def _read(name):
    return (FIXTURES / name).read_bytes()


def test_apply_licence_steps_keep_official_order_and_links():
    steps = parse_apply_licence(_read("apply_licence.html"), APPLY_URL)
    assert len(steps) == 10
    assert [step.ordinal for step in steps] == list(range(1, 11))
    assert steps[0].text.startswith("Application process starts with identification of Indian Standard")
    assert steps[0].link_url is None
    assert steps[1].link_url == "https://standardsbis.bsbedge.com/"
    assert [step.step_label for step in steps].count("5") == 2
    assert steps[8].link_label == "www.manakonline.in"
    assert steps[8].link_url == "https://www.manakonline.in/MANAK/ApplicationLicenceRelatedrpt"
    assert steps[9].link_url is None


def test_certification_process_documents_are_grouped_by_scheme():
    documents = parse_certification_process_docs(_read("certification_process.html"), PROCESS_URL)
    scheme_i = [document for document in documents if document.scheme_id == "SCHEME_I"]
    scheme_iv = [document for document in documents if document.scheme_id == "SCHEME_IV"]
    assert (len(scheme_i), len(scheme_iv)) == (11, 4)
    assert len(documents) == 15

    regulation = scheme_i[0]
    assert regulation.category == "regulation"
    assert regulation.title.startswith("Scheme-I of BIS (Conformity Assessment) Regulation")
    assert regulation.url.endswith("BIS_CA_12032019.pdf#page=243")

    grant = next(document for document in documents if document.title == "Guidelines for Grant of Licence")
    assert grant.category == "guideline"
    assert grant.size_text == "271 KB"
    assert grant.url == "https://www.bis.gov.in/wp-content/uploads/2026/02/GrantofLicence-Guidelines-25Feb2026.pdf"

    assert scheme_iv[0].category == "regulation"
    assert scheme_iv[1].title == "Guidelines for grant of certificate of conformity"
    assert all("size" not in document.title.lower() for document in documents)
    assert [document.ordinal for document in documents] == list(range(1, 16))


@pytest.mark.parametrize(
    "fixture, category, count, first_question",
    [
        ("faq_product_certification.html", "product_certification", 28, "What is a licence?"),
        (
            "faq_laboratory.html",
            "laboratory",
            10,
            "Where to get my product tested for the purpose of applying for the various conformity assessment schemes of BIS?",
        ),
        ("faq_hallmarking_general.html", "hallmarking_general", 25, "What is Hallmarking?"),
        (
            "faq_hallmarking_mandatory.html",
            "hallmarking_mandatory",
            6,
            "Can people sell their old jewellery to jewelers after Hallmarking becomes mandatory?",
        ),
    ],
)
def test_faq_pages(fixture, category, count, first_question):
    faqs = parse_faq_page(_read(fixture), category, CERT_FAQ_URL)
    assert len(faqs) == count
    assert faqs[0].question == first_question
    assert [faq.ordinal for faq in faqs] == list(range(1, count + 1))
    assert all(faq.question and faq.answer for faq in faqs)
    assert all(faq.category == category for faq in faqs)
    assert len({faq.locator for faq in faqs}) == count


def test_faq_answers_keep_text_and_links():
    faqs = parse_faq_page(_read("faq_product_certification.html"), "product_certification", CERT_FAQ_URL)
    assert faqs[0].answer.startswith("Licence means a licence granted under Section 13 of BIS Act 2016")
    assert faqs[1].question.startswith("I am a manufacturer of a product")
    assert "https://www.manakonline.in/MANAK/ApplicationLicenceRelatedrpt" in [url for _, url in faqs[1].answer_links]


def test_faq_numbering_is_removed_from_questions():
    faqs = parse_faq_page(_read("faq_hallmarking_general.html"), "hallmarking_general", CERT_FAQ_URL)
    assert faqs[2].question.startswith("What are the Indian Standards on Hallmarking")
    assert "IS 1417: 2016" in faqs[2].answer


def test_overview_page_text():
    page = parse_page_text(_read("compulsory_overview.html"), OVERVIEW_URL)
    assert page.title == "Products under Compulsory Certification"
    assert any(paragraph.startswith("BIS certification scheme is basically voluntary in nature.") for paragraph in page.paragraphs)
    assert any(url.endswith("Guidance-document-on-QCOs-Revised-1.pdf") for _, url in page.links)
    assert page.last_updated == date(2026, 4, 15)
    assert not any(paragraph.startswith("Last Updated") for paragraph in page.paragraphs)
    assert not any(paragraph == "Home" for paragraph in page.paragraphs)
