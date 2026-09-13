"""BIS process pages and FAQs (plan Task 4.2).

* ``parse_apply_licence`` — the official "Apply for Licence" steps in page order. Step labels are kept as
  printed (the page numbers two different steps "5").
* ``parse_certification_process_docs`` — guideline documents on the Product Certification Process page,
  grouped under the scheme paragraph that precedes each list.
* ``parse_faq_page`` — accordion question/answer pairs, numbering removed, answer links kept.
* ``parse_page_text`` — title, text blocks, links and the "Last Updated on" date of an overview page.

Wording is kept verbatim apart from whitespace; nothing is summarised.
"""

import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from manakmarg.ingest.html_grid import cell_lines
from manakmarg.normalize.dates import parse_date
from manakmarg.normalize.text import clean_ws

_SIZE = re.compile(r"\(\s*size\s*[–—-]\s*([^)]*?)\s*\)", re.IGNORECASE)
_SCHEME = re.compile(r"\bScheme\s*[-–—]?\s*(IV|IX|X|V|I{1,3})\b")
_OLD_GUIDELINES = re.compile(r"\bold\s+guidelines?\b", re.IGNORECASE)
_QUESTION_NUMBER = re.compile(r"^(?:Q\s*\.?\s*\d{1,3}\s*[.):]?|\d{1,3}\s*[.)])\s*", re.IGNORECASE)
_ANSWER_PREFIX = re.compile(r"^A\s*(?:\)|\.(?=\s|[A-Z][a-z]|[A-Z]{2,}))\s*")
_LAST_UPDATED = re.compile(r"^Last\s+Updated\s+on\b", re.IGNORECASE)


@dataclass(frozen=True)
class ProcessStepRecord:
    ordinal: int
    step_label: str | None
    text: str
    link_url: str | None
    link_label: str | None
    locator: str


@dataclass(frozen=True)
class SchemeDocRecord:
    ordinal: int
    scheme_id: str | None
    title: str
    url: str
    size_text: str | None
    category: str
    locator: str


@dataclass(frozen=True)
class FaqRecord:
    category: str
    ordinal: int
    question: str
    answer: str
    answer_links: tuple[tuple[str, str], ...]
    locator: str


@dataclass(frozen=True)
class PageText:
    title: str | None
    paragraphs: list[str]
    links: list[tuple[str, str]]
    last_updated: date | None
    last_updated_raw: str | None


def _soup(html: bytes | str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def resolve_href(href: str | None, page_url: str) -> str | None:
    """Absolute URL for an anchor; bare e-mail addresses become ``mailto:`` links, fragments are ignored."""
    href = (href or "").strip()
    if not href or href.startswith("#") or href.lower().startswith("javascript:"):
        return None
    if "@" in href and "/" not in href and ":" not in href:
        return f"mailto:{href}"
    return urljoin(page_url, href)


def _links(element: Tag, page_url: str) -> tuple[tuple[str, str], ...]:
    found = []
    for anchor in element.find_all("a", href=True):
        url = resolve_href(anchor["href"], page_url)
        if url:
            found.append((clean_ws(anchor.get_text(" ")) or url, url))
    return tuple(found)


def parse_apply_licence(html: bytes | str, page_url: str) -> list[ProcessStepRecord]:
    soup = _soup(html)
    table = next((table for table in soup.find_all("table") if "step" in table.get_text(" ").lower()), None)
    if table is None:
        return []
    steps: list[ProcessStepRecord] = []
    for row in table.find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 2:
            continue
        text = clean_ws(cells[1].get_text(" "))
        if not text:
            continue
        anchor = cells[2].find("a", href=True) if len(cells) > 2 else None
        ordinal = len(steps) + 1
        steps.append(
            ProcessStepRecord(
                ordinal=ordinal,
                step_label=clean_ws(cells[0].get_text(" ")) or None,
                text=text,
                link_url=resolve_href(anchor["href"], page_url) if anchor else None,
                link_label=(clean_ws(anchor.get_text(" ")) or None) if anchor else None,
                locator=f"step-{ordinal}",
            )
        )
    return steps


def parse_certification_process_docs(html: bytes | str, page_url: str) -> list[SchemeDocRecord]:
    soup = _soup(html)
    container = soup.select_one("div.productsCC") or soup.body or soup
    documents: list[SchemeDocRecord] = []
    scheme_id: str | None = None

    def add(anchor: Tag, category: str, context: str) -> None:
        url = resolve_href(anchor.get("href"), page_url)
        label = clean_ws(anchor.get_text(" "))
        title = clean_ws(_SIZE.sub(" ", label)).strip(" –—-")
        if not url or not title:
            return
        size = _SIZE.search(label) or _SIZE.search(context)
        ordinal = len(documents) + 1
        documents.append(
            SchemeDocRecord(
                ordinal=ordinal,
                scheme_id=scheme_id,
                title=title,
                url=url,
                size_text=clean_ws(size.group(1)) if size else None,
                category=category,
                locator=f"doc-{ordinal}",
            )
        )

    for block in container.find_all(["p", "ul"], recursive=False):
        text = clean_ws(block.get_text(" "))
        if block.name == "p":
            scheme = _SCHEME.search(text)
            if _OLD_GUIDELINES.search(text) or not scheme:
                continue
            scheme_id = f"SCHEME_{scheme.group(1)}"
            anchor = block.find("a", href=True)
            if anchor:
                add(anchor, "regulation", text)
        else:
            for item in block.find_all("li"):
                anchor = item.find("a", href=True)
                if anchor:
                    add(anchor, "guideline", clean_ws(item.get_text(" ")))
    return documents


def parse_faq_page(html: bytes | str, category: str, page_url: str) -> list[FaqRecord]:
    soup = _soup(html)
    faqs: list[FaqRecord] = []
    for accordion in soup.find_all("div", class_="accordion"):
        question = _QUESTION_NUMBER.sub("", clean_ws(accordion.get_text(" ")), count=1).strip()
        panel = accordion.find_next_sibling("div")
        if not question or panel is None or "panel" not in (panel.get("class") or []):
            continue
        lines = list(cell_lines(panel))
        if lines:
            lines[0] = _ANSWER_PREFIX.sub("", lines[0], count=1)
        ordinal = len(faqs) + 1
        faqs.append(
            FaqRecord(
                category=category,
                ordinal=ordinal,
                question=question,
                answer="\n".join(line for line in lines if line),
                answer_links=_links(panel, page_url),
                locator=f"faq-{ordinal}",
            )
        )
    return faqs


def parse_page_text(html: bytes | str, page_url: str) -> PageText:
    soup = _soup(html)
    root = soup.select_one("div.who_we_area") or soup.body or soup
    for noise in root.select("div.fbc, script, style, noscript"):
        noise.decompose()

    last_updated_raw = None
    for element in root.find_all(["p", "div", "span"]):
        text = clean_ws(element.get_text(" "))
        if _LAST_UPDATED.match(text) and len(text) < 80:
            last_updated_raw = text
            element.decompose()
            break

    heading = root.find(["h1", "h2"])
    if heading is not None:
        title = clean_ws(heading.get_text(" ")) or None
        heading.decompose()
    else:
        title = clean_ws(soup.title.get_text(" ")) if soup.title else None

    return PageText(
        title=title,
        paragraphs=list(cell_lines(root)),
        links=list(_links(root, page_url)),
        last_updated=parse_date(last_updated_raw),
        last_updated_raw=last_updated_raw,
    )
