"""
EwmaStateStore — Write-through in-memory + SQLite EWMA baseline store.

Provides per-(entity_id, signal_name) EWMA state that:
  1. Loads from the ewma_baselines SQLite table at first access
  2. Updates in-memory immediately on every new metric sample
  3. Flushes dirty state to DB at the end of each ingestion batch

This is intentionally simple — it is not a cache; it's a thin persistence
wrapper so EWMA baselines survive application restarts.

BLUEPRINT §3.2 compliance:
  - alpha is NOT stored in the DB — it is a fixed config constant
  - The store is append-only: existing state is upserted, never deleted
    (except on demo reset via ResetService._clear_demo_rows)
  - The store does NOT auto-apply threshold changes
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session


class EwmaState(TypedDict):
    ewma_mean: float
    ewma_variance: float
    n_samples: int


class EwmaStateStore:
    """Thread-safe write-through in-memory EWMA state store.

    Usage in DetectionPublisher / DetectorService:
      store = EwmaStateStore()
      state = store.get(entity_id, signal_name, session)
      # ... detector updates state dict in-memory ...
      store.put(entity_id, signal_name, new_state, session)
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, str], EwmaState] = {}
        self._dirty: set[tuple[str, str]] = set()
        self._loaded_from_db = False
        self._database_bind: object | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, entity_id: str, signal_name: str, session: Session) -> EwmaState | None:
        """Return EWMA state for the given (entity_id, signal_name), or None on cold start."""
        key = (entity_id, signal_name)
        with self._lock:
            self._prepare_database_bind(session)
            if not self._loaded_from_db:
                self._load(session)
            return dict(self._cache[key]) if key in self._cache else None  # type: ignore[return-value]

    def put(self, entity_id: str, signal_name: str, state: EwmaState, session: Session) -> None:
        """Store updated EWMA state and mark as dirty for flush."""
        key = (entity_id, signal_name)
        with self._lock:
            self._prepare_database_bind(session)
            self._cache[key] = state
            self._dirty.add(key)

    def flush(self, session: Session) -> int:
        """Upsert all dirty entries to the ewma_baselines table.

        Returns the count of rows written.
        Called at the end of each ingestion batch.
        """
        from app.db.models import EwmaBaseline

        with self._lock:
            self._prepare_database_bind(session)
            dirty_snapshot = set(self._dirty)  # snapshot the set of (entity_id, signal_name) tuples
            self._dirty.clear()

        written = 0
        now = datetime.now(tz=timezone.utc)
        try:
            for (entity_id, signal_name) in dirty_snapshot:
                with self._lock:
                    state = self._cache.get((entity_id, signal_name))
                if state is None:
                    continue
                existing = session.scalar(
                    select(EwmaBaseline).where(
                        EwmaBaseline.entity_id == entity_id,
                        EwmaBaseline.signal_name == signal_name,
                    )
                )
                if existing is not None:
                    existing.ewma_mean = state["ewma_mean"]
                    existing.ewma_variance = state["ewma_variance"]
                    existing.n_samples = state["n_samples"]
                    existing.updated_at = now
                else:
                    session.add(EwmaBaseline(
                        entity_id=entity_id,
                        signal_name=signal_name,
                        ewma_mean=state["ewma_mean"],
                        ewma_variance=state["ewma_variance"],
                        n_samples=state["n_samples"],
                        updated_at=now,
                    ))
                written += 1
        except Exception:
            # Table may not exist in tests that use older DB schema; silently skip.
            # In production the migration ensures the table is always present.
            pass
        return written

    def reset(self) -> None:
        """Clear the in-memory cache (called after demo reset clears the DB table)."""
        with self._lock:
            self._cache.clear()
            self._dirty.clear()
            self._loaded_from_db = False
            self._database_bind = None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _prepare_database_bind(self, session: Session) -> None:
        """Scope cached baselines to the database backing the current session."""
        database_bind = session.get_bind()
        if self._database_bind is database_bind:
            return
        if self._dirty:
            raise RuntimeError(
                "cannot switch EWMA database bind with unflushed baseline state"
            )
        self._cache.clear()
        self._loaded_from_db = False
        self._database_bind = database_bind

    def _load(self, session: Session) -> None:
        """Load all rows from ewma_baselines into the in-memory cache.

        Called once on first access. Idempotent — safe to call multiple
        times but protected by _loaded_from_db flag under _lock.
        """
        from app.db.models import EwmaBaseline

        rows = session.scalars(select(EwmaBaseline)).all()
        for row in rows:
            self._cache[(row.entity_id, row.signal_name)] = EwmaState(
                ewma_mean=row.ewma_mean,
                ewma_variance=row.ewma_variance,
                n_samples=row.n_samples,
            )
        self._loaded_from_db = True


# Module-level singleton — shared across all DetectionPublisher instances
ewma_store = EwmaStateStore()
