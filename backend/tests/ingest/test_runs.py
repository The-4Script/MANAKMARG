import json

import pytest
import sqlalchemy as sa

from manakmarg.core import clock
from manakmarg.db import schema
from manakmarg.db.engine import get_engine, init_db
from manakmarg.ingest.fetch import FetchResult
from manakmarg.ingest.runs import RunRecorder


@pytest.fixture
def engine(tmp_path):
    eng = get_engine(tmp_path / "runs.sqlite3")
    init_db(eng)
    with eng.begin() as conn:
        conn.execute(schema.source.insert().values(source_id="test_src", name="Test source"))
        conn.execute(schema.source.insert().values(source_id="other_src", name="Other source"))
    yield eng
    eng.dispose()


def _faq(answer: str, ordinal: int = 1) -> dict:
    return {"category": "general", "ordinal": ordinal, "question": "What is a licence?", "answer": answer}


def _faq_row(engine, key: str):
    with engine.connect() as conn:
        return conn.execute(sa.select(schema.faq).where(schema.faq.c.faq_key == key)).mappings().one()


def _run_row(engine, run_id: int):
    with engine.connect() as conn:
        return (
            conn.execute(sa.select(schema.ingestion_run).where(schema.ingestion_run.c.run_id == run_id))
            .mappings()
            .one()
        )


def test_upsert_reports_inserted_unchanged_updated(engine):
    with RunRecorder(engine, "test_src") as first:
        inserted = first.upsert("faq", key={"faq_key": "k1"}, values=_faq("A1"), locator="page#1")
    with RunRecorder(engine, "test_src") as second:
        unchanged = second.upsert("faq", key={"faq_key": "k1"}, values=_faq("A1"), locator="page#1")
    with RunRecorder(engine, "test_src") as third:
        updated = third.upsert("faq", key={"faq_key": "k1"}, values=_faq("A2"), locator="page#2")

    assert (inserted.outcome, unchanged.outcome, updated.outcome) == ("inserted", "unchanged", "updated")
    assert inserted.pk == unchanged.pk == updated.pk

    row = _faq_row(engine, "k1")
    assert row["answer"] == "A2"
    assert row["source_id"] == "test_src"
    assert row["source_locator"] == "page#2"
    assert row["first_seen_run"] == first.run_id
    assert row["last_seen_run"] == third.run_id
    assert row["run_id"] == third.run_id
    assert row["retrieved_at"]
    assert row["record_hash"]
    assert row["is_current"] is True


def test_unchanged_upsert_still_marks_row_as_seen(engine):
    with RunRecorder(engine, "test_src") as first:
        first.upsert("faq", key={"faq_key": "k1"}, values=_faq("A1"), locator="page#1")
    with RunRecorder(engine, "test_src") as second:
        second.upsert("faq", key={"faq_key": "k1"}, values=_faq("A1"), locator="page#1")
    row = _faq_row(engine, "k1")
    assert row["last_seen_run"] == second.run_id
    assert row["run_id"] == first.run_id


def test_successful_run_records_counts(engine):
    with RunRecorder(engine, "test_src", notes="unit test") as run:
        run.upsert("faq", key={"faq_key": "k1"}, values=_faq("A1"), locator="page#1")
        run.upsert("faq", key={"faq_key": "k2"}, values=_faq("B1", 2), locator="page#2")
        run.reject("page#3", "question without answer")

    row = _run_row(engine, run.run_id)
    assert row["status"] == "success"
    assert row["records_seen"] == 2
    assert row["inserted"] == 2
    assert row["rejected"] == 1
    assert row["completed_at"]
    assert row["notes"] == "unit test"
    assert "question without answer" in row["errors_json"]


def test_failed_run_rolls_back_data_and_is_marked_failed(engine):
    with pytest.raises(RuntimeError):
        with RunRecorder(engine, "test_src") as run:
            run.upsert("faq", key={"faq_key": "k1"}, values=_faq("A1"), locator="page#1")
            raise RuntimeError("parser exploded")

    with engine.connect() as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(schema.faq)).scalar() == 0
    row = _run_row(engine, run.run_id)
    assert row["status"] == "failed"
    assert "parser exploded" in json.loads(row["errors_json"])[-1]["reason"]


def test_retire_unseen_marks_rows_missing_from_this_run(engine):
    with RunRecorder(engine, "test_src") as first:
        first.upsert("faq", key={"faq_key": "k1"}, values=_faq("A1"), locator="page#1")
        first.upsert("faq", key={"faq_key": "k2"}, values=_faq("B1", 2), locator="page#2")
    with RunRecorder(engine, "test_src") as second:
        second.upsert("faq", key={"faq_key": "k1"}, values=_faq("A1"), locator="page#1")
        retired = second.retire_unseen("faq")

    assert retired == 1
    assert _faq_row(engine, "k1")["is_current"] is True
    assert _faq_row(engine, "k2")["is_current"] is False
    assert _run_row(engine, second.run_id)["retired"] == 1


def test_retire_unseen_only_touches_the_recorders_source(engine):
    with RunRecorder(engine, "other_src") as other:
        other.upsert("faq", key={"faq_key": "other"}, values=_faq("X"), locator="elsewhere")
    with RunRecorder(engine, "test_src") as run:
        run.upsert("faq", key={"faq_key": "k1"}, values=_faq("A1"), locator="page#1")
        run.retire_unseen("faq")
    assert _faq_row(engine, "other")["is_current"] is True


def test_retire_unseen_respects_where_filter(engine):
    with RunRecorder(engine, "test_src") as first:
        first.upsert("faq", key={"faq_key": "a"}, values={**_faq("A"), "category": "labs"}, locator="1")
        first.upsert("faq", key={"faq_key": "b"}, values={**_faq("B"), "category": "hallmarking"}, locator="2")
    with RunRecorder(engine, "test_src") as second:
        second.retire_unseen("faq", where={"category": "labs"})
    assert _faq_row(engine, "a")["is_current"] is False
    assert _faq_row(engine, "b")["is_current"] is True


def test_artifact_is_recorded(engine, tmp_path):
    result = FetchResult(
        url="https://www.bis.gov.in/page/",
        final_url="https://www.bis.gov.in/page/",
        status=200,
        content=b"<html></html>",
        content_type="text/html",
        sha256="a" * 64,
        local_path=tmp_path / "page.html",
        retrieved_at=clock.now_utc(),
        from_cache=True,
    )
    with RunRecorder(engine, "test_src") as run:
        run.artifact(result)
    with engine.connect() as conn:
        row = conn.execute(sa.select(schema.raw_artifact)).mappings().one()
    assert row["run_id"] == run.run_id
    assert row["uri"] == "https://www.bis.gov.in/page/"
    assert row["sha256"] == "a" * 64
    assert row["bytes"] == len(b"<html></html>")
    assert row["from_cache"] is True
