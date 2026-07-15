"""Dataset Bridge — reference dataset ingestion for the Network Anomaly RCA Prototype.

Provides five DatasetReader implementations that map real reference datasets
to the production IngestionPipeline payload schemas documented in
DatasetDescription.md §1-§6.

Policy (DatasetDescription.md §3.3):
    Datasets are reference-only.  The live demo runs entirely from the
    deterministic simulator.  This module is for offline validation and
    demo data seeding ONLY — it is never called from the FastAPI app.

Available readers:
    NslKddReader       — NSL-KDD ARFF text -> PrometheusAdapter
    UnswNb15Reader     — UNSW-NB15 parquet -> PrometheusAdapter
    LoghubHdfsReader   — Loghub HDFS log   -> SyslogAdapter
    SampleTracesReader — Sample CSV traces  -> SyslogAdapter
    GaiaRunReader      — GAIA MicroSS run.zip anomaly injection records -> SyslogAdapter

Orchestration:
    DatasetBridgeRunner — runs all (or selected) readers through IngestionPipeline

CLI::

    python -m app.ingestion.dataset_bridge.runner --help
"""

from .base import (
    BASE_TIMESTAMP,
    DEFAULT_ENTITY_ID,
    ENTITY_IDS,
    HYPOTHESIS_MAP,
    PROVENANCE_SEED,
    SCENARIO_ID,
    SERVICE_TO_ENTITY,
    DatasetReader,
    entity_from_service,
    make_provenance,
)
from .loghub_hdfs import LoghubHdfsReader
from .nsl_kdd import NslKddReader
from .runner import BridgeRunSummary, DatasetBridgeRunner, DatasetStats
from .sample_traces import SampleTracesReader
from .unsw_nb15 import UnswNb15Reader
from .gaia_run import GaiaRunReader

__all__ = [
    # Base
    "BASE_TIMESTAMP",
    "DEFAULT_ENTITY_ID",
    "ENTITY_IDS",
    "HYPOTHESIS_MAP",
    "PROVENANCE_SEED",
    "SCENARIO_ID",
    "SERVICE_TO_ENTITY",
    "DatasetReader",
    "entity_from_service",
    "make_provenance",
    # Readers
    "NslKddReader",
    "UnswNb15Reader",
    "LoghubHdfsReader",
    "SampleTracesReader",
    "GaiaRunReader",
    # Runner
    "DatasetBridgeRunner",
    "BridgeRunSummary",
    "DatasetStats",
]
