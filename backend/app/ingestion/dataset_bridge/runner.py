"""
Dataset Bridge Runner
======================
Orchestrates ingestion of all reference datasets through the production
IngestionPipeline, with per-dataset progress reporting and result aggregation.

Usage (programmatic)::

    from pathlib import Path
    from sqlalchemy.orm import Session
    from app.ingestion.dataset_bridge.runner import DatasetBridgeRunner

    runner = DatasetBridgeRunner(data_root=Path("../data"))
    with Session(engine) as session:
        summary = runner.run_all(session, limits={"nsl_kdd": 500, "unsw_nb15": 300})
        print(summary)

Usage (CLI)::

    python -m app.ingestion.dataset_bridge.runner \
        --data-root ../../data \
        --datasets nsl_kdd unsw_nb15 loghub_hdfs sample_traces \
        --limit 500

The runner:
  1. Iterates records from each DatasetReader.
  2. Strips the internal ``_meta`` key (never passed to the pipeline).
  3. Calls ``IngestionPipeline.ingest()`` with the correct ``source`` key.
  4. Accumulates per-dataset stats: accepted / quarantined / collapsed / idempotent.
  5. Returns a ``BridgeRunSummary`` dataclass.

Policy (DatasetDescription.md §3.3):
  - Datasets are reference-only. Runtime does NOT call this runner.
  - This runner is for offline validation and demo data seeding only.
  - ``_meta`` fields (attack_cat, label, class) are NEVER written to the DB.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.ingestion.pipeline import IngestionPipeline

from .base import DatasetReader
from .loghub_hdfs import LoghubHdfsReader
from .nsl_kdd import NslKddReader
from .sample_traces import SampleTracesReader
from .unsw_nb15 import UnswNb15Reader

# Default data/ root relative to the repo root
_DEFAULT_DATA_ROOT = Path(__file__).resolve().parents[5] / "data"

# Registry of all available dataset readers
_READERS: dict[str, DatasetReader] = {
    "nsl_kdd":       NslKddReader(),
    "unsw_nb15":     UnswNb15Reader(),
    "loghub_hdfs":   LoghubHdfsReader(),
    "sample_traces": SampleTracesReader(),
}


@dataclass
class DatasetStats:
    dataset:    str
    accepted:   int = 0
    quarantined: int = 0
    collapsed:  int = 0
    idempotent: int = 0
    errors:     int = 0

    @property
    def total_attempted(self) -> int:
        return self.accepted + self.quarantined + self.collapsed + self.idempotent + self.errors

    @property
    def success_rate(self) -> float:
        if self.total_attempted == 0:
            return 0.0
        return (self.accepted + self.collapsed + self.idempotent) / self.total_attempted

    def __str__(self) -> str:
        return (
            f"{self.dataset}: accepted={self.accepted} collapsed={self.collapsed} "
            f"idempotent={self.idempotent} quarantined={self.quarantined} "
            f"errors={self.errors} (success={self.success_rate:.1%})"
        )


@dataclass
class BridgeRunSummary:
    datasets: dict[str, DatasetStats] = field(default_factory=dict)

    @property
    def total_accepted(self) -> int:
        return sum(s.accepted for s in self.datasets.values())

    @property
    def total_quarantined(self) -> int:
        return sum(s.quarantined for s in self.datasets.values())

    @property
    def total_events(self) -> int:
        return sum(s.total_attempted for s in self.datasets.values())

    def __str__(self) -> str:
        lines = ["DatasetBridge run summary:"]
        for stat in self.datasets.values():
            lines.append(f"  {stat}")
        lines.append(
            f"  TOTAL: {self.total_events} attempted, "
            f"{self.total_accepted} accepted, "
            f"{self.total_quarantined} quarantined"
        )
        return "\n".join(lines)


def _ingest_record(
    pipeline: IngestionPipeline,
    reader:   DatasetReader,
    raw:      dict[str, Any],
    session:  Session,
) -> str:
    """
    Strip ``_meta`` and call pipeline.ingest(). Returns status string.
    _meta is used only for offline analysis — must never reach the pipeline.
    """
    clean = {k: v for k, v in raw.items() if k != "_meta"}
    result = pipeline.ingest(
        source=reader.source_name,
        raw=clean,
        request_id=str(uuid.uuid4()),
        session=session,
    )
    reason_codes = getattr(result, "reason_codes", None) or []
    if result.status == "accepted" and "IDEMPOTENT_RETRY" in reason_codes:
        return "idempotent"
    return result.status   # "accepted" | "collapsed" | "quarantined"


class DatasetBridgeRunner:
    """
    Orchestrates dataset ingestion through IngestionPipeline.

    Args:
        data_root: Path to the project ``data/`` directory.
                   Defaults to ``../../data`` relative to this file.
        verbose:   Print per-record progress. False by default.
    """

    def __init__(
        self,
        data_root: Path | None = None,
        *,
        verbose: bool = False,
    ) -> None:
        self.data_root = data_root or _DEFAULT_DATA_ROOT
        self.verbose   = verbose
        self._pipeline = IngestionPipeline()

    def run_dataset(
        self,
        dataset_key: str,
        session: Session,
        *,
        limit: int | None = None,
        reader_kwargs: dict[str, Any] | None = None,
    ) -> DatasetStats:
        """
        Ingest one dataset by key.

        Args:
            dataset_key:    One of ``"nsl_kdd"``, ``"unsw_nb15"``,
                            ``"loghub_hdfs"``, ``"sample_traces"``.
            session:        Active SQLAlchemy session (not committed here).
            limit:          Max records to process. None = reader default.
            reader_kwargs:  Extra kwargs forwarded to the reader's ``records()``.
                            E.g. ``{"split": "test"}`` for sample_traces.

        Returns:
            DatasetStats with per-outcome counts.
        """
        if dataset_key not in _READERS:
            raise ValueError(
                f"Unknown dataset key {dataset_key!r}. "
                f"Available: {list(_READERS)}"
            )

        reader = _READERS[dataset_key]
        stats  = DatasetStats(dataset=dataset_key)
        kwargs = reader_kwargs or {}

        try:
            for raw in reader.records(self.data_root, limit=limit, **kwargs):
                try:
                    status = _ingest_record(self._pipeline, reader, raw, session)
                    match status:
                        case "accepted":    stats.accepted    += 1
                        case "collapsed":   stats.collapsed   += 1
                        case "quarantined": stats.quarantined += 1
                        case "idempotent":  stats.idempotent  += 1

                    if self.verbose and stats.total_attempted % 100 == 0:
                        print(f"  [{dataset_key}] {stats}", flush=True)

                except Exception as exc:  # noqa: BLE001
                    stats.errors += 1
                    if self.verbose:
                        print(f"  [{dataset_key}] record error: {exc}", flush=True)

        except FileNotFoundError as exc:
            print(f"  [{dataset_key}] SKIP — {exc}", flush=True)

        if self.verbose or True:   # always print final per-dataset result
            print(f"  {stats}", flush=True)

        return stats

    def run_all(
        self,
        session: Session,
        *,
        datasets: list[str] | None = None,
        limits: dict[str, int] | None = None,
        default_limit: int | None = None,
    ) -> BridgeRunSummary:
        """
        Ingest all (or selected) datasets.

        Args:
            session:       Active SQLAlchemy session.
            datasets:      Subset of dataset keys to run. None = all 4.
            limits:        Per-dataset record limits, e.g. ``{"nsl_kdd": 500}``.
            default_limit: Fallback limit for any dataset not in ``limits``.

        Returns:
            BridgeRunSummary with aggregate stats.
        """
        keys     = datasets or list(_READERS)
        limits   = limits   or {}
        summary  = BridgeRunSummary()

        for key in keys:
            lim   = limits.get(key, default_limit)
            stats = self.run_dataset(key, session, limit=lim)
            summary.datasets[key] = stats

        return summary


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m app.ingestion.dataset_bridge.runner",
        description=(
            "Ingest reference datasets into the IngestionPipeline. "
            "Datasets are reference-only (DatasetDescription.md §3.3); "
            "this command is for offline validation and demo seeding only."
        ),
    )
    p.add_argument(
        "--data-root",
        default=str(_DEFAULT_DATA_ROOT),
        help=f"Path to data/ directory (default: {_DEFAULT_DATA_ROOT})",
    )
    p.add_argument(
        "--datasets",
        nargs="+",
        default=list(_READERS),
        choices=list(_READERS),
        help="Dataset(s) to ingest (default: all four)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Max records per dataset (default: 500; 0 = all rows)",
    )
    p.add_argument(
        "--db-url",
        default="sqlite:///./network_anomaly_rca.db",
        help="SQLAlchemy database URL",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-100-record progress",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    # Import here to avoid circular imports at module level
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _Session
    from app.db.models import Base

    engine = create_engine(args.db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)

    print(f"\nDataset Bridge Runner")
    print(f"  data_root : {args.data_root}")
    print(f"  datasets  : {args.datasets}")
    print(f"  limit     : {args.limit or 'all'}")
    print(f"  db_url    : {args.db_url}")
    print()

    runner = DatasetBridgeRunner(
        data_root=Path(args.data_root),
        verbose=args.verbose,
    )

    with _Session(engine) as session:
        summary = runner.run_all(
            session,
            datasets=args.datasets,
            default_limit=args.limit or None,
        )
        session.commit()

    print()
    print(str(summary))


if __name__ == "__main__":
    main()
