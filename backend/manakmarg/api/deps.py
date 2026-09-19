"""Shared API dependencies: database connections, the clock, and indexes loaded once per process."""

from collections.abc import Iterator
from datetime import date
from functools import lru_cache

from sqlalchemy.engine import Connection, Engine

from manakmarg.core import clock, paths
from manakmarg.core.config import Settings, get_settings
from manakmarg.db.engine import get_engine
from manakmarg.reasoning.intents import Gazetteer
from manakmarg.search.vectors import RUNTIME_CORPORA, VectorIndex, load_vector_indexes


class AppState:
    def __init__(self, settings: Settings, engine: Engine | None = None, index_dir=None):
        self.settings = settings
        self.engine = engine or get_engine(settings.db_path)
        self.index_dir = index_dir or paths.INDEX_DIR
        self._vectors: dict[str, VectorIndex] | None = None
        self._gazetteer: Gazetteer | None = None

    @property
    def vectors(self) -> dict[str, VectorIndex]:
        if self._vectors is None:
            self._vectors = load_vector_indexes(self.index_dir, RUNTIME_CORPORA)
        return self._vectors

    def gazetteer(self, conn: Connection) -> Gazetteer:
        if self._gazetteer is None:
            self._gazetteer = Gazetteer.load(conn)
        return self._gazetteer


_state: AppState | None = None


def configure(state: AppState) -> None:
    global _state
    _state = state


def get_state() -> AppState:
    global _state
    if _state is None:
        _state = AppState(get_settings())
    return _state


def release_state() -> None:
    """Close pooled database connections before the data refresh replaces the database file."""
    if _state is not None:
        _state.engine.dispose()


def reload_state() -> None:
    """After a data refresh: reopen the database and rebuild the cached vector index and gazetteer on next use."""
    if _state is not None:
        _state.engine.dispose()
        _state._vectors = None
        _state._gazetteer = None


def get_conn() -> Iterator[Connection]:
    with get_state().engine.connect() as conn:
        yield conn


def get_today() -> date:
    return clock.today()


@lru_cache(maxsize=1)
def settings() -> Settings:
    return get_state().settings
