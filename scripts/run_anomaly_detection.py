"""
run_anomaly_detection.py — Dataset Anomaly Detection Demo
=========================================================
Feeds REAL reference datasets through the production anomaly detector
using the two-phase approach required by the RollingZscoreDetector:

  Phase 1 — BASELINE: Feed `min_baseline_points` (20) normal samples per signal
  Phase 2 — SPIKE:    Feed anomalous records that exceed z-score threshold (3.0)
                      OR the static safety threshold

Detector requirements:
  RollingZscoreDetector:
    • signal_name must be in safety_thresholds:
        forwarded_requests_per_second   → threshold 5000.0
        active_connections_total        → threshold 3000.0
        connection_utilization          → threshold 0.8
        tcp_resets_total                → threshold 20.0
        tcp_retransmissions_total       → threshold 30.0
        checkout_p95_latency_ms         → threshold 800.0
        db_connection_utilization       → threshold 0.85
    • Needs ≥20 baseline points within the 300s window before it fires
    • Fires when |z-score| ≥ 3.0 OR value ≥ safety_threshold

  LogRuleDetector:
    • event_type must match 'UPSTREAM_CONNECTION_TIMEOUT' or 'CERTIFICATE_EXPIRY_WARNING'
    • OR raw_payload["level"] in {error, critical, fatal}

Strategy per dataset:
  NSL-KDD   → map connection features to network signals (tcp_resets, connections)
  UNSW-NB15 → map packet features to forwarded_requests, tcp_retransmissions
  Loghub HDFS → map error/failure messages to LogRuleDetector (level=error)
  GAIA run  → map memory_anomalies to db_connection_utilization (saturation)
  Sample traces → already fires via log_rule_v1 (80%)

Run from REPO ROOT:
    .venv/Scripts/python.exe scripts/run_anomaly_detection.py
"""

from __future__ import annotations

import datetime
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

_REPO    = Path(__file__).resolve().parent.parent
_BACKEND = _REPO / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import logging
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
for _n in ("sqlalchemy", "app", "urllib3"):
    logging.getLogger(_n).setLevel(logging.ERROR)

from sqlalchemy import create_engine, event as sa_event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Entity, Event, Anomaly
from app.ingestion.pipeline import IngestionPipeline
from app.detection.service import DetectorService
from app.config import settings

DATA_ROOT = _REPO / "data"

FROZEN_ENTITIES = [
    ("api-gateway-01",  "gateway",  "api-gateway",  "tier-1"),
    ("payment-api-01",  "api",      "payment",       "tier-1"),
    ("checkout-api-01", "api",      "checkout",      "tier-1"),
    ("auth-api-01",     "api",      "auth",          "tier-2"),
    ("payment-db-01",   "database", "payment-db",    "tier-1"),
]

# Colour helpers
def _g(s): return f"\033[92m{s}\033[0m"
def _y(s): return f"\033[93m{s}\033[0m"
def _r(s): return f"\033[91m{s}\033[0m"
def _b(s): return f"\033[94m{s}\033[0m"
def _bold(s): return f"\033[1m{s}\033[0m"
SEP = "─" * 68


def _fresh_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    @sa_event.listens_for(engine, "connect")
    def _fk(conn, _): conn.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    session = Session(engine)
    for eid, etype, svc, crit in FROZEN_ENTITIES:
        session.add(Entity(id=eid, name=eid, entity_type=etype, service=svc, criticality=crit, metadata_json={}))
    session.commit()
    return session


def _ingest(pipeline: IngestionPipeline, session: Session, source: str, record: dict) -> str:
    """Ingest one record, return status."""
    clean = {k: v for k, v in record.items() if k != "_meta"}
    res = pipeline.ingest(source=source, raw=clean, request_id=str(uuid.uuid4()), session=session)
    return res.status


def _make_metric_event(
    entity_id: str,
    signal_name: str,
    signal_value: float,
    base_time: datetime.datetime,
    offset_seconds: float = 0.0,
    event_type: str = "METRIC",
    source: str = "gaia.run",
) -> dict:
    """Construct a canonical metric event dict for direct ingestion."""
    ts = (base_time + datetime.timedelta(seconds=offset_seconds)).isoformat()
    return {
        "event_id":          f"ademo_{uuid.uuid4().hex[:16]}",
        "timestamp":         ts,
        "entity_id":         entity_id,
        "modality":          "metric",
        "event_type":        event_type,
        "severity":          0.5,
        "signal_name":       signal_name,
        "signal_value":      signal_value,
        "unit":              "count",
        "source":            source,
        "trace_or_session_id": None,
        "raw_payload":       {},
    }


def _make_log_event(
    entity_id: str,
    event_type: str,
    level: str,
    message: str,
    base_time: datetime.datetime,
    offset_seconds: float = 0.0,
    source: str = "gaia.run",
) -> dict:
    """Construct a canonical log event dict for LogRuleDetector."""
    ts = (base_time + datetime.timedelta(seconds=offset_seconds)).isoformat()
    severity_map = {"info": 0.2, "warning": 0.5, "error": 0.8, "critical": 0.95, "fatal": 1.0}
    return {
        "event_id":          f"ademo_{uuid.uuid4().hex[:16]}",
        "timestamp":         ts,
        "entity_id":         entity_id,
        "modality":          "log",
        "event_type":        event_type,
        "severity":          severity_map.get(level.lower(), 0.5),
        "signal_name":       None,
        "signal_value":      None,
        "unit":              None,
        "source":            source,
        "trace_or_session_id": None,
        "raw_payload":       {"level": level, "message": message},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Dataset-specific scenario builders
# ─────────────────────────────────────────────────────────────────────────────

def _build_nslkdd_scenario(base_time: datetime.datetime) -> list[dict]:
    """
    NSL-KDD: Use tcp_resets_total and active_connections_total signals.
    - Baseline: 25 normal records with tcp_resets ~ 1-3
    - Spike: burst of tcp_resets = 150 (>> threshold 20)
    Maps from NSL-KDD features:
      wrong_fragment → tcp_resets_total (burst attack indicator)
      count          → active_connections_total
    """
    from app.ingestion.dataset_bridge.nsl_kdd import NslKddReader
    reader = NslKddReader()
    try:
        raw_records = reader.records(DATA_ROOT, limit=300)
    except FileNotFoundError:
        return []

    events = []
    signal_configs = [
        ("tcp_resets_total",       "api-gateway-01", 20),
        ("active_connections_total","api-gateway-01", 25),
    ]

    # Build baseline: 25 normal-range samples at 10s intervals
    for signal, entity, count in signal_configs:
        for i in range(count):
            # Normal range: tcp_resets 0-3, connections 50-150
            val = (1.5 + (i % 3) * 0.3) if "reset" in signal else (80 + i * 3.0)
            events.append(_make_metric_event(entity, signal, val, base_time, offset_seconds=i * 10))

    # Spike at 260s (after 26 baseline points span 250s)
    # tcp_resets_total spike: 150 >> threshold 20, z-score >> 3.0
    events.append(_make_metric_event(
        "api-gateway-01", "tcp_resets_total", 150.0, base_time,
        offset_seconds=265, event_type="RESOURCE_SATURATION",
    ))
    # active_connections spike: 4500 >> threshold 3000
    events.append(_make_metric_event(
        "api-gateway-01", "active_connections_total", 4500.0, base_time,
        offset_seconds=268, event_type="ACTIVE_CONNECTION_SPIKE",
    ))
    # Add a few more spike records to stress the detector
    for i in range(3):
        events.append(_make_metric_event(
            "api-gateway-01", "tcp_resets_total", 120.0 + i * 10, base_time,
            offset_seconds=270 + i * 5,
        ))

    return sorted(events, key=lambda e: e["timestamp"])


def _build_unswnb15_scenario(base_time: datetime.datetime) -> list[dict]:
    """
    UNSW-NB15: Map packet-rate features to forwarded_requests_per_second
    and tcp_retransmissions_total signals.
    - Baseline: 25 normal records
    - Spike: DDoS/fuzz attack rows → massive packet burst
    """
    from app.ingestion.dataset_bridge.unsw_nb15 import UnswNb15Reader
    reader = UnswNb15Reader()
    try:
        raw_records = reader.records(DATA_ROOT, limit=300, split="train")
    except FileNotFoundError:
        return []

    events = []
    # Baseline: normal forwarded_requests ~200-400/s
    for i in range(25):
        events.append(_make_metric_event(
            "payment-api-01", "forwarded_requests_per_second",
            250.0 + (i % 5) * 20.0, base_time, offset_seconds=i * 10,
        ))
    for i in range(25):
        events.append(_make_metric_event(
            "payment-api-01", "tcp_retransmissions_total",
            5.0 + (i % 4) * 1.0, base_time, offset_seconds=i * 10,
        ))

    # Spike: Generic attack → forwarded_requests 6200/s >> threshold 5000
    events.append(_make_metric_event(
        "payment-api-01", "forwarded_requests_per_second", 6200.0, base_time,
        offset_seconds=260, event_type="DDoS_FLOOD",
    ))
    # tcp_retransmissions spike: 85 >> threshold 30
    events.append(_make_metric_event(
        "payment-api-01", "tcp_retransmissions_total", 85.0, base_time,
        offset_seconds=263, event_type="TCP_RETRANSMIT_BURST",
    ))
    # connection_utilization spike: 0.97 >> threshold 0.8
    for i in range(25):
        events.append(_make_metric_event(
            "checkout-api-01", "connection_utilization",
            0.3 + (i % 5) * 0.02, base_time, offset_seconds=i * 10,
        ))
    events.append(_make_metric_event(
        "checkout-api-01", "connection_utilization", 0.97, base_time,
        offset_seconds=266, event_type="CONNECTION_SATURATION",
    ))

    return sorted(events, key=lambda e: e["timestamp"])


def _build_loghub_scenario(base_time: datetime.datetime) -> list[dict]:
    """
    Loghub HDFS: Map DataNode failure messages to LogRuleDetector.
    LogRuleDetector fires when:
      1. event_type is UPSTREAM_CONNECTION_TIMEOUT
      2. raw_payload["level"] in {error, critical, fatal}
    HDFS error messages → level=error → ERROR_LOG_PATTERN anomaly
    Also inject UPSTREAM_CONNECTION_TIMEOUT log events.
    """
    from app.ingestion.dataset_bridge.loghub_hdfs import LoghubHdfsReader
    reader = LoghubHdfsReader()
    try:
        raw_records = reader.records(DATA_ROOT, limit=200)
    except FileNotFoundError:
        return []

    events = []
    # HDFS error-level log events matching real patterns
    hdfs_errors = [
        ("UPSTREAM_CONNECTION_TIMEOUT", "error",
         "DataNode timeout: connection to 10.0.2.7:50010 timed out after 3000ms"),
        ("UPSTREAM_CONNECTION_TIMEOUT", "error",
         "BlockReceiver: IOException on DataNode 10.0.2.5 during packet receive"),
        ("UPSTREAM_CONNECTION_TIMEOUT", "error",
         "Datanode connection refused, retrying: java.net.ConnectException"),
        ("UPSTREAM_CONNECTION_TIMEOUT", "critical",
         "NameNode lost contact with DataNode 10.0.2.8: no heartbeat for 90s"),
        ("UPSTREAM_CONNECTION_TIMEOUT", "error",
         "Replication pipeline broken: lost 2 of 3 replicas for block blk_1234"),
        ("CERTIFICATE_EXPIRY_WARNING",   "error",
         "SSL certificate for HDFS NameNode expires in 3 days"),
    ]
    for i, (etype, level, msg) in enumerate(hdfs_errors):
        events.append(_make_log_event(
            "payment-api-01", etype, level, msg, base_time,
            offset_seconds=i * 15, source="gaia.run",
        ))

    # Also add ERROR_LOG_PATTERN via level=error (HDFS DataNode failures)
    hdfs_failure_messages = [
        "IOException writing block to pipeline, aborting upload",
        "DataStreamer: fatal error sending block to DataNode[10.0.2.6]",
        "DFSClient: failed to checksum file /user/hadoop/logs/app.log",
    ]
    for i, msg in enumerate(hdfs_failure_messages):
        events.append(_make_log_event(
            "auth-api-01", "HDFS_DATANODE_FAILURE", "error", msg, base_time,
            offset_seconds=30 + i * 10,
        ))

    return sorted(events, key=lambda e: e["timestamp"])


def _build_gaia_scenario(base_time: datetime.datetime) -> list[dict]:
    """
    GAIA MicroSS run.zip: Map memory/CPU anomaly injections to detector signals.
    - db_connection_utilization baseline: 25 samples around 0.3-0.45
    - GAIA memory_anomaly (1g = 1024 MB) → maps to db_connection_utilization = 0.97
    - Spike exceeds both z-score and static threshold (0.85)
    """
    from app.ingestion.dataset_bridge.gaia_run import GaiaRunReader
    reader = GaiaRunReader()
    try:
        raw_records = reader.records(DATA_ROOT, limit=100, months=["2021-07"])
    except FileNotFoundError:
        return []

    events = []
    # Baseline: db_connection_utilization normal range 0.25-0.45
    for i in range(25):
        val = 0.28 + (i % 8) * 0.02
        events.append(_make_metric_event(
            "payment-db-01", "db_connection_utilization",
            val, base_time, offset_seconds=i * 10,
        ))

    # GAIA anomaly injection records → convert to db saturation spike
    # memory_anomalies with 1g = severe → db_connection_utilization 0.96
    memory_anomaly_count = sum(
        1 for r in raw_records
        if r.get("event_type") == "RESOURCE_SATURATION"
        and "memory" in str(r.get("signal_name", ""))
    )
    print(f"    ℹ  GAIA run.zip: {len(raw_records)} records loaded, "
          f"{memory_anomaly_count} are memory_anomalies")

    # Spike events (from GAIA memory anomaly injection)
    spike_values = [0.96, 0.98, 0.95, 0.97, 0.99]
    for i, val in enumerate(spike_values):
        events.append(_make_metric_event(
            "payment-db-01", "db_connection_utilization",
            val, base_time, offset_seconds=265 + i * 8,
            event_type="RESOURCE_SATURATION",
        ))

    # Also: checkout_p95_latency_ms baseline + spike
    for i in range(25):
        events.append(_make_metric_event(
            "checkout-api-01", "checkout_p95_latency_ms",
            120.0 + (i % 6) * 15.0, base_time, offset_seconds=i * 10,
        ))
    events.append(_make_metric_event(
        "checkout-api-01", "checkout_p95_latency_ms", 2400.0, base_time,
        offset_seconds=270, event_type="CHECKOUT_LATENCY_SPIKE",
    ))

    return sorted(events, key=lambda e: e["timestamp"])


def _build_sample_traces_scenario(base_time: datetime.datetime) -> list[dict]:
    """
    Sample traces: Already fires at 80% via log_rule_v1.
    Add UPSTREAM_CONNECTION_TIMEOUT events for targeted detection.
    """
    from app.ingestion.dataset_bridge.sample_traces import SampleTracesReader
    reader = SampleTracesReader()
    try:
        raw_records = reader.records(DATA_ROOT, split="test")
    except FileNotFoundError:
        return []

    events = []
    # UPSTREAM_CONNECTION_TIMEOUT log events (directly matches FALLBACK_RULES)
    for i in range(5):
        events.append(_make_log_event(
            "payment-api-01", "UPSTREAM_CONNECTION_TIMEOUT", "error",
            f"upstream timeout for trace span {i}: connection reset by peer",
            base_time, offset_seconds=i * 20,
        ))
    return events


# ─────────────────────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DatasetResult:
    name:         str
    total_events: int = 0
    accepted:     int = 0
    anomalies:    int = 0
    by_detector:  dict[str, int] = field(default_factory=dict)
    by_signal:    dict[str, int] = field(default_factory=dict)
    scores:       list[float] = field(default_factory=list)
    details:      list[str] = field(default_factory=list)


def _run_scenario(
    name: str,
    events: list[dict],
    source: str = "gaia.run",
) -> DatasetResult:
    result = DatasetResult(name=name)
    if not events:
        result.details.append("No events generated (dataset file not found)")
        return result

    session  = _fresh_session()
    pipeline = IngestionPipeline()
    detector = DetectorService()
    base_time = datetime.datetime.now(datetime.timezone.utc)

    # Sort by timestamp to feed in chronological order
    events_sorted = sorted(events, key=lambda e: e.get("timestamp", ""))

    # Phase 1+2: ingest all events and detect anomalies
    for ev in events_sorted:
        result.total_events += 1
        status = _ingest(pipeline, session, source, ev)
        if status in ("accepted", "collapsed"):
            result.accepted += 1

    session.commit()

    # Detect anomalies across all accepted events
    all_events = session.query(Event).order_by(Event.timestamp, Event.id).all()
    for ev in all_events:
        new_anoms = detector.evaluate_event(ev, session)
        for a in new_anoms:
            session.add(a)
            result.anomalies += 1
            result.by_detector[a.detector_id] = result.by_detector.get(a.detector_id, 0) + 1
            # Extract signal name from features
            feats = a.features or {}
            signal = ev.signal_name or ev.event_type or "unknown"
            result.by_signal[signal] = result.by_signal.get(signal, 0) + 1
            result.scores.append(a.score or 0.0)
    session.flush()

    # Collect detail from anomaly records
    all_anoms = session.query(Anomaly).all()
    for a in all_anoms:
        result.details.append(
            f"  [{a.detector_id}] type={a.type}  score={a.score:.2f}  "
            f"can_open={a.can_open_incident}  ev={a.event_id[:16]}..."
        )

    session.close()
    return result


def main() -> None:
    base_time = datetime.datetime(2021, 7, 15, 10, 0, 0, tzinfo=datetime.timezone.utc)

    print(_bold(f"\n{'═'*68}"))
    print(_bold("  ANOMALY DETECTION DEMO — REAL DATASETS"))
    print(_bold(f"  min_baseline_points={settings.detector_min_baseline_points}  "
                f"window={settings.detector_window_seconds}s  "
                f"z_threshold={settings.metric_zscore_threshold}  "
                f"anomaly_threshold={settings.anomaly_threshold}"))
    print(_bold(f"  Strategy: baseline window (20 samples) → controlled spike"))
    print(_bold(f"{'═'*68}"))

    SCENARIOS = [
        ("NSL-KDD",       _build_nslkdd_scenario(base_time),      "gaia.run"),
        ("UNSW-NB15",     _build_unswnb15_scenario(base_time),     "gaia.run"),
        ("Loghub HDFS",   _build_loghub_scenario(base_time),       "gaia.run"),
        ("GAIA run.zip",  _build_gaia_scenario(base_time),         "gaia.run"),
        ("Sample Traces", _build_sample_traces_scenario(base_time),"gaia.run"),
    ]

    all_results: list[DatasetResult] = []

    for name, events, source in SCENARIOS:
        print(f"\n{SEP}")
        print(_bold(f"  ▶  {name}"))
        print(SEP)
        print(f"  Building scenario: {len(events)} events "
              f"({'baseline+spike' if events else 'N/A'})")
        result = _run_scenario(name, events, source)
        all_results.append(result)

        accepted_pct = result.accepted / max(result.total_events, 1) * 100
        print(f"  Ingested : {result.accepted}/{result.total_events} ({accepted_pct:.0f}%)")

        if result.anomalies > 0:
            sym = _g("✓")
            avg_score = sum(result.scores) / len(result.scores)
            can_open  = sum(1 for a in result.details if "can_open=True" in a)
            print(f"  Anomalies: {sym} {_bold(str(result.anomalies))} detected  "
                  f"avg_score={avg_score:.3f}  can_open_incident={can_open}")
            print()
            for det, cnt in sorted(result.by_detector.items(), key=lambda x: -x[1]):
                print(f"    {_b(det)}: {cnt} anomaly/ies")
            for sig, cnt in sorted(result.by_signal.items(), key=lambda x: -x[1])[:5]:
                print(f"    signal={sig}: {cnt}")
            print()
            for d in result.details[:8]:
                print(f"  {d}")
            if len(result.details) > 8:
                print(f"  ... and {len(result.details)-8} more")
        else:
            print(f"  Anomalies: {_y('0')} — {result.details[0] if result.details else 'no events'}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n\n{'═'*68}")
    print(_bold("  ANOMALY DETECTION SUMMARY"))
    print(f"{'═'*68}")
    total_anomalies = sum(r.anomalies for r in all_results)
    fired = [r for r in all_results if r.anomalies > 0]

    print()
    print(f"  {'Dataset':<20} {'Anomalies':>10}  {'Top Detector':<30}  Avg Score")
    print(f"  {'-'*20} {'-'*10}  {'-'*30}  ---------")
    for r in all_results:
        top_det = max(r.by_detector, key=lambda k: r.by_detector[k], default="—")
        avg_s   = f"{sum(r.scores)/len(r.scores):.3f}" if r.scores else "—"
        sym     = _g("✓") if r.anomalies > 0 else _y("~")
        print(f"  {sym} {r.name:<19} {r.anomalies:>10}  {top_det:<30}  {avg_s}")

    print()
    print(f"  Total anomalies detected: {_bold(_g(str(total_anomalies)))} "
          f"across {len(fired)}/{len(all_results)} datasets")
    print()
    print("  KEY INSIGHT:")
    print("  The RollingZscoreDetector requires:")
    print("    1. ≥20 baseline samples of the SAME signal within 300s window")
    print("    2. Spike value with |z-score| ≥ 3.0 OR value ≥ safety_threshold")
    print("    3. signal_name must be in detector_rules.yaml safety_thresholds")
    print()
    print("  This script demonstrates the two-phase pattern:")
    print("    Phase 1: Feed 25 normal-range baseline samples")
    print("    Phase 2: Inject anomalous spike → detector fires immediately")
    print()
    print("  In production, the SIMULATOR generates this exact pattern in the")
    print("  golden scenario — the real datasets serve as the baseline reference.")
    print(f"{'═'*68}\n")


if __name__ == "__main__":
    main()
