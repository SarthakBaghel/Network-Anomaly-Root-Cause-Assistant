from app.detection.detector import DetectionContext
from app.detection.reference_threshold import ReferenceThresholdDetector
from app.detection.trace_anomaly import TraceLatencyDetector, TraceStructureDetector
from app.ingestion.adapters import ADAPTERS
from app.simulator.scenario_catalogue import groups_for_scenario


def _events(scenario_id: str):
    _resolved, groups = groups_for_scenario(scenario_id)
    return [ADAPTERS[source].adapt(raw) for group in groups for source, raw in group.records]


def test_reference_threshold_is_limited_to_curated_scenario_transformations() -> None:
    event = next(
        item
        for item in _events("network_path_congestion")
        if item.signal_name == "packet_loss_rate"
    )
    detector = ReferenceThresholdDetector()

    assert detector.evaluate(event, DetectionContext())[0].anomaly_type == "PACKET_LOSS_SPIKE"

    raw_payload = dict(event.raw_payload)
    raw_payload["provenance"] = {
        **raw_payload["provenance"],
        "transformation_version": "dataset-bridge-1.0",
    }
    bulk_evaluation_event = event.model_copy(update={"raw_payload": raw_payload})
    assert detector.evaluate(bulk_evaluation_event, DetectionContext()) == []


def test_trace_detectors_find_latency_and_missing_parent_without_dataset_labels() -> None:
    root, slow, orphan = _events("trace_anomaly")
    latency = TraceLatencyDetector().evaluate(slow, DetectionContext(history=[root]))
    structure = TraceStructureDetector().evaluate(orphan, DetectionContext(history=[root, slow]))

    assert [item.anomaly_type for item in latency] == ["TRACE_LATENCY_ANOMALY"]
    assert [item.anomaly_type for item in structure] == ["TRACE_STRUCTURE_ANOMALY"]
    assert not {
        "nodeLatencyLabel",
        "graphLatencyLabel",
        "graphStructureLabel",
    }.intersection(slow.raw_payload)
