"""Ingestion pipeline (plan Task 7.1): fetch official sources politely, parse, load, validate and index.

Steps run in this order; every source is one ingestion run with provenance:

* ``standards``   supplied Excel exports in data/ (read-only inputs)
* ``schemes``     Scheme I, II, IV, X and upcoming-QCO pages → coverage, standard links, orders
* ``pages``       compulsory-certification overview, apply-for-licence steps, certification-process
                  documents, FAQs, hallmarking overview
* ``psg``         Product Specific Guidelines table
* ``documents``   Product Manual and QCO PDFs for the demo product families
* ``labs``        LIMS laboratory directories and the Group-1 / Group-2 PDF lists
* ``lab_scope``   LIMS Indian Standard-wise test facilities for the demo families
* ``hallmarking`` AHC list, suspended/cancelled AHCs, Gazette annex and phase-wise districts
* ``index``       FTS5 indexes
* ``quality``     data-quality report and source manifest

A source that refuses access (HTTP 401/403, robots.txt, CAPTCHA) or cannot be fetched is recorded as a failed
run and reported; it is never retried or worked around.
"""

import logging
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from manakmarg.core import paths
from manakmarg.db import fts, schema
from manakmarg.db.engine import init_db
from manakmarg.ingest import loaders, sources
from manakmarg.ingest.bis_pages import (
    parse_apply_licence,
    parse_certification_process_docs,
    parse_faq_page,
    parse_page_text,
)
from manakmarg.ingest.bis_schemes import (
    parse_scheme_i,
    parse_scheme_ii,
    parse_scheme_iv,
    parse_scheme_x,
    parse_upcoming_qcos,
)
from manakmarg.ingest.compliance_loader import load_scheme_records
from manakmarg.ingest.demo_families import DEMO_FAMILIES
from manakmarg.ingest.documents import (
    TEXT_ACCESS_DENIED,
    TEXT_EXTRACTED,
    TEXT_FETCH_FAILED,
    TEXT_PARSED,
    pdf_pages,
    register_document,
)
from manakmarg.ingest.excel_standards import ingest_standard_exports
from manakmarg.ingest.fetch import AccessBlocked, FetchError, Fetcher, FetchResult, OfflineCacheMiss
from manakmarg.ingest.hallmarking import (
    parse_ahc_events,
    parse_ahc_list,
    parse_gazette_annex,
    parse_phasewise_districts,
    validate_against_gazette,
)
from manakmarg.ingest.lab_lists import parse_group_list
from manakmarg.ingest.lims import parse_lims_directory, parse_lims_scope_search
from manakmarg.ingest.product_manual import ManualPage, parse_product_manual
from manakmarg.ingest.psg import parse_psg
from manakmarg.ingest.quality import run_quality_checks, write_quality_report
from manakmarg.ingest.runs import RunRecorder
from manakmarg.search.vectors import build_vector_indexes

log = logging.getLogger(__name__)

STEPS = ("standards", "schemes", "pages", "psg", "documents", "labs", "lab_scope", "hallmarking", "index", "quality")
MAX_ORDERS_PER_FAMILY = 12

SCHEME_PAGES = (
    ("bis_scheme_i_page", parse_scheme_i, "SCHEME_I"),
    ("bis_scheme_ii_page", parse_scheme_ii, "SCHEME_II"),
    ("bis_scheme_iv_page", parse_scheme_iv, "SCHEME_IV"),
    ("bis_scheme_x_page", parse_scheme_x, "SCHEME_X"),
    ("bis_upcoming_qco_page", parse_upcoming_qcos, None),
)
FAQ_PAGES = (
    ("bis_faq_product_certification", "product_certification"),
    ("bis_faq_laboratory", "laboratory"),
    ("bis_faq_hallmarking_general", "hallmarking_general"),
    ("bis_faq_hallmarking_mandatory", "hallmarking_mandatory"),
)
LIMS_DIRECTORIES = (
    ("lims_bis_labs", "BIS_LAB"),
    ("lims_recognised_labs", "BIS_RECOGNISED"),
    ("lims_empanelled_labs", "GOVT_EMPANELLED"),
)
GROUP_LISTS = (("bis_lab_group1_list", 1), ("bis_lab_group2_list", 2))


@dataclass
class PipelineContext:
    engine: Engine
    fetcher: Fetcher
    data_dir: Path = paths.DATA_DIR
    manifest_dir: Path = paths.MANIFEST_DIR
    docs_dir: Path = paths.DOCS_DIR
    index_dir: Path = paths.INDEX_DIR


def _url(source_id: str) -> str:
    return sources.REGISTRY[source_id].url


def _fetch(run: RunRecorder, fetcher: Fetcher, url: str, *, params: dict | None = None) -> FetchResult:
    result = fetcher.get(url, source_id=run.source_id, params=params)
    run.artifact(result)
    return result


def _guarded(action: Callable[[], dict]) -> dict:
    """Run one source. A blocked or unavailable source is reported; its run has already been marked failed."""
    try:
        return action()
    except AccessBlocked as exc:
        log.warning("access blocked (%s): %s", exc.reason, exc.url)
        return {"status": "access_blocked", "reason": exc.reason, "url": exc.url}
    except (FetchError, OfflineCacheMiss) as exc:
        log.warning("fetch failed: %s", exc)
        return {"status": "fetch_failed", "error": str(exc)}


def _page_run(ctx: PipelineContext, source_id: str, handler: Callable[[RunRecorder, FetchResult, str], dict]) -> dict:
    url = _url(source_id)

    def action() -> dict:
        with RunRecorder(ctx.engine, source_id) as run:
            return handler(run, _fetch(run, ctx.fetcher, url), url)

    return _guarded(action)


def _is_pdf(fetched: FetchResult) -> bool:
    return "pdf" in fetched.content_type.lower() or fetched.content.startswith(b"%PDF")


def demo_family_keys() -> set[str]:
    return {query.family_key for family in DEMO_FAMILIES for query in family.lims_queries}


def lims_doc_numbers() -> list[str]:
    numbers = {query.doc_no for family in DEMO_FAMILIES for query in family.lims_queries}
    return sorted(numbers, key=lambda number: (len(number), number))


# --------------------------------------------------------------------------- steps


def step_standards(ctx: PipelineContext) -> dict:
    return ingest_standard_exports(ctx.engine, ctx.data_dir)


def step_schemes(ctx: PipelineContext) -> dict:
    report = {}
    for source_id, parser, scheme_id in SCHEME_PAGES:
        report[source_id] = _page_run(
            ctx,
            source_id,
            lambda run, fetched, url, parser=parser, scheme_id=scheme_id: load_scheme_records(
                run, parser(fetched.content, url), scheme_id=scheme_id, page_url=url
            ),
        )
    return report


def step_pages(ctx: PipelineContext) -> dict:
    def web_page(run, fetched, url):
        return loaders.load_web_page(run, parse_page_text(fetched.content, url), url=url, fetched=fetched)

    report = {
        "bis_compulsory_overview_page": _page_run(ctx, "bis_compulsory_overview_page", web_page),
        "bis_apply_licence_page": _page_run(
            ctx,
            "bis_apply_licence_page",
            lambda run, fetched, url: loaders.load_process_steps(run, parse_apply_licence(fetched.content, url), page_url=url),
        ),
        "bis_cert_process_page": _page_run(
            ctx,
            "bis_cert_process_page",
            lambda run, fetched, url: loaders.load_scheme_documents(
                run, parse_certification_process_docs(fetched.content, url), page_url=url
            ),
        ),
        "bis_hallmarking_overview_page": _page_run(ctx, "bis_hallmarking_overview_page", web_page),
    }
    for source_id, category in FAQ_PAGES:
        report[source_id] = _page_run(
            ctx,
            source_id,
            lambda run, fetched, url, category=category: loaders.load_faqs(
                run, parse_faq_page(fetched.content, category, url), page_url=url
            ),
        )
    return report


def step_psg(ctx: PipelineContext) -> dict:
    return _page_run(
        ctx, "bis_psg_page", lambda run, fetched, url: loaders.load_guidelines(run, parse_psg(fetched.content, url), page_url=url)
    )


def _demo_manuals(conn) -> list[tuple[str, str]]:
    table = schema.product_guideline
    rows = conn.execute(
        sa.select(table.c.url, table.c.title)
        .where(table.c.is_current.is_(True), table.c.family_key.in_(sorted(demo_family_keys())))
        .order_by(table.c.guideline_id)
    )
    return list(dict((row.url, row.title) for row in rows).items())


def _demo_orders(conn) -> list:
    links, coverage, order_links, orders = (
        schema.coverage_standard,
        schema.scheme_coverage,
        schema.coverage_order,
        schema.regulatory_order,
    )
    rows = conn.execute(
        sa.select(links.c.family_key, orders.c.url, orders.c.title, orders.c.order_date)
        .select_from(
            links.join(coverage, coverage.c.coverage_id == links.c.coverage_id)
            .join(order_links, order_links.c.coverage_id == links.c.coverage_id)
            .join(orders, orders.c.order_id == order_links.c.order_id)
        )
        .where(links.c.family_key.in_(sorted(demo_family_keys())), coverage.c.is_current.is_(True), orders.c.url.is_not(None))
    ).all()
    by_family: dict[str, dict[str, object]] = defaultdict(dict)
    for row in rows:
        by_family[row.family_key].setdefault(row.url, row)
    selected: dict[str, object] = {}
    for family_orders in by_family.values():
        newest_first = sorted(
            family_orders.values(), key=lambda row: (row.order_date is None, -(row.order_date.toordinal() if row.order_date else 0))
        )
        for row in newest_first[:MAX_ORDERS_PER_FAMILY]:
            selected.setdefault(row.url, row)
    return list(selected.values())


def _fetch_document(run: RunRecorder, ctx: PipelineContext, url: str, *, doc_type: str, title: str | None, source_page_url):
    """Fetched PDF, or ``None`` after recording why it could not be read."""
    try:
        fetched = _fetch(run, ctx.fetcher, url)
    except AccessBlocked as exc:
        loaders.record_document_failure(
            run,
            url=url,
            doc_type=doc_type,
            title=title,
            source_page_url=source_page_url,
            text_status=TEXT_ACCESS_DENIED,
            http_status=exc.status,
            reason=f"access blocked ({exc.reason}); not retried",
        )
        return None, "access_denied"
    except (FetchError, OfflineCacheMiss) as exc:
        loaders.record_document_failure(
            run,
            url=url,
            doc_type=doc_type,
            title=title,
            source_page_url=source_page_url,
            text_status=TEXT_FETCH_FAILED,
            http_status=getattr(exc, "status", None),
            reason=str(exc),
        )
        return None, "fetch_failed"
    if not _is_pdf(fetched):
        loaders.record_document_failure(
            run,
            url=url,
            doc_type=doc_type,
            title=title,
            source_page_url=source_page_url,
            text_status="not_pdf",
            http_status=fetched.status,
            reason=f"content type {fetched.content_type or 'unknown'}",
        )
        return None, "not_pdf"
    return fetched, "fetched"


def _read_pdf(fetched: FetchResult, *, with_tables: bool) -> list[dict] | None:
    try:
        return pdf_pages(fetched.content, with_tables=with_tables)
    except Exception:  # PyMuPDF raises several unrelated exception types for damaged files
        log.warning("unreadable PDF: %s", fetched.url, exc_info=True)
        return None


def step_documents(ctx: PipelineContext) -> dict:
    with ctx.engine.connect() as conn:
        manuals = _demo_manuals(conn)
        orders = _demo_orders(conn)
    psg_url = _url("bis_psg_page")
    report = {}

    with RunRecorder(ctx.engine, "bis_product_manual_documents", notes="Product Manuals for demo families") as run:
        stats = Counter()
        for url, title in manuals:
            fetched, outcome = _fetch_document(run, ctx, url, doc_type="product_manual", title=title, source_page_url=psg_url)
            stats[outcome] += 1
            if fetched is None:
                continue
            pages = _read_pdf(fetched, with_tables=True)
            if pages is None:
                loaders.record_document_failure(
                    run, url=url, doc_type="product_manual", title=title, source_page_url=psg_url,
                    text_status="unreadable_pdf", http_status=fetched.status, reason="PDF could not be opened",
                )
                stats["unreadable"] += 1
                continue
            manual = parse_product_manual([ManualPage(page["page"], page["text"], page["tables"]) for page in pages])
            if manual.sections:
                loaders.load_product_manual(
                    run, url=url, title=title, manual=manual, fetched=fetched, page_count=len(pages), source_page_url=psg_url
                )
                stats["parsed"] += 1
            else:
                result = loaders.load_text_document(
                    run,
                    url=url,
                    doc_type="product_manual",
                    title=title,
                    page_texts=[(page["page"], page["text"]) for page in pages],
                    fetched=fetched,
                    source_page_url=psg_url,
                )
                loaders.set_guideline_status(run, url, TEXT_EXTRACTED, result["document_id"])
                stats["text_only"] += 1
        stats["retired"] = run.retire_unseen("document")
        report["bis_product_manual_documents"] = dict(stats)

    with RunRecorder(ctx.engine, "bis_qco_documents", notes="QCO documents for demo families") as run:
        stats = Counter()
        for order in orders:
            fetched, outcome = _fetch_document(
                run, ctx, order.url, doc_type="regulatory_order", title=order.title, source_page_url=None
            )
            stats[outcome] += 1
            if fetched is None:
                continue
            pages = _read_pdf(fetched, with_tables=False)
            if pages is None:
                stats["unreadable"] += 1
                continue
            result = loaders.load_text_document(
                run,
                url=order.url,
                doc_type="regulatory_order",
                title=order.title,
                page_texts=[(page["page"], page["text"]) for page in pages],
                fetched=fetched,
                source_page_url=None,
                doc_date=order.order_date,
            )
            stats["orders_linked"] += loaders.link_order_document(run, order_url=order.url, document_id=result["document_id"])
            stats["chunks"] += result["chunks"]
        stats["retired"] = run.retire_unseen("document")
        report["bis_qco_documents"] = dict(stats)
    return report


def step_labs(ctx: PipelineContext) -> dict:
    report = {}
    for source_id, category in LIMS_DIRECTORIES:
        url = _url(source_id)

        def directory(source_id=source_id, category=category, url=url) -> dict:
            with RunRecorder(ctx.engine, source_id) as run:
                first = parse_lims_directory(_fetch(run, ctx.fetcher, url).content, category, url)
                labs = list(first.labs)
                for page_url in first.page_urls:
                    labs.extend(parse_lims_directory(_fetch(run, ctx.fetcher, page_url).content, category, page_url).labs)
                summary = loaders.load_labs(run, labs, directory_url=url)
                return {**summary, "pages": first.total_pages, "listed_total": first.total_results}

        report[source_id] = _guarded(directory)

    for source_id, group in GROUP_LISTS:

        def group_list(run, fetched, url, source_id=source_id, group=group) -> dict:
            pages = pdf_pages(fetched.content)
            parsed = parse_group_list(pages, group)
            register_document(
                run,
                url=url,
                doc_type="lab_list",
                title=sources.REGISTRY[source_id].name,
                source_page_url=None,
                text_status=TEXT_PARSED,
                fetched=fetched,
                pages=len(pages),
            )
            return {**loaders.load_group_list(run, parsed, document_url=url), "as_of": parsed.as_of_raw}

        report[source_id] = _page_run(ctx, source_id, group_list)
    return report


def step_lab_scope(ctx: PipelineContext, doc_numbers: list[str] | None = None) -> dict:
    search_url = _url("lims_is_scope_search")
    report = {}
    for doc_no in doc_numbers or lims_doc_numbers():

        def search(doc_no=doc_no) -> dict:
            with RunRecorder(ctx.engine, "lims_is_scope_search", notes=f"is_number__doc_no={doc_no}") as run:
                first_fetch = _fetch(run, ctx.fetcher, search_url, params={"is_number__doc_no": doc_no})
                first = parse_lims_scope_search(first_fetch.content, first_fetch.url)
                rows = list(first.rows)
                for page_url in first.page_urls:
                    rows.extend(parse_lims_scope_search(_fetch(run, ctx.fetcher, page_url).content, page_url).rows)
                summary = loaders.load_lab_scope(run, rows, query_doc_no=doc_no, search_url=first_fetch.url)
                return {**summary, "pages": first.total_pages, "listed_total": first.total_results}

        report[doc_no] = _guarded(search)
    return report


def step_hallmarking(ctx: PipelineContext) -> dict:
    report = {
        "manak_ahc_list": _page_run(
            ctx, "manak_ahc_list", lambda run, fetched, url: loaders.load_ahcs(run, parse_ahc_list(fetched.content, url), page_url=url)
        ),
        "manak_ahc_cancelled_suspended": _page_run(
            ctx,
            "manak_ahc_cancelled_suspended",
            lambda run, fetched, url: loaders.load_ahc_events(run, parse_ahc_events(fetched.content, url), page_url=url),
        ),
    }
    annex: list[tuple[str, str]] = []
    gazette_only: list[tuple[str, str]] = []

    def gazette(run, fetched, url) -> dict:
        pages = pdf_pages(fetched.content, with_tables=False)
        annex.extend(parse_gazette_annex([page["text"] for page in pages]))
        result = loaders.load_text_document(
            run,
            url=url,
            doc_type="hallmarking_order",
            title=sources.REGISTRY["bis_hm_gazette_2026_08_03"].name,
            page_texts=[(page["page"], page["text"]) for page in pages],
            fetched=fetched,
            source_page_url=None,
        )
        return {**result, "annex_entries": len(annex)}

    report["bis_hm_gazette_2026_08_03"] = _page_run(ctx, "bis_hm_gazette_2026_08_03", gazette)

    def districts(run, fetched, url) -> dict:
        pages = pdf_pages(fetched.content, with_tables=False)
        records = parse_phasewise_districts([page["text"] for page in pages])
        validation = validate_against_gazette(records, annex) if annex else None
        if validation is not None:
            gazette_only.extend(validation.extra_in_gazette)
        register_document(
            run,
            url=url,
            doc_type="hallmarking_district_list",
            title=sources.REGISTRY["bis_hm_districts_phasewise"].name,
            source_page_url=None,
            text_status=TEXT_PARSED,
            fetched=fetched,
            pages=len(pages),
        )
        summary = loaders.load_districts(run, records, validation, document_url=url)
        if validation is not None:
            summary.update(
                gazette_matched=validation.matched,
                gazette_variants=len(validation.variants),
                missing_in_gazette=list(validation.missing_in_gazette),
                gazette_annex_only=list(validation.extra_in_gazette),
            )
        return summary

    report["bis_hm_districts_phasewise"] = _page_run(ctx, "bis_hm_districts_phasewise", districts)

    if annex and "status" not in report["bis_hm_districts_phasewise"]:
        gazette_source = sources.REGISTRY["bis_hm_gazette_2026_08_03"]

        def annex_only() -> dict:
            with RunRecorder(ctx.engine, gazette_source.source_id, notes="Districts listed only in the Gazette annex") as run:
                return loaders.load_gazette_only_districts(
                    run,
                    gazette_only,
                    document_url=gazette_source.url,
                    note=(
                        f"Listed in the district annex of {gazette_source.name} but not in the BIS phase-wise coverage "
                        "list; verify with BIS before relying on it."
                    ),
                )

        report["gazette_only_districts"] = _guarded(annex_only)
    return report


def step_index(ctx: PipelineContext) -> dict:
    with ctx.engine.begin() as conn:
        fts.rebuild_fts(conn)
        counts = {name: conn.exec_driver_sql(f"SELECT count(*) FROM {name}").scalar() for name in fts.FTS_SPECS}
    with ctx.engine.connect() as conn:
        counts["vectors"] = build_vector_indexes(conn, ctx.index_dir)
    return counts


def step_quality(ctx: PipelineContext) -> dict:
    with ctx.engine.connect() as conn:
        findings = run_quality_checks(conn)
    write_quality_report(findings, ctx.manifest_dir / "data_quality.json", ctx.docs_dir / "DATA_QUALITY.md")
    sources.export_manifest(ctx.manifest_dir / "sources.json")
    counts = Counter(finding.severity for finding in findings if finding.count)
    return {"checks": len(findings), "with_findings": dict(counts)}


STEP_FUNCTIONS: dict[str, Callable[[PipelineContext], dict]] = {
    "standards": step_standards,
    "schemes": step_schemes,
    "pages": step_pages,
    "psg": step_psg,
    "documents": step_documents,
    "labs": step_labs,
    "lab_scope": step_lab_scope,
    "hallmarking": step_hallmarking,
    "index": step_index,
    "quality": step_quality,
}


def run_pipeline(
    engine: Engine,
    fetcher: Fetcher,
    *,
    steps: list[str] | None = None,
    data_dir: Path = paths.DATA_DIR,
    manifest_dir: Path = paths.MANIFEST_DIR,
    docs_dir: Path = paths.DOCS_DIR,
    index_dir: Path = paths.INDEX_DIR,
) -> dict:
    selected = list(steps) if steps else list(STEPS)
    unknown = sorted(set(selected) - set(STEPS))
    if unknown:
        raise ValueError(f"unknown pipeline steps: {', '.join(unknown)}")
    init_db(engine)
    with engine.begin() as conn:
        sources.sync_registry(conn)
    ctx = PipelineContext(engine, fetcher, Path(data_dir), Path(manifest_dir), Path(docs_dir), Path(index_dir))
    report: dict[str, dict] = {}
    for step in STEPS:
        if step not in selected:
            continue
        started = time.monotonic()
        log.info("step %s: started", step)
        report[step] = STEP_FUNCTIONS[step](ctx)
        log.info("step %s: finished in %.1f s", step, time.monotonic() - started)
    return report
