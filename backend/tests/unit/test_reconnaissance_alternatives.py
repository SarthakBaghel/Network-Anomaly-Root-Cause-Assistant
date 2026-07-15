from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.contracts import AnomalyRecord, CanonicalEvent, Modality
from app.rca import AnalysisEngine, CandidateGenerator
from tests.support.rca_prerequisites import build_golden_analysis_bundle


OBSERVED_AT = datetime(2026, 7, 14, 10, 0, tzinfo=timezone.utc)


def _event(
    event_id: str,
    *,
    modality: Modality,
    event_type: str,
    signal_name: str | None = None,
    signal_value: float | None = None,
    raw_payload: dict | None = None,
    timestamp: datetime = OBSERVED_AT,
) -> CanonicalEvent:
    return CanonicalEvent(
        event_id=event_id,
        timestamp=timestamp,
        ingested_at=timestamp + timedelta(milliseconds=100),
        entity_id="api-gateway-01",
        modality=modality,
        event_type=event_type,
        severity=0.95,
        signal_name=signal_name,
        signal_value=signal_value,
        unit="count/60s" if modality is Modality.METRIC else None,
        trace_or_session_id="recon-test",
        source=f"test.{modality.value}",
        source_record_id=event_id,
        schema_version="1.0",
        quality_flags=["REFERENCE_DERIVED"],
        raw_payload=raw_payload or {},
    )


def _anomaly(event: CanonicalEvent, anomaly_type: str) -> AnomalyRecord:
    return AnomalyRecord(
        anomaly_id=f"anomaly-{event.event_id}",
        event_id=event.event_id,
        detector_id="reference_threshold_v1",
        detected_at=event.timestamp,
        anomaly_type=anomaly_type,
        score=1.0,
        threshold=0.75,
        context_only=False,
        can_open_incident=True,
        window_start=event.timestamp,
        window_end=event.timestamp,
        features={},
        explanation=f"Detected {anomaly_type}.",
    )


def _port_scan_bundle(*, authorized: bool = False):
    port_fanout = _event(
        "evt-port-fanout",
        modality=Modality.METRIC,
        event_type="UNIQUE_DESTINATION_PORTS",
        signal_name="unique_destination_ports",
        signal_value=950.0,
    )
    destination_fanout = _event(
        "evt-destination-fanout",
        modality=Modality.METRIC,
        event_type="DESTINATION_FANOUT",
        signal_name="destination_fanout",
        signal_value=300.0,
    )
    rejected = _event(
        "evt-rejected-connections",
        modality=Modality.METRIC,
        event_type="REJECTED_CONNECTION_RATE",
        signal_name="rejected_connection_rate",
        signal_value=0.87,
    )
    log = _event(
        "evt-port-scan-log",
        modality=Modality.LOG,
        event_type="PORT_SCAN_DETECTED",
        raw_payload={"source_fingerprint": "scanner-cluster-01"},
    )
    alert = _event(
        "evt-port-scan-alert",
        modality=Modality.ALERT,
        event_type="RECONNAISSANCESUSPECTED",
    )
    events = [port_fanout, destination_fanout, rejected, log, alert]
    if authorized:
        events.append(
            _event(
                "evt-scanner-allowlist",
                modality=Modality.CONFIG_CHANGE,
                event_type="SCANNER_ALLOWLIST_MATCH",
                timestamp=OBSERVED_AT - timedelta(seconds=30),
                raw_payload={
                    "scanner_authorized": True,
                    "source_fingerprint": "scanner-cluster-01",
                    "change_ticket": "SEC-2026-0714",
                },
            )
        )
    anomalies = (
        _anomaly(port_fanout, "PORT_FANOUT_HIGH"),
        _anomaly(destination_fanout, "DESTINATION_FANOUT_HIGH"),
        _anomaly(rejected, "REJECTED_CONNECTION_SPIKE"),
        _anomaly(alert, "RECONNAISSANCESUSPECTED"),
    )
    base = build_golden_analysis_bundle()
    incident = base.incident.model_copy(
        update={
            "incident_id": "inc-recon-test",
            "title": "Port-scan reconnaissance at the gateway",
            "started_at": OBSERVED_AT,
            "last_event_at": OBSERVED_AT,
            "primary_entity_id": "api-gateway-01",
            "primary_entity_type": "gateway",
            "affected_entity_ids": ("api-gateway-01",),
            "anomaly_count": len(anomalies),
        }
    )
    return base.model_copy(
        update={
            "incident": incident,
            "attached_events": tuple(
                sorted(events, key=lambda item: (item.timestamp, item.event_id))
            ),
            "anomalies": anomalies,
            "excluded_evaluations": (),
            "historical_matches": (),
        }
    )


def test_port_scan_ranks_three_evidence_backed_candidates() -> None:
    result = AnalysisEngine().analyse(_port_scan_bundle())

    assert [item.hypothesis_type for item in result.ranked_hypotheses] == [
        "external_probe",
        "authorized_security_scanner",
        "dos_or_traffic_surge",
    ]
    assert [item.evidence_score for item in result.ranked_hypotheses] == [
        85.0,
        72.5,
        35.0,
    ]
    coverage = {item.hypothesis_type: item.evidence_coverage for item in result.ranked_hypotheses}
    assert coverage["external_probe"].available == 3
    assert coverage["external_probe"].expected == 3
    assert coverage["authorized_security_scanner"].available == 2
    assert coverage["authorized_security_scanner"].expected == 4
    assert coverage["dos_or_traffic_surge"].available == 0
    assert coverage["dos_or_traffic_surge"].expected == 3


def test_allowlist_and_ticket_promote_authorized_scanner() -> None:
    result = AnalysisEngine().analyse(_port_scan_bundle(authorized=True))

    assert [item.hypothesis_type for item in result.ranked_hypotheses] == [
        "authorized_security_scanner",
        "external_probe",
        "dos_or_traffic_surge",
    ]
    by_type = {item.hypothesis_type: item for item in result.ranked_hypotheses}
    assert by_type["authorized_security_scanner"].evidence_score == 85.0
    assert by_type["authorized_security_scanner"].evidence_coverage.available == 4
    assert by_type["external_probe"].evidence_score == 66.3
    assert result.conflict_reason_codes == ("AUTHORIZED_SCANNER_MATCH",)
    assert result.conflict_evidence[0].source_event_id == "evt-scanner-allowlist"


def test_reconnaissance_alternatives_do_not_leak_to_unrelated_anomalies() -> None:
    packet_loss = _event(
        "evt-packet-loss",
        modality=Modality.METRIC,
        event_type="PACKET_LOSS_RATE",
        signal_name="packet_loss_rate",
        signal_value=0.20,
    )
    base = _port_scan_bundle()
    unrelated = base.model_copy(
        update={
            "attached_events": (packet_loss,),
            "anomalies": (_anomaly(packet_loss, "PACKET_LOSS_SPIKE"),),
            "incident": base.incident.model_copy(update={"anomaly_count": 1}),
        }
    )

    generated = CandidateGenerator().generate(unrelated)

    assert [item.hypothesis_type for item in generated] == ["network_path_congestion"]
