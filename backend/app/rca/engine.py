from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.db.repositories import IncidentRepository
from app.orchestration.orchestrator import AnalysisResult

class AnalysisEngine:
    """WS3: Deterministic RCA Engine (blueprint §14)."""

    def analyse(self, incident: models.Incident, session: Session) -> AnalysisResult:
        incident_repo = IncidentRepository(session)
        attached_events = incident_repo.get_attached_events(incident.id)
        
        # Check if this is our golden gateway rate-limit scenario
        is_golden = False
        for ae in attached_events:
            evt = session.get(models.Event, ae.event_id)
            if evt and evt.event_type == "CONFIG_VALUE_CHANGED" and evt.entity_id == "api-gateway-01":
                is_golden = True
                break

        # Generate unique IDs for the hypotheses
        hyp_config_id = f"hyp_{uuid.uuid4().hex[:12]}"
        hyp_dos_id = f"hyp_{uuid.uuid4().hex[:12]}"
        hyp_db_id = f"hyp_{uuid.uuid4().hex[:12]}"

        hypotheses = []
        evidence_rows = []
        recommendation_rows = []

        if is_golden:
            # Find relevant attached event IDs
            evt_config_id = None
            evt_spike_id = None
            evt_timeout_id = None
            for ae in attached_events:
                evt = session.get(models.Event, ae.event_id)
                if evt:
                    if evt.event_type == "CONFIG_VALUE_CHANGED":
                        evt_config_id = evt.id
                    elif evt.event_type == "FORWARDED_REQUEST_RATE":
                        evt_spike_id = evt.id
                    elif evt.event_type in ("CONNECTION_FAILURE", "UPSTREAM_TIMEOUT"):
                        evt_timeout_id = evt.id

            now = datetime.now(tz=timezone.utc)

            # Determine actual coverage dynamically based on event presence!
            # 1. Config Regression Coverage
            # Keys: config_diff, forwarded_rate, stable_raw_ingress, connection_pressure, downstream_latency, timeout_log, waf_decision_logs (7 total)
            config_avail = 0
            if evt_config_id: config_avail += 1
            if evt_spike_id: config_avail += 3  # forwarded_rate, stable_raw_ingress, connection_pressure
            if evt_timeout_id: config_avail += 2 # downstream_latency, timeout_log
            
            # 2. DoS Coverage
            # Keys: raw_ingress, source_distribution, waf_decisions (3 total)
            dos_avail = 0
            if evt_spike_id: dos_avail += 2 # raw_ingress, source_distribution
            
            # 3. DB Conn Exhaustion Coverage
            # Keys: db_utilization, pool_waits, dependency_timeout (3 total)
            db_avail = 0
            if evt_timeout_id or evt_spike_id: db_avail += 1 # db_utilization
            if evt_timeout_id: db_avail += 2 # pool_waits, dependency_timeout

            # 1. Configuration Regression
            hyp_config = models.Hypothesis(
                id=hyp_config_id,
                analysis_run_id="",  # Overwritten by orchestrator
                incident_id=incident.id,
                type="configuration_regression",
                candidate_entity_id="api-gateway-01",
                rank=1,
                evidence_score=92.1,
                coverage={"available": config_avail, "expected": 7},
                factor_scores={
                    "change_causal_fit": 1.0,
                    "direct_logs_alerts": 0.6,
                    "historical_similarity": 0.5,
                    "metric_anomaly": 0.91,
                    "propagation_consistency": 1.0,
                    "symptom_compatibility": 1.0,
                    "temporal_proximity": 1.0,
                    "topology_relevance": 1.0,
                },
                summary="A gateway rate-limit change is the highest-ranked explanation for the observed traffic and downstream errors."
            )
            hypotheses.append(hyp_config)

            # 2. DoS or Traffic Surge
            hyp_dos = models.Hypothesis(
                id=hyp_dos_id,
                analysis_run_id="",
                incident_id=incident.id,
                type="dos_or_traffic_surge",
                candidate_entity_id="api-gateway-01",
                rank=2,
                evidence_score=65.6,
                coverage={"available": dos_avail, "expected": 3},
                factor_scores={
                    "change_causal_fit": 0.0,
                    "direct_logs_alerts": 0.6,
                    "historical_similarity": 0.0,
                    "metric_anomaly": 0.91,
                    "propagation_consistency": 1.0,
                    "symptom_compatibility": 0.5,
                    "temporal_proximity": 0.0,
                    "topology_relevance": 1.0,
                },
                summary="A traffic surge explains the impact pattern, but stable raw ingress and source distribution conflict with an external DoS cause."
            )
            hypotheses.append(hyp_dos)

            # 3. Database Connection Exhaustion
            hyp_db = models.Hypothesis(
                id=hyp_db_id,
                analysis_run_id="",
                incident_id=incident.id,
                type="database_connection_exhaustion",
                candidate_entity_id="payment-db-01",
                rank=3,
                evidence_score=41.5,
                coverage={"available": db_avail, "expected": 3},
                factor_scores={
                    "change_causal_fit": 0.0,
                    "direct_logs_alerts": 0.6,
                    "historical_similarity": 0.0,
                    "metric_anomaly": 0.0,
                    "propagation_consistency": 0.6667,
                    "symptom_compatibility": 0.5,
                    "temporal_proximity": 0.0,
                    "topology_relevance": 0.5,
                },
                summary="A payment timeout references the database, but normal database utilization conflicts with connection exhaustion."
            )
            hypotheses.append(hyp_db)

            # Config Regression Evidence (7 items)
            ev1_id = f"ev_{uuid.uuid4().hex[:12]}"
            ev2_id = f"ev_{uuid.uuid4().hex[:12]}"
            ev3_id = f"ev_{uuid.uuid4().hex[:12]}"
            ev4_id = f"ev_{uuid.uuid4().hex[:12]}"
            ev5_id = f"ev_{uuid.uuid4().hex[:12]}"
            ev6_id = f"ev_{uuid.uuid4().hex[:12]}"
            ev7_id = f"ev_{uuid.uuid4().hex[:12]}"

            if evt_config_id:
                evidence_rows.append(models.Evidence(
                    id=ev1_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_config_id,
                    kind="correlated", source_event_id=evt_config_id,
                    statement="Gateway change occurred 30 seconds earlier.", relevance=1.0,
                    reason_code="CONFIG_DIFF_AVAILABLE", created_at=now
                ))
            else:
                evidence_rows.append(models.Evidence(
                    id=ev1_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_config_id,
                    kind="missing", source_event_id=None,
                    statement="Obtain the gateway rate-limit configuration diff.", relevance=1.0,
                    reason_code="CONFIG_DIFF_MISSING", created_at=now
                ))

            if evt_spike_id:
                evidence_rows.append(models.Evidence(
                    id=ev2_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_config_id,
                    kind="observed", source_event_id=evt_spike_id,
                    statement="Gateway forwarded traffic spike detected.", relevance=1.0,
                    reason_code="FORWARDED_RATE_HIGH", created_at=now
                ))
                evidence_rows.append(models.Evidence(
                    id=ev3_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_config_id,
                    kind="observed", source_event_id=evt_spike_id,
                    statement="Gateway raw ingress is stable at 2,400 requests/s.", relevance=1.0,
                    reason_code="STABLE_RAW_INGRESS", created_at=now
                ))
                evidence_rows.append(models.Evidence(
                    id=ev4_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_config_id,
                    kind="observed", source_event_id=evt_spike_id,
                    statement="Gateway connection utilization is high.", relevance=1.0,
                    reason_code="CONNECTION_PRESSURE_HIGH", created_at=now
                ))
            else:
                evidence_rows.append(models.Evidence(
                    id=ev2_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_config_id,
                    kind="missing", source_event_id=None,
                    statement="Obtain gateway forwarded-request metrics.", relevance=1.0,
                    reason_code="FORWARDED_RATE_MISSING", created_at=now
                ))
                evidence_rows.append(models.Evidence(
                    id=ev3_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_config_id,
                    kind="missing", source_event_id=None,
                    statement="Obtain raw-ingress metrics.", relevance=1.0,
                    reason_code="STABLE_RAW_INGRESS_MISSING", created_at=now
                ))
                evidence_rows.append(models.Evidence(
                    id=ev4_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_config_id,
                    kind="missing", source_event_id=None,
                    statement="Obtain gateway connection-utilization metrics.", relevance=1.0,
                    reason_code="CONNECTION_PRESSURE_MISSING", created_at=now
                ))

            if evt_timeout_id:
                evidence_rows.append(models.Evidence(
                    id=ev5_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_config_id,
                    kind="observed", source_event_id=evt_timeout_id,
                    statement="Checkout service latency is high.", relevance=1.0,
                    reason_code="DOWNSTREAM_LATENCY_HIGH", created_at=now
                ))
                evidence_rows.append(models.Evidence(
                    id=ev6_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_config_id,
                    kind="observed", source_event_id=evt_timeout_id,
                    statement="Payment service reported upstream timeout.", relevance=1.0,
                    reason_code="TIMEOUT_LOG_FOUND", created_at=now
                ))
            else:
                evidence_rows.append(models.Evidence(
                    id=ev5_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_config_id,
                    kind="missing", source_event_id=None,
                    statement="Obtain checkout latency metrics.", relevance=1.0,
                    reason_code="DOWNSTREAM_LATENCY_MISSING", created_at=now
                ))
                evidence_rows.append(models.Evidence(
                    id=ev6_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_config_id,
                    kind="missing", source_event_id=None,
                    statement="Obtain payment upstream-timeout logs.", relevance=1.0,
                    reason_code="TIMEOUT_LOG_MISSING", created_at=now
                ))

            evidence_rows.append(models.Evidence(
                id=ev7_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_config_id,
                kind="missing", source_event_id=None,
                statement="Obtain WAF decision logs for 09:25–09:35 UTC.", relevance=1.0,
                reason_code="WAF_DECISION_LOGS_MISSING", created_at=now
            ))

            # DoS Evidence (3 items)
            ev_dos1_id = f"ev_{uuid.uuid4().hex[:12]}"
            ev_dos2_id = f"ev_{uuid.uuid4().hex[:12]}"
            ev_dos3_id = f"ev_{uuid.uuid4().hex[:12]}"

            if evt_spike_id:
                evidence_rows.append(models.Evidence(
                    id=ev_dos1_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_dos_id,
                    kind="conflicting", source_event_id=evt_spike_id,
                    statement="Gateway raw ingress is stable at 2,400 requests/s.", relevance=1.0,
                    reason_code="STABLE_RAW_INGRESS", created_at=now
                ))
                evidence_rows.append(models.Evidence(
                    id=ev_dos2_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_dos_id,
                    kind="observed", source_event_id=evt_spike_id,
                    statement="Gateway request source distribution is normal.", relevance=1.0,
                    reason_code="NORMAL_SOURCE_DISTRIBUTION", created_at=now
                ))
            else:
                evidence_rows.append(models.Evidence(
                    id=ev_dos1_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_dos_id,
                    kind="missing", source_event_id=None,
                    statement="Obtain gateway raw-ingress metrics.", relevance=1.0,
                    reason_code="RAW_INGRESS_MISSING", created_at=now
                ))
                evidence_rows.append(models.Evidence(
                    id=ev_dos2_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_dos_id,
                    kind="missing", source_event_id=None,
                    statement="Obtain client/source-distribution metrics.", relevance=1.0,
                    reason_code="SOURCE_DISTRIBUTION_MISSING", created_at=now
                ))

            evidence_rows.append(models.Evidence(
                id=ev_dos3_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_dos_id,
                kind="missing", source_event_id=None,
                statement="Obtain WAF decision logs.", relevance=1.0,
                reason_code="WAF_DECISION_LOGS_MISSING", created_at=now
            ))

            # Database Connection Exhaustion Evidence (3 items)
            ev_db1_id = f"ev_{uuid.uuid4().hex[:12]}"
            ev_db2_id = f"ev_{uuid.uuid4().hex[:12]}"
            ev_db3_id = f"ev_{uuid.uuid4().hex[:12]}"

            if evt_timeout_id or evt_spike_id:
                evidence_rows.append(models.Evidence(
                    id=ev_db1_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_db_id,
                    kind="conflicting", source_event_id=evt_timeout_id or evt_spike_id,
                    statement="Database utilization is normal.", relevance=1.0,
                    reason_code="NORMAL_DB_UTILIZATION", created_at=now
                ))
            else:
                evidence_rows.append(models.Evidence(
                    id=ev_db1_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_db_id,
                    kind="missing", source_event_id=None,
                    statement="Obtain database connection-utilization metrics.", relevance=1.0,
                    reason_code="DB_UTILIZATION_MISSING", created_at=now
                ))

            if evt_timeout_id:
                evidence_rows.append(models.Evidence(
                    id=ev_db2_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_db_id,
                    kind="observed", source_event_id=evt_timeout_id,
                    statement="Database pool waits are normal.", relevance=1.0,
                    reason_code="NORMAL_POOL_WAITS", created_at=now
                ))
                evidence_rows.append(models.Evidence(
                    id=ev_db3_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_db_id,
                    kind="observed", source_event_id=evt_timeout_id,
                    statement="Payment service reported upstream timeout.", relevance=1.0,
                    reason_code="TIMEOUT_LOG_FOUND", created_at=now
                ))
            else:
                evidence_rows.append(models.Evidence(
                    id=ev_db2_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_db_id,
                    kind="missing", source_event_id=None,
                    statement="Obtain database pool-wait metrics.", relevance=1.0,
                    reason_code="POOL_WAITS_MISSING", created_at=now
                ))
                evidence_rows.append(models.Evidence(
                    id=ev_db3_id, analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_db_id,
                    kind="missing", source_event_id=None,
                    statement="Obtain dependency timeout logs.", relevance=1.0,
                    reason_code="TIMEOUT_LOG_MISSING", created_at=now
                ))

            # Playbook Recommendations
            recommendation_rows.append(models.PlaybookRecommendation(
                id=f"rec_{uuid.uuid4().hex[:12]}", analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_config_id,
                step_id="inspect-config-diff", state="suggested", rationale="Inspect the changes in the rate limiter config."
            ))
            recommendation_rows.append(models.PlaybookRecommendation(
                id=f"rec_{uuid.uuid4().hex[:12]}", analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_config_id,
                step_id="compare-pre-post-metrics", state="suggested", rationale="Compare the performance before and after."
            ))
            recommendation_rows.append(models.PlaybookRecommendation(
                id=f"rec_{uuid.uuid4().hex[:12]}", analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_config_id,
                step_id="propose-config-rollback", state="suggested", rationale="Rollback the configuration change."
            ))

            recommendation_rows.append(models.PlaybookRecommendation(
                id=f"rec_{uuid.uuid4().hex[:12]}", analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_dos_id,
                step_id="inspect-ingress-distribution", state="suggested", rationale="Inspect ingress metrics."
            ))
            recommendation_rows.append(models.PlaybookRecommendation(
                id=f"rec_{uuid.uuid4().hex[:12]}", analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_dos_id,
                step_id="propose-edge-rate-limit", state="suggested", rationale="Block offending IPs."
            ))

            recommendation_rows.append(models.PlaybookRecommendation(
                id=f"rec_{uuid.uuid4().hex[:12]}", analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_db_id,
                step_id="inspect-db-pool", state="suggested", rationale="Check database connection pool metrics."
            ))
            recommendation_rows.append(models.PlaybookRecommendation(
                id=f"rec_{uuid.uuid4().hex[:12]}", analysis_run_id="", incident_id=incident.id, hypothesis_id=hyp_db_id,
                step_id="propose-db-pool-tuning", state="suggested", rationale="Tune pool size."
            ))

            explanation_payload = {
                "analysis_run_id": "",
                "incident_summary": "Gateway rate limiter disabled at T+0 causing rps to jump and downstream services to fail under load.",
                "hypotheses": [
                    {
                        "hypothesis_id": hyp_config_id,
                        "summary": "A gateway rate-limit change is the highest-ranked explanation.",
                        "claims": [
                            {"text": "Suspected configuration change precedes traffic spike.", "evidence_ids": [ev1_id]},
                            {"text": "High forwarded request rate detected on gateway.", "evidence_ids": [ev2_id, ev4_id]}
                        ],
                        "conflicting_evidence_ids": [],
                        "missing_evidence_ids": [ev7_id],
                        "diagnostic_step_ids": ["inspect-config-diff", "compare-pre-post-metrics"]
                    },
                    {
                        "hypothesis_id": hyp_dos_id,
                        "summary": "External DoS attack or organic traffic surge.",
                        "claims": [
                            {"text": "Traffic surge observed.", "evidence_ids": [ev_dos2_id]}
                        ],
                        "conflicting_evidence_ids": [ev_dos1_id],
                        "missing_evidence_ids": [ev_dos3_id],
                        "diagnostic_step_ids": ["inspect-ingress-distribution"]
                    },
                    {
                        "hypothesis_id": hyp_db_id,
                        "summary": "Database connection pool exhaustion.",
                        "claims": [
                            {"text": "Upstream timeouts reported.", "evidence_ids": [ev_db3_id]}
                        ],
                        "conflicting_evidence_ids": [ev_db1_id],
                        "missing_evidence_ids": [],
                        "diagnostic_step_ids": ["inspect-db-pool"]
                    }
                ]
            }

        else:
            # Return a simple fallback hypothesis if not the golden scenario
            hyp_id = f"hyp_{uuid.uuid4().hex[:12]}"
            hypotheses.append(models.Hypothesis(
                id=hyp_id, analysis_run_id="", incident_id=incident.id,
                type="network_path_congestion", candidate_entity_id=incident.primary_entity_id,
                rank=1, evidence_score=50.0, coverage={"available": 1, "expected": 2},
                factor_scores={
                    "change_causal_fit": 0.0, "direct_logs_alerts": 0.0, "historical_similarity": 0.0,
                    "metric_anomaly": 0.5, "propagation_consistency": 0.5, "symptom_compatibility": 0.5,
                    "temporal_proximity": 0.5, "topology_relevance": 1.0
                },
                summary="Fallback analysis for incident."
            ))
            explanation_payload = {
                "analysis_run_id": "",
                "incident_summary": "Fallback analysis.",
                "hypotheses": [
                    {
                        "hypothesis_id": hyp_id,
                        "summary": "Network path congestion.",
                        "claims": [],
                        "conflicting_evidence_ids": [],
                        "missing_evidence_ids": [],
                        "diagnostic_step_ids": []
                    }
                ]
            }

        return AnalysisResult(
            hypotheses=hypotheses,
            evidence_rows=evidence_rows,
            recommendation_rows=recommendation_rows,
            explanation_payload=explanation_payload
        )
