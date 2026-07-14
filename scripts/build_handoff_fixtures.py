from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_FIXTURES = ROOT / "backend" / "tests" / "fixtures"
GOLDEN_EVENTS = BACKEND_FIXTURES / "golden_events.jsonl"
TOPOLOGY = ROOT / "backend" / "app" / "fixtures" / "topology.json"
FRONTEND_MOCK = ROOT / "frontend" / "src" / "test-fixtures" / "golden-investigation-response.json"
RUN_ID = "run_007"
INCIDENT_ID = "inc_001"

WEIGHTS = {
    "symptom_compatibility": Decimal("0.25"),
    "topology_relevance": Decimal("0.20"),
    "direct_logs_alerts": Decimal("0.15"),
    "propagation_consistency": Decimal("0.15"),
    "metric_anomaly": Decimal("0.10"),
    "change_causal_fit": Decimal("0.10"),
    "temporal_proximity": Decimal("0.03"),
    "historical_similarity": Decimal("0.02"),
}


def pretty(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def score(factors: dict[str, float]) -> float:
    weighted = sum(WEIGHTS[name] * Decimal(str(value)) for name, value in factors.items())
    return float((Decimal("100") * weighted).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def load_events() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    events = [json.loads(line) for line in GOLDEN_EVENTS.read_text(encoding="utf-8").splitlines()]
    return events, {event["source_record_id"]: event for event in events}


def build_hypotheses() -> list[dict[str, Any]]:
    definitions = [
        (
            "hyp_001",
            "configuration_regression",
            "api-gateway-01",
            1,
            {"available": 6, "expected": 7},
            {
                "symptom_compatibility": 1.0,
                "topology_relevance": 1.0,
                "direct_logs_alerts": 0.6,
                "propagation_consistency": 1.0,
                "metric_anomaly": 0.91,
                "change_causal_fit": 1.0,
                "temporal_proximity": 1.0,
                "historical_similarity": 0.5,
            },
            "A gateway rate-limit change is the highest-ranked explanation for the observed traffic and downstream errors.",
        ),
        (
            "hyp_002",
            "dos_or_traffic_surge",
            "api-gateway-01",
            2,
            {"available": 2, "expected": 3},
            {
                "symptom_compatibility": 0.5,
                "topology_relevance": 1.0,
                "direct_logs_alerts": 0.6,
                "propagation_consistency": 1.0,
                "metric_anomaly": 0.91,
                "change_causal_fit": 0.0,
                "temporal_proximity": 0.0,
                "historical_similarity": 0.0,
            },
            "A traffic surge explains the impact pattern, but stable raw ingress and source distribution conflict with an external DoS cause.",
        ),
        (
            "hyp_003",
            "database_connection_exhaustion",
            "payment-db-01",
            3,
            {"available": 2, "expected": 3},
            {
                "symptom_compatibility": 0.5,
                "topology_relevance": 0.5,
                "direct_logs_alerts": 0.6,
                "propagation_consistency": 0.6667,
                "metric_anomaly": 0.0,
                "change_causal_fit": 0.0,
                "temporal_proximity": 0.0,
                "historical_similarity": 0.0,
            },
            "A payment timeout references the database, but normal database utilization conflicts with connection exhaustion.",
        ),
    ]
    return [
        {
            "hypothesis_id": hypothesis_id,
            "analysis_run_id": RUN_ID,
            "incident_id": INCIDENT_ID,
            "hypothesis_type": hypothesis_type,
            "candidate_entity_id": entity,
            "rank": rank,
            "evidence_score": score(factors),
            "evidence_coverage": coverage,
            "factor_scores": factors,
            "summary": summary,
        }
        for hypothesis_id, hypothesis_type, entity, rank, coverage, factors, summary in definitions
    ]


def evaluation(source: str, event: dict[str, Any], score_value: float, reasons: list[str], decision: str = "attached") -> dict[str, Any]:
    return {
        "event_id": event["event_id"],
        "source_record_id": source,
        "decision": decision,
        "attachment_score": score_value,
        "attachment_reasons": reasons,
    }


def build_incident_bundle(by_source: dict[str, dict[str, Any]]) -> dict[str, Any]:
    attached_specs = [
        ("config-change-000001", 0.9, ["SAME_ENTITY", "SHARED_SCENARIO_TRACE", "WITHIN_60_SECONDS"]),
        ("prom-raw_ingress_requests_per_second-0241", 1.0, ["SAME_ENTITY", "SHARED_SCENARIO_TRACE", "COMPATIBLE_SYMPTOM"]),
        ("prom-forwarded_requests_per_second-0242", 1.0, ["SAME_ENTITY", "SHARED_SCENARIO_TRACE", "COMPATIBLE_SYMPTOM"]),
        ("prom-active_connections_total-0243", 1.0, ["SAME_ENTITY", "SHARED_SCENARIO_TRACE", "COMPATIBLE_SYMPTOM"]),
        ("prom-connection_utilization-0244", 1.0, ["SAME_ENTITY", "SHARED_SCENARIO_TRACE", "COMPATIBLE_SYMPTOM"]),
        ("prom-tcp_resets_total-0245", 1.0, ["SAME_ENTITY", "SHARED_SCENARIO_TRACE", "COMPATIBLE_SYMPTOM"]),
        ("prom-tcp_retransmissions_total-0246", 1.0, ["SAME_ENTITY", "SHARED_SCENARIO_TRACE", "COMPATIBLE_SYMPTOM"]),
        ("alert-gateway-forwarded-0001", 1.0, ["SAME_ENTITY", "SHARED_SCENARIO_TRACE", "COMPATIBLE_SYMPTOM"]),
        ("prom-checkout_p95_latency_ms-0247", 1.0, ["ONE_TRAFFIC_HOP", "SHARED_SCENARIO_TRACE", "COMPATIBLE_SYMPTOM"]),
        ("log-payment-timeout-0001", 0.75, ["TWO_TRAFFIC_HOPS", "SHARED_SCENARIO_TRACE", "COMPATIBLE_SYMPTOM"]),
        ("alert-checkout-error-0001", 0.9, ["ONE_TRAFFIC_HOP", "SHARED_SCENARIO_TRACE", "COMPATIBLE_SYMPTOM"]),
        ("prom-db_connection_utilization-0248", 0.4, ["SHARED_SCENARIO_TRACE", "CONFLICTING_DB_EVIDENCE"]),
    ]
    attached = [evaluation(source, by_source[source], value, reasons) for source, value, reasons in attached_specs]
    excluded = [
        evaluation(
            "log-auth-certificate-0001",
            by_source["log-auth-certificate-0001"],
            -0.15,
            ["INCOMPATIBLE_MAINTENANCE_SYMPTOM", "EXPLICIT_DIFFERENT_TRACE"],
            decision="excluded",
        )
    ]
    return {
        "schema_version": "1.0",
        "version": "golden-incident-bundle-1.0",
        "incident": {
            "incident_id": INCIDENT_ID,
            "current_analysis_run_id": RUN_ID,
            "title": "Checkout degradation through API gateway",
            "status": "investigating",
            "severity": 0.95,
            "started_at": "2026-07-14T09:30:00.000Z",
            "last_event_at": "2026-07-14T09:31:40.000Z",
            "primary_entity_id": "api-gateway-01",
            "affected_entity_ids": ["api-gateway-01", "checkout-api-01", "payment-api-01"],
            "anomaly_count": 9,
            "top_hypothesis_id": "hyp_001",
            "confirmed_hypothesis_id": None,
        },
        "attached_events": attached,
        "excluded_events": excluded,
    }


def evidence_item(
    evidence_id: str,
    hypothesis_id: str,
    kind: str,
    source_event_id: str | None,
    statement: str,
    relevance: float,
    reason_code: str,
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "analysis_run_id": RUN_ID,
        "incident_id": INCIDENT_ID,
        "hypothesis_id": hypothesis_id,
        "kind": kind,
        "source_event_id": source_event_id,
        "statement": statement,
        "relevance": relevance,
        "reason_code": reason_code,
        "created_at": "2026-07-14T09:31:41.000Z",
    }


def build_evidence(by_source: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    event_id = lambda source: by_source[source]["event_id"]
    return {
        "hyp_001": [
            evidence_item("ev_001", "hyp_001", "observed", event_id("prom-forwarded_requests_per_second-0242"), "Gateway forwarded request rate reached 7,800 requests/s.", 0.95, "METRIC_THRESHOLD_EXCEEDED"),
            evidence_item("ev_002", "hyp_001", "observed", event_id("prom-connection_utilization-0244"), "Gateway connection utilization reached 0.92.", 0.92, "CONNECTION_UTILIZATION_HIGH"),
            evidence_item("ev_003", "hyp_001", "correlated", event_id("config-change-000001"), "Gateway rate limiting was disabled 30 seconds before the first symptom.", 0.9, "PRECEDING_RELEVANT_CHANGE"),
            evidence_item("ev_004", "hyp_001", "conflicting", event_id("alert-gateway-forwarded-0001"), "The gateway alert is also compatible with a traffic-surge alternative and does not prove the change caused the incident.", 0.45, "ALTERNATIVE_CAUSE_SIGNAL"),
            evidence_item("ev_005", "hyp_001", "missing", None, "Obtain WAF decision logs for 09:25–09:35 UTC.", 0.5, "MISSING_WAF_DECISION_LOGS"),
        ],
        "hyp_002": [
            evidence_item("ev_006", "hyp_002", "observed", event_id("prom-forwarded_requests_per_second-0242"), "Gateway forwarded request rate reached 7,800 requests/s.", 0.9, "FORWARDED_TRAFFIC_SPIKE"),
            evidence_item("ev_007", "hyp_002", "correlated", event_id("alert-gateway-forwarded-0001"), "A critical gateway traffic alert fired after the metric spike.", 0.7, "TRAFFIC_ALERT_CORRELATED"),
            evidence_item("ev_008", "hyp_002", "conflicting", event_id("prom-raw_ingress_requests_per_second-0241"), "Raw ingress remained stable near 7,800 requests/s with no new source distribution.", 0.95, "STABLE_RAW_INGRESS"),
            evidence_item("ev_009", "hyp_002", "missing", None, "Obtain WAF decisions and client/source-distribution details.", 0.5, "MISSING_SOURCE_DISTRIBUTION"),
        ],
        "hyp_003": [
            evidence_item("ev_010", "hyp_003", "observed", event_id("log-payment-timeout-0001"), "Payment API logged a timeout referencing payment-db-01.", 0.8, "DEPENDENCY_TIMEOUT_LOG"),
            evidence_item("ev_011", "hyp_003", "correlated", event_id("prom-checkout_p95_latency_ms-0247"), "Checkout latency increased on the dependency path to the payment database.", 0.6, "DEPENDENCY_PATH_LATENCY"),
            evidence_item("ev_012", "hyp_003", "conflicting", event_id("prom-db_connection_utilization-0248"), "Payment database connection utilization remained normal at 0.44.", 0.95, "NORMAL_DB_UTILIZATION"),
            evidence_item("ev_013", "hyp_003", "missing", None, "Obtain database connection-pool wait and rejected-lease metrics.", 0.5, "MISSING_DB_POOL_WAITS"),
        ],
    }


def recommendation(
    recommendation_id: str,
    hypothesis_id: str,
    step_id: str,
    title: str,
    step_type: str,
    risk: str,
    instructions: str,
) -> dict[str, Any]:
    return {
        "recommendation_id": recommendation_id,
        "analysis_run_id": RUN_ID,
        "incident_id": INCIDENT_ID,
        "hypothesis_id": hypothesis_id,
        "step_id": step_id,
        "title": title,
        "step_type": step_type,
        "risk_level": risk,
        "requires_human_approval": True,
        "instructions": instructions,
        "rationale": "Catalogue-backed recommendation; not automatically executed.",
    }


def build_recommendations() -> dict[str, list[dict[str, Any]]]:
    return {
        "hyp_001": [
            recommendation("rec_001", "hyp_001", "inspect-config-diff", "Inspect configuration diff", "diagnostic", "low", "Compare current and last-known-good rate-limit configuration."),
            recommendation("rec_002", "hyp_001", "propose-config-rollback", "Propose rate-limit rollback", "remediation", "low", "Prepare re-enabling the rate limiter for human approval."),
        ],
        "hyp_002": [recommendation("rec_003", "hyp_002", "inspect-ingress-distribution", "Inspect ingress distribution", "diagnostic", "low", "Compare raw ingress and source distribution with baseline.")],
        "hyp_003": [recommendation("rec_004", "hyp_003", "inspect-db-pool", "Inspect database pool", "diagnostic", "low", "Inspect active connections, waits, and rejected leases.")],
    }


def topology_snapshot() -> dict[str, Any]:
    topology = json.loads(TOPOLOGY.read_text(encoding="utf-8"))
    states = {
        "api-gateway-01": "suspected_root",
        "checkout-api-01": "primary_affected",
        "payment-api-01": "impact_path",
        "payment-db-01": "blast_radius",
        "auth-api-01": "blast_radius",
    }
    nodes = [
        {
            "id": node["id"],
            "name": node["name"],
            "type": node["entity_type"],
            "service": node["service"],
            "criticality": node["criticality"],
            "state": states[node["id"]],
        }
        for node in topology["nodes"]
    ]
    edges = [
        {
            **edge,
            "state": "impact_path"
            if edge["relation_type"] == "sends_traffic_to" and edge["target"] != "auth-api-01"
            else "blast_radius",
        }
        for edge in topology["edges"]
    ]
    return {"fixture_version": topology["version"], "nodes": nodes, "edges": edges}


def build_investigation(
    events: list[dict[str, Any]],
    by_source: dict[str, dict[str, Any]],
    incident_bundle: dict[str, Any],
    hypotheses: list[dict[str, Any]],
) -> dict[str, Any]:
    evaluation_by_event = {
        evaluation["event_id"]: evaluation
        for group in (incident_bundle["attached_events"], incident_bundle["excluded_events"])
        for evaluation in group
    }
    timeline = []
    for event in events:
        evaluation_data = evaluation_by_event.get(event["event_id"])
        if evaluation_data is None:
            continue
        timeline.append(
            {
                "event": event,
                "attachment_decision": evaluation_data["decision"],
                "attachment_score": evaluation_data["attachment_score"],
                "attachment_reasons": evaluation_data["attachment_reasons"],
                "hypothesis_relevance": {},
            }
        )
    fingerprint_source = "|".join(
        f"{item['event']['event_id']}:{json.dumps(item['event'], sort_keys=True)}"
        for item in timeline
        if item["attachment_decision"] == "attached"
    )
    fingerprint = hashlib.sha256(fingerprint_source.encode()).hexdigest()
    evidence = build_evidence(by_source)
    recommendations = build_recommendations()
    return {
        "generated_at": "2026-07-14T09:31:41.500Z",
        "analysis_run_id": RUN_ID,
        "analysis_run": {
            "analysis_run_id": RUN_ID,
            "incident_id": INCIDENT_ID,
            "revision": 7,
            "status": "current",
            "trigger_event_id": by_source["prom-db_connection_utilization-0248"]["event_id"],
            "input_fingerprint": f"sha256:{fingerprint}",
            "created_at": "2026-07-14T09:31:41.000Z",
            "completed_at": "2026-07-14T09:31:41.320Z",
            "algorithm_version": "rca-rules-1.1",
        },
        "incident": incident_bundle["incident"],
        "timeline": timeline,
        "topology": topology_snapshot(),
        "hypotheses": hypotheses,
        "evidence_by_hypothesis": evidence,
        "recommendations_by_hypothesis": recommendations,
        "explanation": {
            "analysis_run_id": RUN_ID,
            "incident_id": INCIDENT_ID,
            "hypothesis_id": "hyp_001",
            "generator": "template",
            "summary": "The probable root cause is a gateway configuration regression after rate limiting was disabled.",
            "claims": [
                {"claim": "Forwarded traffic increased after the configuration change.", "evidence_ids": ["ev_001", "ev_003"]},
                {"claim": "Stable raw ingress weakens an external DoS explanation.", "evidence_ids": ["ev_008"]},
            ],
            "diagnostic_step_ids": ["inspect-config-diff", "compare-pre-post-metrics"],
            "remediation_step_ids": ["propose-config-rollback"],
        },
        "reviews": [],
    }


def build_outputs() -> dict[Path, str]:
    events, by_source = load_events()
    hypotheses = build_hypotheses()
    if [item["evidence_score"] for item in hypotheses] != [92.1, 65.6, 41.5]:
        raise ValueError("frozen evidence scores do not calculate correctly")
    incident_bundle = build_incident_bundle(by_source)
    expected = {
        "schema_version": "1.0",
        "version": "golden-expected-analysis-1.0",
        "analysis_run_id": RUN_ID,
        "incident_id": INCIDENT_ID,
        "algorithm_version": "rca-rules-1.1",
        "weights": {name: float(value) for name, value in WEIGHTS.items()},
        "hypotheses": hypotheses,
        "typed_paths": {
            "configuration_traffic_impact": ["api-gateway-01", "checkout-api-01", "payment-api-01"],
            "database_dependency": ["checkout-api-01", "payment-api-01", "payment-db-01"],
        },
        "conflict_reason_codes": ["STABLE_RAW_INGRESS", "NORMAL_DB_UTILIZATION"],
    }
    investigation = build_investigation(events, by_source, incident_bundle, hypotheses)
    review_examples = {
        "schema_version": "1.0",
        "version": "review-examples-1.0",
        "records": [
            {
                "review_id": "rev_001",
                "incident_id": INCIDENT_ID,
                "analysis_run_id": RUN_ID,
                "hypothesis_id": "hyp_001",
                "decision": "confirmed",
                "client_action_id": "review-action-001",
                "requested_evidence_id": None,
                "reviewer": "team-demo-user",
                "comment": "Confirmed after reviewing the config diff and stable ingress distribution.",
                "created_at": "2026-07-14T09:32:30.000Z",
            }
        ],
    }
    audit_examples = {
        "schema_version": "1.0",
        "version": "audit-examples-1.0",
        "records": [
            {
                "audit_id": "audit_excluded_auth_001",
                "timestamp": "2026-07-14T09:32:00.200Z",
                "actor_type": "system",
                "actor_id": None,
                "action": "EVENT_EXCLUDED",
                "object_type": "event",
                "object_id": by_source["log-auth-certificate-0001"]["event_id"],
                "request_id": "req_batch_t120",
                "analysis_run_id": RUN_ID,
                "payload": {"reason_codes": ["INCOMPATIBLE_MAINTENANCE_SYMPTOM", "EXPLICIT_DIFFERENT_TRACE"]},
            },
            {
                "audit_id": "audit_published_007",
                "timestamp": "2026-07-14T09:31:41.320Z",
                "actor_type": "system",
                "actor_id": None,
                "action": "ANALYSIS_PUBLISHED",
                "object_type": "analysis_run",
                "object_id": RUN_ID,
                "request_id": "req_batch_t100",
                "analysis_run_id": RUN_ID,
                "payload": {"revision": 7, "top_hypothesis_id": "hyp_001"},
            },
        ],
    }
    return {
        BACKEND_FIXTURES / "golden_expected_analysis.json": pretty(expected),
        BACKEND_FIXTURES / "golden_incident_bundle.json": pretty(incident_bundle),
        BACKEND_FIXTURES / "golden_investigation_response.json": pretty(investigation),
        BACKEND_FIXTURES / "golden_review_examples.json": pretty(review_examples),
        BACKEND_FIXTURES / "golden_audit_examples.json": pretty(audit_examples),
        FRONTEND_MOCK: pretty(investigation),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = build_outputs()
    stale = []
    for path, content in outputs.items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    if stale:
        raise SystemExit("handoff fixtures are stale: " + ", ".join(stale))
    print(f"{'validated' if args.check else 'generated'} {len(outputs)} handoff artifacts")


if __name__ == "__main__":
    main()

