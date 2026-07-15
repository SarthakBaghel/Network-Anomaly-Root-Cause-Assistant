"""
Integration tests for the Dataset Bridge module.

Verifies that all four DatasetReader implementations produce raw dicts that
the production adapters accept without error, and that the full IngestionPipeline
ingests them with zero quarantines.

These tests use the real dataset files from data/ — they are skipped
automatically if the files are not present (CI without the large datasets).

Run:
    pytest tests/integration/test_dataset_bridge.py -v
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Entity, Event, QuarantinedEvent
from app.ingestion.adapters import ADAPTERS
from app.ingestion.dataset_bridge import (
    DatasetBridgeRunner,
    LoghubHdfsReader,
    NslKddReader,
    SampleTracesReader,
    UnswNb15Reader,
)
from app.ingestion.pipeline import IngestionPipeline

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

DATA_ROOT = Path(__file__).resolve().parents[3] / "data"

FROZEN_ENTITIES = [
    ("api-gateway-01",  "gateway",  "gateway"),
    ("payment-api-01",  "api",      "payment"),
    ("checkout-api-01", "api",      "checkout"),
    ("auth-api-01",     "api",      "auth"),
    ("payment-db-01",   "database", "payment"),
]


@pytest.fixture()
def mem_session():
    """In-memory SQLite session with frozen entity seeds."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        for eid, etype, svc in FROZEN_ENTITIES:
            s.add(Entity(id=eid, name=eid, entity_type=etype, service=svc,
                         criticality="tier-1", metadata_json={}))
        s.commit()
        yield s


@pytest.fixture()
def pipeline():
    return IngestionPipeline()


def _skip_if_missing(path: Path) -> pytest.MarkDecorator:
    return pytest.mark.skipif(not path.exists(), reason=f"Dataset not found: {path}")


# ---------------------------------------------------------------------------
# Helper: assert that a batch of records all ingest cleanly
# ---------------------------------------------------------------------------

def _run_batch(pipeline, session, reader, raws, *, dataset_name: str):
    accepted = quar = coll = 0
    for raw in raws:
        clean = {k: v for k, v in raw.items() if k != "_meta"}
        result = pipeline.ingest(
            source=reader.source_name,
            raw=clean,
            request_id=str(uuid.uuid4()),
            session=session,
        )
        codes = getattr(result, "reason_codes", None) or []
        if result.status == "accepted":
            if "IDEMPOTENT_RETRY" not in codes:
                accepted += 1
        elif result.status == "quarantined":
            quar += 1
        elif result.status == "collapsed":
            coll += 1
    assert quar == 0, (
        f"{dataset_name}: {quar} records quarantined (expected 0). "
        "Check entity_id mapping and adapter field names."
    )
    return accepted, coll


# ---------------------------------------------------------------------------
# Step 1: All adapters present in registry
# ---------------------------------------------------------------------------

class TestAdapterRegistry:
    def test_prometheus_registered(self):
        assert "simulator.prometheus" in ADAPTERS

    def test_syslog_registered(self):
        assert "simulator.syslog" in ADAPTERS


# ---------------------------------------------------------------------------
# Step 2: NSL-KDD Reader
# ---------------------------------------------------------------------------

NSL_KDD_PATH = DATA_ROOT / "nsl_kdd/KDDTrain+_20Percent.txt"

@_skip_if_missing(NSL_KDD_PATH)
class TestNslKddReader:

    def test_records_are_yielded(self):
        reader = NslKddReader()
        raws   = list(reader.records(DATA_ROOT, limit=10))
        assert len(raws) == 10

    def test_payload_has_required_prometheus_fields(self):
        reader = NslKddReader()
        raw    = next(reader.records(DATA_ROOT, limit=1))
        p      = raw["payload"]
        assert "sample_id"   in p
        assert "observed_at" in p
        assert "metric"      in p
        assert "value"       in p
        assert "unit"        in p
        assert "entity_id"   in p["labels"]

    def test_meta_stripped_before_pipeline(self):
        reader = NslKddReader()
        raw    = next(reader.records(DATA_ROOT, limit=1))
        assert "_meta" in raw                    # present in yielded record
        clean = {k: v for k, v in raw.items() if k != "_meta"}
        assert "_meta" not in clean              # stripped for pipeline

    def test_entity_id_is_frozen(self):
        reader     = NslKddReader()
        frozen_ids = {e[0] for e in FROZEN_ENTITIES}
        for raw in reader.records(DATA_ROOT, limit=50):
            assert raw["payload"]["labels"]["entity_id"] in frozen_ids

    def test_all_six_signals_produced(self):
        reader  = NslKddReader()
        signals = {raw["payload"]["metric"] for raw in reader.records(DATA_ROOT, limit=60)}
        expected = {
            "raw_ingress_requests_per_second",
            "forwarded_requests_per_second",
            "active_connections_total",
            "connection_utilization",
            "tcp_resets_total",
            "tcp_retransmissions_total",
        }
        assert signals == expected

    def test_source_record_id_format(self):
        reader = NslKddReader()
        raw    = next(reader.records(DATA_ROOT, limit=1))
        assert raw["payload"]["sample_id"].startswith("kdd-train-")

    def test_adapter_accepts_records(self):
        reader  = NslKddReader()
        adapter = ADAPTERS["simulator.prometheus"]
        for raw in reader.records(DATA_ROOT, limit=20):
            clean = {k: v for k, v in raw.items() if k != "_meta"}
            ev    = adapter.adapt(clean)
            assert ev.modality.value == "metric"
            assert ev.severity == 0.0
            assert "SIMULATED" in (ev.quality_flags or [])

    def test_pipeline_accepts_with_zero_quarantines(self, mem_session, pipeline):
        reader = NslKddReader()
        raws   = list(reader.records(DATA_ROOT, limit=30))
        accepted, collapsed = _run_batch(pipeline, mem_session, reader, raws, dataset_name="NSL-KDD")
        assert accepted + collapsed == 30


# ---------------------------------------------------------------------------
# Step 3: UNSW-NB15 Reader
# ---------------------------------------------------------------------------

UNSW_PATH = DATA_ROOT / "unsw_nb15/UNSW_NB15_training-set.parquet"

@_skip_if_missing(UNSW_PATH)
class TestUnswNb15Reader:

    def test_records_are_yielded(self):
        reader = UnswNb15Reader()
        raws   = list(reader.records(DATA_ROOT, limit=10))
        assert len(raws) == 10

    def test_payload_prometheus_schema(self):
        reader = UnswNb15Reader()
        raw    = next(reader.records(DATA_ROOT, limit=1))
        p      = raw["payload"]
        for field in ("sample_id", "observed_at", "metric", "value", "unit"):
            assert field in p, f"Missing field '{field}' in UNSW payload"
        assert "entity_id" in p["labels"]

    def test_four_signals_produced(self):
        reader  = UnswNb15Reader()
        signals = {raw["payload"]["metric"] for raw in reader.records(DATA_ROOT, limit=40)}
        expected = {
            "checkout_p95_latency_ms",
            "active_connections_total",
            "tcp_resets_total",
            "db_connection_utilization",
        }
        assert signals == expected

    def test_meta_has_no_label_leakage_into_payload(self):
        """attack_cat and label must NOT appear in the payload — only in _meta.

        Note: 'labels' (plural) is a legitimate PrometheusAdapter field;
        only the singular 'label' and 'attack_cat' keys must stay in _meta.
        """
        reader = UnswNb15Reader()
        for raw in reader.records(DATA_ROOT, limit=20):
            payload = raw["payload"]
            # Flatten all keys recursively
            def _all_keys(d):
                for k, v in d.items():
                    yield k
                    if isinstance(v, dict):
                        yield from _all_keys(v)
            all_keys = set(_all_keys(payload))
            assert "attack_cat" not in all_keys, f"attack_cat leaked into payload keys: {all_keys}"
            assert "label"      not in all_keys, f"label leaked into payload keys: {all_keys}"
            assert "_meta"      not in all_keys, f"_meta leaked into payload keys: {all_keys}"

    def test_adapter_accepts_records(self):
        reader  = UnswNb15Reader()
        adapter = ADAPTERS["simulator.prometheus"]
        for raw in reader.records(DATA_ROOT, limit=20):
            clean = {k: v for k, v in raw.items() if k != "_meta"}
            ev    = adapter.adapt(clean)
            assert ev.modality.value == "metric"

    def test_pipeline_zero_quarantines(self, mem_session, pipeline):
        reader = UnswNb15Reader()
        raws   = list(reader.records(DATA_ROOT, limit=30))
        accepted, collapsed = _run_batch(pipeline, mem_session, reader, raws, dataset_name="UNSW-NB15")
        assert accepted + collapsed == 30


# ---------------------------------------------------------------------------
# Step 4: Loghub HDFS Reader
# ---------------------------------------------------------------------------

HDFS_PATH = DATA_ROOT / "loghub/HDFS/HDFS.log"

@_skip_if_missing(HDFS_PATH)
class TestLoghubHdfsReader:

    def test_records_are_yielded(self):
        reader = LoghubHdfsReader()
        raws   = list(reader.records(DATA_ROOT, limit=20))
        assert len(raws) > 0

    def test_payload_syslog_schema(self):
        reader = LoghubHdfsReader()
        raw    = next(reader.records(DATA_ROOT, limit=1))
        p      = raw["payload"]
        for field in ("record_id", "observed_at", "host", "code"):
            assert field in p, f"Missing required syslog field '{field}'"

    def test_record_id_format(self):
        reader = LoghubHdfsReader()
        raw    = next(reader.records(DATA_ROOT, limit=1))
        assert raw["payload"]["record_id"].startswith("hdfs-")

    def test_trace_id_uses_block_id(self):
        reader = LoghubHdfsReader()
        raws   = list(reader.records(DATA_ROOT, limit=50))
        blk_traces = [r["payload"]["trace_id"] for r in raws
                      if r["payload"]["trace_id"].startswith("blk_")]
        assert len(blk_traces) > 0, "Expected at least one blk_ trace_id from HDFS.log"

    def test_multiple_event_codes_produced(self):
        reader = LoghubHdfsReader()
        codes  = {r["payload"]["code"] for r in reader.records(DATA_ROOT, limit=200)}
        assert len(codes) >= 2, f"Expected multiple event codes, got: {codes}"

    def test_entity_id_is_frozen(self):
        reader     = LoghubHdfsReader()
        frozen_ids = {e[0] for e in FROZEN_ENTITIES}
        for raw in reader.records(DATA_ROOT, limit=50):
            assert raw["payload"]["host"] in frozen_ids

    def test_adapter_accepts_records(self):
        reader  = LoghubHdfsReader()
        adapter = ADAPTERS["simulator.syslog"]
        for raw in reader.records(DATA_ROOT, limit=20):
            clean = {k: v for k, v in raw.items() if k != "_meta"}
            ev    = adapter.adapt(clean)
            assert ev.modality.value == "log"

    def test_pipeline_zero_quarantines(self, mem_session, pipeline):
        reader = LoghubHdfsReader()
        raws   = list(reader.records(DATA_ROOT, limit=30))
        _run_batch(pipeline, mem_session, reader, raws, dataset_name="Loghub-HDFS")


# ---------------------------------------------------------------------------
# Step 5: Sample Traces Reader
# ---------------------------------------------------------------------------

SAMPLE_CSV_PATH = DATA_ROOT / "sample_dataset/test.csv"

@_skip_if_missing(SAMPLE_CSV_PATH)
class TestSampleTracesReader:

    def test_records_yielded(self):
        reader = SampleTracesReader()
        raws   = list(reader.records(DATA_ROOT, split="test"))
        assert len(raws) > 0

    def test_payload_syslog_schema(self):
        reader = SampleTracesReader()
        raw    = next(reader.records(DATA_ROOT, split="test", limit=1))
        p      = raw["payload"]
        for field in ("record_id", "observed_at", "host", "code"):
            assert field in p

    def test_trace_id_is_128bit_hex(self):
        reader = SampleTracesReader()
        raw    = next(reader.records(DATA_ROOT, split="test", limit=1))
        tid    = raw["payload"]["trace_id"]
        assert tid.startswith("trace-")
        hex_part = tid[len("trace-"):]
        assert len(hex_part) == 32, f"Expected 32-char hex trace_id, got: {tid!r}"

    def test_anomalous_spans_get_timeout_code(self):
        reader   = SampleTracesReader()
        timeouts = [r for r in reader.records(DATA_ROOT, split="test")
                    if r["payload"]["code"] == "UPSTREAM_CONNECTION_TIMEOUT"]
        assert len(timeouts) >= 1, "Expected at least one anomalous span in test.csv"

    def test_meta_uses_latency_range_yml(self):
        reader = SampleTracesReader()
        raws   = list(reader.records(DATA_ROOT, split="test", limit=10))
        for r in raws:
            assert "p99_threshold" in r["_meta"], "_meta should contain p99_threshold"
            assert r["_meta"]["p99_threshold"] > 0

    def test_adapter_accepts_records(self):
        reader  = SampleTracesReader()
        adapter = ADAPTERS["simulator.syslog"]
        for raw in reader.records(DATA_ROOT, split="test", limit=10):
            clean = {k: v for k, v in raw.items() if k != "_meta"}
            ev    = adapter.adapt(clean)
            assert ev.modality.value == "log"

    def test_pipeline_zero_quarantines(self, mem_session, pipeline):
        reader = SampleTracesReader()
        raws   = list(reader.records(DATA_ROOT, split="test"))
        _run_batch(pipeline, mem_session, reader, raws, dataset_name="SampleTraces")


# ---------------------------------------------------------------------------
# Step 6: Full runner integration
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not (NSL_KDD_PATH.exists() and SAMPLE_CSV_PATH.exists()),
    reason="Requires at least NSL-KDD and sample_dataset",
)
class TestDatasetBridgeRunner:

    def test_run_subset(self, mem_session):
        runner  = DatasetBridgeRunner(data_root=DATA_ROOT)
        summary = runner.run_all(
            mem_session,
            datasets=["nsl_kdd", "sample_traces"],
            default_limit=30,
        )
        assert "nsl_kdd"       in summary.datasets
        assert "sample_traces" in summary.datasets
        assert summary.total_quarantined == 0

    def test_run_all_zero_quarantines(self, mem_session):
        runner  = DatasetBridgeRunner(data_root=DATA_ROOT)
        summary = runner.run_all(mem_session, default_limit=20)
        assert summary.total_quarantined == 0, str(summary)

    def test_summary_total_events(self, mem_session):
        runner  = DatasetBridgeRunner(data_root=DATA_ROOT)
        summary = runner.run_all(mem_session, default_limit=10)
        # At minimum sample_dataset and any other available dataset
        assert summary.total_events > 0

    def test_unknown_dataset_raises(self, mem_session):
        runner = DatasetBridgeRunner(data_root=DATA_ROOT)
        with pytest.raises(ValueError, match="Unknown dataset key"):
            runner.run_dataset("nonexistent", mem_session)

    def test_meta_never_reaches_db(self, mem_session):
        """_meta must be stripped — event raw_payload must not contain attack labels.

        Note: 'labels' (plural) is a legitimate PrometheusAdapter field in raw_payload;
        only the singular 'label', 'attack_cat', and '_meta' keys must be absent.
        """
        runner = DatasetBridgeRunner(data_root=DATA_ROOT)
        runner.run_all(mem_session, datasets=["nsl_kdd"], default_limit=20)
        events = mem_session.query(Event).all()

        def _all_keys(d):
            """Recursively yield all dict keys."""
            for k, v in (d or {}).items():
                yield k
                if isinstance(v, dict):
                    yield from _all_keys(v)

        for ev in events:
            all_keys = set(_all_keys(ev.raw_payload))
            assert "_meta"      not in all_keys, f"_meta found in raw_payload keys: {all_keys}"
            assert "attack_cat" not in all_keys, f"attack_cat found in raw_payload keys: {all_keys}"
            assert "label"      not in all_keys, f"label found in raw_payload keys (note: 'labels' is OK): {all_keys}"
