from __future__ import annotations

import sqlite3
import threading
import time

from app.db.session import SQLITE_BUSY_TIMEOUT_MS, _configure_sqlite_connection


def test_sqlite_connections_enable_wal_and_bounded_writer_wait(tmp_path) -> None:
    connection = sqlite3.connect(tmp_path / "concurrency.db")
    try:
        _configure_sqlite_connection(connection)

        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        synchronous = connection.execute("PRAGMA synchronous").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
    finally:
        connection.close()

    assert busy_timeout == SQLITE_BUSY_TIMEOUT_MS
    assert journal_mode.lower() == "wal"
    assert synchronous == 1  # NORMAL
    assert foreign_keys == 1


def test_second_writer_waits_for_first_transaction_instead_of_failing(tmp_path) -> None:
    database = tmp_path / "writer-wait.db"
    first = sqlite3.connect(database, check_same_thread=False)
    second = sqlite3.connect(database)
    _configure_sqlite_connection(first)
    _configure_sqlite_connection(second)
    first.execute("CREATE TABLE records (id INTEGER PRIMARY KEY)")
    first.commit()
    first.execute("BEGIN IMMEDIATE")
    first.execute("INSERT INTO records (id) VALUES (1)")

    release = threading.Timer(0.15, first.commit)
    release.start()
    started = time.monotonic()
    try:
        second.execute("INSERT INTO records (id) VALUES (2)")
        second.commit()
    finally:
        release.join(timeout=1)
        first.close()
        second.close()

    assert time.monotonic() - started >= 0.1
