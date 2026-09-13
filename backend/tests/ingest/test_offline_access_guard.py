"""An offline replay must not turn a recorded access refusal (HTTP 403) into a generic fetch failure."""

import sqlalchemy as sa

from manakmarg.db import schema
from manakmarg.db.engine import get_engine, init_db
from manakmarg.ingest import loaders, pipeline, sources
from manakmarg.ingest.fetch import OfflineCacheMiss
from manakmarg.ingest.runs import RunRecorder

MANUAL = "https://www.bis.gov.in/PDF/cart/PM_IS_2062.pdf"


class OfflineFetcher:
    def get(self, url, *, source_id=None, params=None):
        raise OfflineCacheMiss(url)


def _status(engine, url):
    with engine.connect() as conn:
        return conn.execute(sa.select(schema.document.c.text_status, schema.document.c.http_status).where(schema.document.c.url == url)).one()


def test_offline_replay_keeps_a_recorded_access_refusal(tmp_path):
    engine = get_engine(tmp_path / "guard.sqlite3")
    init_db(engine)
    with engine.begin() as conn:
        sources.sync_registry(conn)
    with RunRecorder(engine, "bis_product_manual_documents") as run:
        loaders.record_document_failure(
            run, url=MANUAL, doc_type="product_manual", title="IS 2062 manual", source_page_url=None,
            text_status="access_denied", http_status=403, reason="access blocked (http_403); not retried",
        )
    ctx = pipeline.PipelineContext(engine=engine, fetcher=OfflineFetcher())
    with RunRecorder(engine, "bis_product_manual_documents") as run:
        fetched, outcome = pipeline._fetch_document(run, ctx, MANUAL, doc_type="product_manual", title="IS 2062 manual", source_page_url=None)
        other, other_outcome = pipeline._fetch_document(run, ctx, "https://www.bis.gov.in/never-seen.pdf", doc_type="product_manual", title="x", source_page_url=None)
    assert (fetched, outcome) == (None, "access_denied")
    assert tuple(_status(engine, MANUAL)) == ("access_denied", 403)
    assert (other, other_outcome) == (None, "fetch_failed")
    assert _status(engine, "https://www.bis.gov.in/never-seen.pdf").text_status == "fetch_failed"
    engine.dispose()
