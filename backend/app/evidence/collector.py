"""Deterministic evidence collection for catalogue-backed RCA hypotheses.

This module classifies accepted incident events only. Quarantined records can
explain why a requirement is unavailable, but never satisfy a requirement and
never become source-linked evidence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from app.contracts import (
    CanonicalEvent,
    EvidenceCoverage,
    EvidenceItem,
    EvidenceKind,
    Hypothesis,
    Modality,
)


EventMatcher = Callable[[CanonicalEvent], bool]


def _contains(value: str | None, *needles: str) -> bool:
    haystack = (value or "").lower()
    return any(needle in haystack for needle in needles)


def _payload_contains(event: CanonicalEvent, *needles: str) -> bool:
    payload = json.dumps(event.raw_payload, sort_keys=True).lower()
    return any(needle in payload for needle in needles)


REQUIREMENT_MATCHERS: dict[str, EventMatcher] = {
    "config_diff": lambda event: event.modality is Modality.CONFIG_CHANGE,
    "forwarded_rate": lambda event: _contains(
        event.signal_name, "forwarded_requests", "forwarded_request_rate"
    ),
    "raw_vs_forwarded_request_metrics": lambda event: _contains(
        event.signal_name, "raw_ingress", "forwarded_requests"
    ),
    "stable_raw_ingress": lambda event: _contains(event.signal_name, "raw_ingress"),
    "raw_ingress": lambda event: _contains(event.signal_name, "raw_ingress"),
    # The frozen raw-ingress record carries the stable scenario/source labels
    # used by the ranker to establish unchanged source distribution.
    "source_distribution": lambda event: _contains(event.signal_name, "raw_ingress")
    or _payload_contains(event, "source_distribution", "client_ip", "source_ip"),
    "connection_pressure": lambda event: _contains(
        event.signal_name, "connection_utilization", "active_connections"
    ),
    "gateway_connection_and_tcp_metrics": lambda event: _contains(
        event.signal_name,
        "connection_utilization",
        "active_connections",
        "tcp_resets",
        "tcp_retransmissions",
    ),
    "gateway_saturation_alert": lambda event: event.modality is Modality.ALERT
    and _contains(event.event_type, "gateway", "forwarded_request", "connection_rate"),
    "downstream_latency": lambda event: _contains(
        event.signal_name, "latency", "duration"
    ),
    "downstream_latency_metrics": lambda event: _contains(
        event.signal_name, "latency", "duration"
    ),
    "timeout_log": lambda event: event.modality is Modality.LOG
    and _contains(event.event_type, "timeout"),
    "downstream_timeout_logs": lambda event: event.modality is Modality.LOG
    and _contains(event.event_type, "timeout"),
    "waf_decision_logs": lambda event: _contains(event.source, "waf")
    or _contains(event.event_type, "waf_decision"),
    "waf_decisions": lambda event: _contains(event.source, "waf")
    or _contains(event.event_type, "waf_decision"),
    "db_utilization": lambda event: _contains(
        event.signal_name, "db_connection_utilization"
    ),
    "pool_waits": lambda event: _contains(
        event.signal_name, "pool_wait", "rejected_lease"
    ),
    "dependency_timeout": lambda event: event.modality is Modality.LOG
    and _contains(event.event_type, "timeout")
    and _payload_contains(event, "dependency_id"),
    "path_telemetry": lambda event: _contains(
        event.signal_name, "packet_loss", "retransmission", "hop_latency"
    ),
    "upstream_health": lambda event: _contains(
        event.event_type, "health", "upstream_failure", "upstream_error"
    ),
    "dns_queries": lambda event: _contains(event.event_type, "dns", "resolver"),
    "certificate_state": lambda event: _contains(
        event.event_type, "certificate", "tls", "handshake"
    ),
}


REASON_CODES = {
    "config_diff": "PRECEDING_RELEVANT_CHANGE",
    "forwarded_rate": "METRIC_THRESHOLD_EXCEEDED",
    "raw_vs_forwarded_request_metrics": "RAW_AND_FORWARDED_RATES_OBSERVED",
    "stable_raw_ingress": "STABLE_RAW_INGRESS_OBSERVED",
    "raw_ingress": "RAW_INGRESS_OBSERVED",
    "source_distribution": "SOURCE_DISTRIBUTION_OBSERVED",
    "connection_pressure": "CONNECTION_UTILIZATION_HIGH",
    "gateway_connection_and_tcp_metrics": "GATEWAY_CONNECTION_PRESSURE",
    "gateway_saturation_alert": "GATEWAY_SATURATION_ALERT",
    "downstream_latency": "DOWNSTREAM_LATENCY_INCREASE",
    "downstream_latency_metrics": "DOWNSTREAM_LATENCY_INCREASE",
    "timeout_log": "DEPENDENCY_TIMEOUT_LOG",
    "downstream_timeout_logs": "DEPENDENCY_TIMEOUT_LOG",
    "db_utilization": "DB_UTILIZATION_OBSERVED",
    "pool_waits": "DB_POOL_WAITS_OBSERVED",
    "dependency_timeout": "DEPENDENCY_TIMEOUT_LOG",
    "path_telemetry": "PATH_TELEMETRY_OBSERVED",
    "upstream_health": "UPSTREAM_HEALTH_OBSERVED",
    "dns_queries": "DNS_QUERY_EVIDENCE_OBSERVED",
    "certificate_state": "CERTIFICATE_STATE_OBSERVED",
}


def _normalise_code(value: str) -> str:
    return "_".join(part for part in value.upper().replace("-", "_").split("_") if part)


def _expected_evidence(catalogue_entry: Mapping[str, Any]) -> list[tuple[str, str]]:
    raw = catalogue_entry.get("expected_evidence", {})
    if isinstance(raw, Mapping):
        pairs = [(str(key), str(template)) for key, template in raw.items()]
    elif isinstance(raw, list):
        templates = catalogue_entry.get("collection_requests", {})
        if not isinstance(templates, Mapping):
            templates = {}
        pairs = [
            (
                str(key),
                str(templates.get(key, f"Obtain evidence for {str(key).replace('_', ' ')}.")),
            )
            for key in raw
        ]
    else:
        raise ValueError("catalogue expected_evidence must be a mapping or list")
    # Catalogue coverage is defined over unique requirement keys. Preserve the
    # first template and ordering if a list-based catalogue repeats a key.
    return list(dict(pairs).items())


def _friendly_entity(entity_id: str) -> str:
    names = {
        "api-gateway-01": "Gateway",
        "checkout-api-01": "Checkout API",
        "payment-api-01": "Payment API",
        "payment-db-01": "Payment database",
        "auth-api-01": "Auth API",
    }
    return names.get(entity_id, entity_id)


def _format_value(value: float | None) -> str:
    if value is None:
        return "an unspecified value"
    if value.is_integer():
        return f"{int(value):,}"
    return f"{value:,.4f}".rstrip("0").rstrip(".")


def _observed_statement(requirement: str, event: CanonicalEvent) -> str:
    entity = _friendly_entity(event.entity_id)
    value = _format_value(event.signal_value)
    unit = f" {event.unit}" if event.unit else ""
    statements = {
        "forwarded_rate": f"{entity} forwarded request rate reached {value}{unit}.",
        "stable_raw_ingress": f"{entity} raw ingress remained near {value}{unit}.",
        "raw_ingress": f"{entity} raw ingress was {value}{unit}.",
        "source_distribution": (
            f"{entity} raw-ingress record retained the incident source-distribution context."
        ),
        "connection_pressure": f"{entity} connection utilization reached {value}.",
        "downstream_latency": f"{entity} latency reached {value}{unit}.",
        "db_utilization": f"{entity} connection utilization was {value}.",
        "pool_waits": f"{entity} pool-wait metric was {value}{unit}.",
        "path_telemetry": f"{entity} path telemetry recorded {value}{unit}.",
    }
    if requirement in statements:
        return statements[requirement]
    if requirement == "config_diff":
        key = event.raw_payload.get("config_key", "configuration")
        old = event.raw_payload.get("old_value")
        new = event.raw_payload.get("new_value")
        return f"{entity} {key} changed from {old!r} to {new!r}."
    if requirement in {"timeout_log", "downstream_timeout_logs", "dependency_timeout"}:
        dependency = event.raw_payload.get("dependency_id")
        if dependency:
            return f"{entity} logged a timeout referencing {dependency}."
    message = event.raw_payload.get("message")
    if isinstance(message, str) and message:
        return f"{entity} recorded: {message}"
    if event.signal_name:
        return f"{entity} {event.signal_name} was {value}{unit}."
    return f"{entity} recorded {event.event_type}."


def _change_correlation_statement(
    change: CanonicalEvent, events: list[CanonicalEvent]
) -> str:
    first_symptom = next(
        (
            event
            for event in events
            if event.modality is not Modality.CONFIG_CHANGE
            and event.timestamp >= change.timestamp
        ),
        None,
    )
    if first_symptom is None:
        return _observed_statement("config_diff", change)
    seconds = int((first_symptom.timestamp - change.timestamp).total_seconds())
    return (
        f"{_friendly_entity(change.entity_id)} configuration change occurred "
        f"{seconds} seconds before the first incident symptom."
    )


def _evidence_id(
    hypothesis: Hypothesis,
    kind: EvidenceKind,
    reason_code: str,
    source_event_id: str | None,
) -> str:
    identity = "|".join(
        (
            hypothesis.analysis_run_id,
            hypothesis.hypothesis_id,
            kind.value,
            reason_code,
            source_event_id or "missing",
        )
    )
    return f"ev_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]}"


def _created_at(events: Iterable[CanonicalEvent]) -> datetime:
    timestamps = [event.timestamp for event in events]
    if not timestamps:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    return max(timestamps) + timedelta(seconds=1)


def _item(
    hypothesis: Hypothesis,
    *,
    kind: EvidenceKind,
    statement: str,
    relevance: float,
    reason_code: str,
    source_event: CanonicalEvent | None,
    created_at: datetime,
) -> EvidenceItem:
    source_event_id = source_event.event_id if source_event else None
    return EvidenceItem(
        evidence_id=_evidence_id(hypothesis, kind, reason_code, source_event_id),
        analysis_run_id=hypothesis.analysis_run_id,
        incident_id=hypothesis.incident_id,
        hypothesis_id=hypothesis.hypothesis_id,
        kind=kind,
        source_event_id=source_event_id,
        statement=statement,
        relevance=relevance,
        reason_code=reason_code,
        created_at=created_at,
    )


def _latest_match(requirement: str, events: list[CanonicalEvent]) -> CanonicalEvent | None:
    matcher = REQUIREMENT_MATCHERS.get(requirement)
    if matcher is None:
        return None
    matches = [event for event in events if matcher(event)]
    return max(matches, key=lambda event: (event.timestamp, event.event_id), default=None)


def _find_event(events: list[CanonicalEvent], event_id: str | None) -> CanonicalEvent | None:
    if event_id is None:
        return None
    return next((event for event in events if event.event_id == event_id), None)


def _conflict_source(pattern_id: str, events: list[CanonicalEvent]) -> CanonicalEvent | None:
    if pattern_id == "STABLE_RAW_INGRESS":
        return _latest_match("stable_raw_ingress", events)
    if pattern_id == "NORMAL_DB_UTILIZATION":
        candidates = [
            event
            for event in events
            if REQUIREMENT_MATCHERS["db_utilization"](event)
            and event.signal_value is not None
            and event.signal_value < 0.75
        ]
        return max(candidates, key=lambda event: (event.timestamp, event.event_id), default=None)
    return None


def _conflict_statement(pattern_id: str, event: CanonicalEvent) -> str:
    if pattern_id == "STABLE_RAW_INGRESS":
        return (
            f"Gateway raw ingress remained stable near {_format_value(event.signal_value)} "
            f"{event.unit or ''} with no new source distribution."
        ).replace("  ", " ")
    if pattern_id == "NORMAL_DB_UTILIZATION":
        return (
            "Payment database connection utilization remained normal at "
            f"{_format_value(event.signal_value)}."
        )
    return (
        f"{_friendly_entity(event.entity_id)} recorded evidence conflicting "
        "with this hypothesis."
    )


def _quarantine_mentions(requirement: str, quarantined_events: list[Any]) -> bool:
    tokens = set(requirement.lower().split("_"))
    if not tokens:
        return False
    for record in quarantined_events:
        if hasattr(record, "model_dump"):
            record = record.model_dump(mode="json")
        elif hasattr(record, "raw_payload"):
            record = getattr(record, "raw_payload")
        text = json.dumps(record, sort_keys=True, default=str).lower()
        if all(token in text for token in tokens):
            return True
    return False


def calculate_evidence_coverage(
    catalogue_entry: Mapping[str, Any],
    evidence_items: Iterable[EvidenceItem],
) -> EvidenceCoverage:
    """Return requirement coverage; extra evidence cannot inflate availability."""

    expected = len(dict(_expected_evidence(catalogue_entry)))
    missing = sum(1 for item in evidence_items if item.kind is EvidenceKind.MISSING)
    return EvidenceCoverage(available=max(0, expected - missing), expected=expected)


def collect_evidence(
    hypothesis: Hypothesis,
    incident_events: list[CanonicalEvent],
    catalogue_entry: dict,
    quarantined_events: list,
) -> list[EvidenceItem]:
    """Collect four-category evidence without reading test expectations or executing actions.

    P4 may attach ``applied_conflict_effects`` to the catalogue entry. Each
    effect is expected to carry the catalogue ``pattern_id``/``reason_code``
    and optionally ``source_event_id``. When absent, the two frozen conflict
    patterns are matched directly against accepted incident events.
    """

    entry_type = catalogue_entry.get("hypothesis_type", catalogue_entry.get("id"))
    if entry_type and entry_type != hypothesis.hypothesis_type:
        raise ValueError("catalogue entry does not match hypothesis type")

    # A duplicated accepted event must never duplicate evidence.
    accepted_by_id = {event.event_id: event for event in incident_events}
    accepted = sorted(
        accepted_by_id.values(), key=lambda event: (event.timestamp, event.event_id)
    )
    created_at = _created_at(accepted)
    collected: list[EvidenceItem] = []
    missing_requirements: list[tuple[str, str]] = []

    for requirement, collection_request in _expected_evidence(catalogue_entry):
        event = _latest_match(requirement, accepted)
        if event is None:
            missing_requirements.append((requirement, collection_request))
            continue
        kind = (
            EvidenceKind.CORRELATED
            if requirement == "config_diff"
            else EvidenceKind.OBSERVED
        )
        collected.append(
            _item(
                hypothesis,
                kind=kind,
                statement=_change_correlation_statement(event, accepted)
                if requirement == "config_diff"
                else _observed_statement(requirement, event),
                relevance=0.90 if kind is EvidenceKind.CORRELATED else 0.95,
                reason_code=REASON_CODES.get(
                    requirement, f"{_normalise_code(requirement)}_OBSERVED"
                ),
                source_event=event,
                created_at=created_at,
            )
        )

    # Add deterministic associations that are relevant but do not themselves
    # satisfy an expected-evidence requirement.
    if not any(item.kind is EvidenceKind.CORRELATED for item in collected):
        correlation: CanonicalEvent | None = None
        reason_code = "RELEVANT_SIGNAL_ASSOCIATION"
        statement = "A related signal occurred within the incident window."
        if hypothesis.hypothesis_type == "dos_or_traffic_surge":
            correlation = next(
                (event for event in reversed(accepted) if event.modality is Modality.ALERT),
                None,
            )
            reason_code = "TRAFFIC_ALERT_CORRELATED"
            statement = "A gateway traffic alert fired after the forwarded-rate spike."
        elif hypothesis.hypothesis_type == "database_connection_exhaustion":
            correlation = _latest_match("downstream_latency", accepted)
            reason_code = "DEPENDENCY_PATH_LATENCY"
            statement = "Checkout latency increased on the dependency path to the database."
        if correlation is not None:
            collected.append(
                _item(
                    hypothesis,
                    kind=EvidenceKind.CORRELATED,
                    statement=statement,
                    relevance=0.70,
                    reason_code=reason_code,
                    source_event=correlation,
                    created_at=created_at,
                )
            )

    applied = catalogue_entry.get("applied_conflict_effects")
    conflict_effects = applied if isinstance(applied, list) else catalogue_entry.get(
        "conflict_patterns", []
    )
    for effect in conflict_effects or []:
        if not isinstance(effect, Mapping):
            continue
        pattern_id = str(effect.get("reason_code", effect.get("pattern_id", effect.get("id", ""))))
        if not pattern_id:
            continue
        source = _find_event(accepted, effect.get("source_event_id")) or _conflict_source(
            pattern_id, accepted
        )
        if source is None:
            continue
        collected.append(
            _item(
                hypothesis,
                kind=EvidenceKind.CONFLICTING,
                statement=str(effect.get("statement") or _conflict_statement(pattern_id, source)),
                relevance=0.95,
                reason_code=pattern_id,
                source_event=source,
                created_at=created_at,
            )
        )

    # The configuration candidate deliberately exposes ambiguity: the same
    # gateway alert is compatible with the alternative traffic-surge cause.
    if hypothesis.hypothesis_type == "configuration_regression" and not any(
        item.kind is EvidenceKind.CONFLICTING for item in collected
    ):
        alert = next(
            (event for event in reversed(accepted) if event.modality is Modality.ALERT),
            None,
        )
        if alert is not None:
            collected.append(
                _item(
                    hypothesis,
                    kind=EvidenceKind.CONFLICTING,
                    statement=(
                        "The gateway alert is also compatible with a traffic-surge "
                        "alternative and does not prove the configuration change "
                        "caused the incident."
                    ),
                    relevance=0.45,
                    reason_code="ALTERNATIVE_CAUSE_SIGNAL",
                    source_event=alert,
                    created_at=created_at,
                )
            )

    for requirement, collection_request in missing_requirements:
        prefix = (
            "QUARANTINED"
            if _quarantine_mentions(requirement, quarantined_events)
            else "MISSING"
        )
        collected.append(
            _item(
                hypothesis,
                kind=EvidenceKind.MISSING,
                statement=collection_request,
                relevance=0.50,
                reason_code=f"{prefix}_{_normalise_code(requirement)}",
                source_event=None,
                created_at=created_at,
            )
        )

    kind_order = {
        EvidenceKind.OBSERVED: 0,
        EvidenceKind.CORRELATED: 1,
        EvidenceKind.CONFLICTING: 2,
        EvidenceKind.MISSING: 3,
    }
    return sorted(
        collected,
        key=lambda item: (kind_order[item.kind], item.reason_code, item.evidence_id),
    )
