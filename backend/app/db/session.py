from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


SQLITE_BUSY_TIMEOUT_SECONDS = max(
    75.0,
    settings.ollama_timeout_seconds * 2 + 5.0,
)
SQLITE_BUSY_TIMEOUT_MS = int(SQLITE_BUSY_TIMEOUT_SECONDS * 1000)


engine = create_engine(
    settings.database_url,
    future=True,
    connect_args={
        "check_same_thread": False,
        "timeout": SQLITE_BUSY_TIMEOUT_SECONDS,
    },
    pool_pre_ping=True,
)


def _configure_sqlite_connection(dbapi_connection) -> None:
    """Configure every SQLite connection for concurrent local API requests."""

    cursor = dbapi_connection.cursor()
    try:
        # WAL lets dashboard reads continue while a scenario/reset transaction
        # writes. SQLite still permits only one writer, so busy_timeout makes a
        # second bounded mutation wait instead of failing after the 5s default.
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


@event.listens_for(engine, "connect")
def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    _configure_sqlite_connection(dbapi_connection)


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency with one transaction per request."""
    with session_scope() as session:
        yield session
