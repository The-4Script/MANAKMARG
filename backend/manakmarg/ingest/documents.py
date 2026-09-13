"""Official documents: registration, PDF text extraction and chunking (plan Task 4.1).

Documents are fetched only from official URLs listed on BIS pages (QCO orders, Product Manuals, laboratory
lists, hallmarking orders). Protected Indian Standard texts are never fetched. A 401/403 response is recorded
as ``access_denied`` and not retried. Extracted text is used for retrieval with page numbers; users are sent to
the official URL for the document itself.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy.engine import Connection

from manakmarg.core.paths import PROJECT_ROOT
from manakmarg.db import schema
from manakmarg.ingest.fetch import FetchResult
from manakmarg.ingest.runs import RunRecorder
from manakmarg.normalize.text import clean_ws

TEXT_PARSED = "parsed"
TEXT_EXTRACTED = "text_extracted"
TEXT_METADATA_ONLY = "metadata_only"
TEXT_ACCESS_DENIED = "access_denied"
TEXT_FETCH_FAILED = "fetch_failed"
TEXT_NO_TEXT_LAYER = "no_text_layer"

MAX_CHUNK_CHARS = 1600


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    page_start: int | None
    page_end: int | None
    text: str
    section_key: str | None = None
    heading: str | None = None


def pdf_pages(source: Path | bytes, *, with_tables: bool = True) -> list[dict]:
    """``{"page", "text", "tables"}`` for every page of a PDF (tables from PyMuPDF's table finder)."""
    import fitz

    if isinstance(source, (bytes, bytearray)):
        document = fitz.open(stream=bytes(source), filetype="pdf")
    else:
        document = fitz.open(source)
    try:
        return [
            {
                "page": index + 1,
                "text": page.get_text(),
                "tables": [table.extract() for table in page.find_tables().tables] if with_tables else [],
            }
            for index, page in enumerate(document)
        ]
    finally:
        document.close()


def chunk_page_texts(page_texts: list[tuple[int, str]], *, max_chars: int = MAX_CHUNK_CHARS) -> list[Chunk]:
    """Consecutive text lines grouped into chunks of at most ``max_chars``, each with its page range."""
    chunks: list[Chunk] = []
    lines: list[str] = []
    size = 0
    first_page = last_page = None
    for page_number, text in page_texts:
        for raw_line in (text or "").splitlines():
            line = clean_ws(raw_line)
            if not line:
                continue
            if lines and size + len(line) + 1 > max_chars:
                chunks.append(Chunk(len(chunks) + 1, first_page, last_page, "\n".join(lines)))
                lines, size, first_page = [], 0, None
            if first_page is None:
                first_page = page_number
            last_page = page_number
            lines.append(line)
            size += len(line) + 1
    if lines:
        chunks.append(Chunk(len(chunks) + 1, first_page, last_page, "\n".join(lines)))
    return chunks


def _relative(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def register_document(
    run: RunRecorder,
    *,
    url: str,
    doc_type: str,
    title: str | None,
    source_page_url: str | None,
    text_status: str,
    fetched: FetchResult | None = None,
    pages: int | None = None,
    http_status: int | None = None,
    doc_date: date | None = None,
    notes: str | None = None,
) -> int:
    values = {
        "source_page_url": source_page_url,
        "title": title,
        "doc_type": doc_type,
        "language": "en",
        "doc_date": doc_date,
        "sha256": fetched.sha256 if fetched else None,
        "pages": pages,
        "http_status": fetched.status if fetched else http_status,
        "text_status": text_status,
        "local_path": _relative(fetched.local_path) if fetched else None,
        "notes": notes,
    }
    return run.upsert(
        "document",
        key={"url": url},
        values=values,
        locator=url,
        retrieved_at=fetched.retrieved_at if fetched else None,
    ).pk


def replace_chunks(conn: Connection, document_id: int, chunks: list[Chunk]) -> int:
    table = schema.document_chunk
    conn.execute(table.delete().where(table.c.document_id == document_id))
    for chunk in chunks:
        conn.execute(
            table.insert().values(
                document_id=document_id,
                ordinal=chunk.ordinal,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                section_key=chunk.section_key,
                heading=chunk.heading,
                text=chunk.text,
            )
        )
    return len(chunks)
