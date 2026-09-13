"""SQLite engine factory and database initialisation."""

from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.engine import Engine

from manakmarg.core.config import get_settings
from manakmarg.db import fts, schema


def get_engine(db_path: Path | str | None = None) -> Engine:
    path = Path(db_path) if db_path is not None else get_settings().db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = sa.create_engine(sa.engine.URL.create("sqlite", database=str(path)))

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
        cursor.close()

    return engine


def init_db(engine: Engine) -> None:
    schema.metadata.create_all(engine)
    with engine.begin() as conn:
        fts.create_fts(conn)
