"""
Topology-Aware Cascade Anomaly Detector.

Detects downstream anomalies that are consistent with a known upstream failure,
using the typed topology graph traversal rules from BLUEPRINT §13.

This detector is BLUEPRINT-native:
  - §12.2: Uses typed-topology hops with relation_type and direction
  - §13.1: Traverses only sends_traffic_to or depends_on edges
  - §14.3: Its output feeds into the Topology relevance and Propagation consistency factors
  - §11.4: Implements the standard Detector protocol

Algorithm:
  1. For each accepted metric/log event on entity E, look up upstream entities
     within INCIDENT_MAX_TOPOLOGY_HOPS that already have recent anomalies.
  2. If upstream anomalies are present AND the current event's symptom family
     is compatible with a cascade propagation, emit a context_only=True cascade
     signal that strengthens the incident's topology evidence.
  3. Score: 0.7 × event.severity + 0.3 × max(upstream anomaly scores)
  4. Explanation names the upstream entity, relation_type, hop distance,
     and contributing upstream anomaly IDs.

Explainability rules:
  - features dict contains: upstream_entity, relation_type, hop_distance,
    upstream_anomaly_ids, cascade_score_formula, fired_reason
  - explanation string is human-readable with actual entity names and scores
  - context_only=True: cannot open an incident, only strengthens existing ones
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.contracts import AnomalyRecord, CanonicalEvent
from app.detection.common import record
from app.detection.detector import DetectionContext


@dataclass
class _UpstreamAnomaly:
    entity_id: str
    anomaly_id: str
    anomaly_type: str
    score: float
    relation_type: str
    hop_distance: int


def _clamp(v: float) -> float:
    return max(0.0, min(v, 1.0))


def _cascade_score(event_severity: float, upstream_max_score: float) -> float:
    raw = 0.7 * event_severity + 0.3 * upstream_max_score
    return float(Decimal(str(raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class TopologyCascadeDetector:
    """Topology-aware cascade propagation detector.

    Fires context_only signals when a downstream entity shows symptoms
    consistent with a known upstream failure. This tightens topology
    evidence in the RCA scoring without creating spurious incidents.
    """

    detector_id = "topology_cascade_v1"

    def evaluate(self, event: CanonicalEvent, context: DetectionContext) -> list[AnomalyRecord]:
        # Only run if topology and recent_anomalies are available in context
        topology = getattr(context, "topology", None)
        recent_anomalies = getattr(context, "recent_anomalies", [])
        if topology is None or not recent_anomalies:
            return []

        # Skip config markers — they use context_only separately
        if event.modality.value == "config_change":
            return []

        upstream_hits: list[_UpstreamAnomaly] = []

        for anomaly in recent_anomalies:
            if anomaly.entity_id == event.entity_id:
                continue  # Same entity — not a cascade
            # Check: is anomaly.entity_id upstream of event.entity_id?
            for rel_type in ("sends_traffic_to", "depends_on"):
                try:
                    distance = topology.distance(anomaly.entity_id, event.entity_id, rel_type)
                except Exception:
                    distance = None
                if distance is not None and 1 <= distance <= 2:
                    upstream_hits.append(_UpstreamAnomaly(
                        entity_id=anomaly.entity_id,
                        anomaly_id=anomaly.anomaly_id,
                        anomaly_type=anomaly.anomaly_type,
                        score=anomaly.score,
                        relation_type=rel_type,
                        hop_distance=distance,
                    ))
                    break

        if not upstream_hits:
            return []

        # Use the closest (lowest hop), highest-scoring upstream anomaly
        best = sorted(upstream_hits, key=lambda x: (x.hop_distance, -x.score))[0]
        cascade_score = _cascade_score(event.severity, best.score)

        # Only emit if above the anomaly threshold
        from app.config import settings
        if cascade_score < settings.anomaly_threshold:
            return []

        features: dict[str, Any] = {
            "source_record_id": event.source_record_id,
            "detector_algorithm": "topology_cascade",
            "upstream_entity": best.entity_id,
            "upstream_anomaly_id": best.anomaly_id,
            "upstream_anomaly_type": best.anomaly_type,
            "upstream_anomaly_score": best.score,
            "relation_type": best.relation_type,
            "hop_distance": best.hop_distance,
            "cascade_score_formula": (
                f"0.7 × {event.severity:.2f} + 0.3 × {best.score:.2f} = {cascade_score:.2f}"
            ),
            "fired_reason": "topology_cascade",
            "all_upstream_hits": [
                {"entity_id": h.entity_id, "hop": h.hop_distance, "score": h.score}
                for h in upstream_hits
            ],
        }
        explanation = (
            f"Cascade propagation: {event.entity_id} shows {event.event_type} "
            f"consistent with upstream failure at {best.entity_id} "
            f"(relation={best.relation_type}, hop={best.hop_distance}, "
            f"upstream_score={best.score:.2f}). "
            f"Cascade score = 0.7×{event.severity:.2f} + 0.3×{best.score:.2f} = {cascade_score:.2f}."
        )
        return [record(
            event, context,
            detector_id=self.detector_id,
            anomaly_type=f"CASCADE_{best.anomaly_type}",
            score=cascade_score,
            features=features,
            explanation=explanation,
            context_only=True,
            can_open_incident=False,  # BLUEPRINT §12.1: context_only cannot open incidents
        )]
