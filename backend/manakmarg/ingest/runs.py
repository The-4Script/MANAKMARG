"""Ingestion-run bookkeeping and provenance-aware upserts.

A ``RunRecorder`` wraps one ingestion run of one source:

* the ``ingestion_run`` row is written in its own transaction, so a failed run is still recorded
  even though its data transaction is rolled back;
* ``upsert`` stamps provenance columns and classifies each record as inserted / updated /
  unchanged using a hash of its key and values;
* ``retire_unseen`` marks rows of this source that the run did not see as no longer current —
  history is kept, nothing is deleted.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from manakmarg import __version__
from manakmarg.core import clock
from manakmarg.db import schema
from manakmarg.ingest.fetch import FetchResult

MAX_RECORDED_ERRORS = 200
_WRITE_COUNTERS = ("inserted", "updated", "unchanged", "retired")


@dataclass(frozen=True)
class UpsertResult:
    outcome: str
    pk: object


def record_hash(values: dict) -> str:
    payload = json.dumps(values, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _match_clauses(table: sa.Table, criteria: dict) -> list:
    return [table.c[name].is_(None) if value is None else table.c[name] == value for name, value in criteria.items()]


def _pk_value(values):
    values = tuple(values)
    return values[0] if len(values) == 1 else values


class RunRecorder:
    def __init__(self, engine: Engine, source_id: str, notes: str = ""):
        self.engine = engine
        self.source_id = source_id
        self.notes = notes
        self.run_id: int | None = None
        self.conn: Connection | None = None
        self._transaction = None
        self.stats = {
            "records_seen": 0,
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
            "retired": 0,
            "rejected": 0,
        }
        self.errors: list[dict] = []

    def __enter__(self) -> "RunRecorder":
        with self.engine.begin() as conn:
            result = conn.execute(
                schema.ingestion_run.insert().values(
                    source_id=self.source_id,
                    started_at=_iso(clock.now_utc()),
                    status="running",
                    notes=self.notes or None,
                    code_version=__version__,
                )
            )
            self.run_id = result.inserted_primary_key[0]
        self.conn = self.engine.connect()
        self._transaction = self.conn.begin()
        return self

    def __exit__(self, exc_type, exc, _traceback) -> bool:
        try:
            if exc_type is None:
                self._transaction.commit()
                status = "success"
            else:
                self._transaction.rollback()
                status = "failed"
                for counter in _WRITE_COUNTERS:
                    self.stats[counter] = 0
                self.errors.append({"locator": None, "reason": f"{exc_type.__name__}: {exc}"})
        finally:
            self.conn.close()

        with self.engine.begin() as conn:
            conn.execute(
                schema.ingestion_run.update()
                .where(schema.ingestion_run.c.run_id == self.run_id)
                .values(
                    completed_at=_iso(clock.now_utc()),
                    status=status,
                    errors_json=json.dumps(self.errors, ensure_ascii=False) if self.errors else None,
                    **self.stats,
                )
            )
        return False

    def upsert(
        self,
        table: str,
        key: dict,
        values: dict,
        locator: str,
        retrieved_at: datetime | None = None,
    ) -> UpsertResult:
        target = schema.metadata.tables[table]
        pk_columns = list(target.primary_key.columns)
        digest = record_hash({**key, **values})
        stamp = _iso(retrieved_at or clock.now_utc())
        self.stats["records_seen"] += 1

        existing = self.conn.execute(
            sa.select(*pk_columns, target.c.record_hash).where(*_match_clauses(target, key))
        ).first()

        if existing is None:
            result = self.conn.execute(
                target.insert().values(
                    **key,
                    **values,
                    source_id=self.source_id,
                    run_id=self.run_id,
                    source_locator=locator,
                    retrieved_at=stamp,
                    record_hash=digest,
                    first_seen_run=self.run_id,
                    last_seen_run=self.run_id,
                    is_current=True,
                )
            )
            self.stats["inserted"] += 1
            return UpsertResult("inserted", _pk_value(result.inserted_primary_key))

        pk_values = tuple(existing)[: len(pk_columns)]
        row_filter = [column == value for column, value in zip(pk_columns, pk_values)]
        if existing.record_hash == digest:
            self.conn.execute(
                target.update().where(*row_filter).values(last_seen_run=self.run_id, is_current=True)
            )
            outcome = "unchanged"
        else:
            self.conn.execute(
                target.update()
                .where(*row_filter)
                .values(
                    **values,
                    source_id=self.source_id,
                    run_id=self.run_id,
                    source_locator=locator,
                    retrieved_at=stamp,
                    record_hash=digest,
                    last_seen_run=self.run_id,
                    is_current=True,
                )
            )
            outcome = "updated"
        self.stats[outcome] += 1
        return UpsertResult(outcome, _pk_value(pk_values))

    def retire_unseen(self, table: str, where: dict | None = None) -> int:
        target = schema.metadata.tables[table]
        result = self.conn.execute(
            target.update()
            .where(
                target.c.source_id == self.source_id,
                target.c.is_current.is_(True),
                sa.or_(target.c.last_seen_run.is_(None), target.c.last_seen_run != self.run_id),
                *_match_clauses(target, where or {}),
            )
            .values(is_current=False)
        )
        self.stats["retired"] += result.rowcount
        return result.rowcount

    def reject(self, locator: str, reason: str) -> None:
        self.stats["rejected"] += 1
        if len(self.errors) < MAX_RECORDED_ERRORS:
            self.errors.append({"locator": locator, "reason": reason})

    def artifact(self, result: FetchResult) -> None:
        self.conn.execute(
            schema.raw_artifact.insert().values(
                source_id=self.source_id,
                run_id=self.run_id,
                uri=result.url,
                local_path=str(result.local_path),
                retrieved_at=_iso(result.retrieved_at),
                http_status=result.status,
                content_type=result.content_type,
                bytes=len(result.content),
                sha256=result.sha256,
                from_cache=result.from_cache,
            )
        )
