from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import simulator as simulator_api
from app.db import models
from app.db import session as db_session
from app.main import app
from app.orchestration import reset_service
from app.orchestration.orchestrator import orchestrator
from app.simulator.engine import SimulatorEngine


SCENARIO_ID = "scenario_gateway_rate_limit_001"


@contextmanager
def _production_client(
    monkeypatch,
    *,
    raise_server_exceptions: bool = False,
) -> Iterator[tuple[TestClient, sessionmaker]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=Session,
    )
    simulator = SimulatorEngine(background=False)
    old_components = (
        orchestrator._detector,
        orchestrator._incident_manager,
        orchestrator._analysis_engine,
        reset_service._simulator_hook,
    )
    monkeypatch.setattr(db_session, "SessionLocal", session_factory)
    monkeypatch.setattr(simulator_api, "simulator_engine", simulator)
    try:
        with TestClient(app, raise_server_exceptions=raise_server_exceptions) as client:
            yield client, session_factory
    finally:
        (
            orchestrator._detector,
            orchestrator._incident_manager,
            orchestrator._analysis_engine,
            reset_service._simulator_hook,
        ) = old_components
        engine.dispose()


def _replay(client: TestClient) -> tuple[str, dict]:
    reset = client.post("/api/v1/simulator/reset")
    assert reset.status_code == 200, reset.text
    start = client.post("/api/v1/simulator/start")
    assert start.status_code == 200, start.text
    simulator_api.simulator_engine.complete_baseline()
    trigger = client.post(f"/api/v1/simulator/scenarios/{SCENARIO_ID}/trigger")
    assert trigger.status_code == 200, trigger.text
    incidents = client.get("/api/v1/incidents")
    assert incidents.status_code == 200
    items = incidents.json()["items"]
    assert len(items) == 1
    incident_id = items[0]["incident_id"]
    investigation = client.get(f"/api/v1/incidents/{incident_id}/investigation")
    assert investigation.status_code == 200, investigation.text
    return incident_id, investigation.json()


def _semantic_projection(payload: dict) -> dict:
    type_by_id = {item["hypothesis_id"]: item["hypothesis_type"] for item in payload["hypotheses"]}
    return {
        "incident": {
            "title": payload["incident"]["title"],
            "status": payload["incident"]["status"],
            "severity": payload["incident"]["severity"],
            "primary_entity_id": payload["incident"]["primary_entity_id"],
            "affected_entity_ids": payload["incident"]["affected_entity_ids"],
            "anomaly_count": payload["incident"]["anomaly_count"],
        },
        "timeline": [
            (
                item["event"]["source_record_id"],
                item["attachment_decision"],
                item["attachment_score"],
                item["attachment_reasons"],
            )
            for item in payload["timeline"]
        ],
        "hypotheses": [
            (
                item["hypothesis_type"],
                item["candidate_entity_id"],
                item["rank"],
                item["evidence_score"],
                item["evidence_coverage"],
                item["factor_scores"],
            )
            for item in payload["hypotheses"]
        ],
        "evidence": {
            type_by_id[hypothesis_id]: sorted(
                (item["kind"], item["reason_code"]) for item in evidence
            )
            for hypothesis_id, evidence in payload["evidence_by_hypothesis"].items()
        },
        "recommendations": {
            type_by_id[hypothesis_id]: [item["step_id"] for item in rows]
            for hypothesis_id, rows in payload["recommendations_by_hypothesis"].items()
        },
        "topology": {
            "nodes": [(item["id"], item["state"]) for item in payload["topology"]["nodes"]],
            "edges": [
                (
                    item["source"],
                    item["target"],
                    item["relation_type"],
                    item["state"],
                )
                for item in payload["topology"]["edges"]
            ],
        },
        "explanation": {
            "generator": payload["explanation"]["generator"],
            "summary": payload["explanation"]["summary"],
            # Evidence IDs are intentionally run-scoped; claim text/order is
            # the deterministic semantic contract across reset/replay.
            "claims": [item["claim"] for item in payload["explanation"]["claims"]],
            "diagnostic_step_ids": payload["explanation"]["diagnostic_step_ids"],
            "remediation_step_ids": payload["explanation"]["remediation_step_ids"],
        },
    }


def _assert_one_run(payload: dict) -> None:
    run_id = payload["analysis_run_id"]
    assert payload["analysis_run"]["analysis_run_id"] == run_id
    assert payload["incident"]["current_analysis_run_id"] == run_id
    assert all(item["analysis_run_id"] == run_id for item in payload["hypotheses"])
    assert all(
        item["analysis_run_id"] == run_id
        for rows in payload["evidence_by_hypothesis"].values()
        for item in rows
    )
    assert all(
        item["analysis_run_id"] == run_id
        for rows in payload["recommendations_by_hypothesis"].values()
        for item in rows
    )
    assert payload["explanation"]["analysis_run_id"] == run_id


def test_production_reset_replay_is_deterministic_and_run_consistent(
    monkeypatch,
) -> None:
    with _production_client(monkeypatch) as (client, session_factory):
        first_incident_id, first = _replay(client)
        second_incident_id, second = _replay(client)

        _assert_one_run(first)
        _assert_one_run(second)
        assert _semantic_projection(first) == _semantic_projection(second)
        assert first_incident_id != second_incident_id

        # Nine primary detector findings plus six independent EWMA
        # corroborations over the same metric events.
        assert first["incident"]["anomaly_count"] == 15
        assert len(first["timeline"]) == 13
        decisions = {
            item["event"]["source_record_id"]: item["attachment_decision"]
            for item in first["timeline"]
        }
        assert decisions["prom-raw_ingress_requests_per_second-0241"] == "attached"
        assert decisions["log-auth-certificate-0001"] == "excluded"
        assert [item["evidence_score"] for item in first["hypotheses"]] == [
            92.1,
            65.6,
            41.5,
        ]
        conflicts = {
            item["reason_code"]
            for rows in first["evidence_by_hypothesis"].values()
            for item in rows
            if item["kind"] == "conflicting"
        }
        assert {"STABLE_RAW_INGRESS", "NORMAL_DB_UTILIZATION"} <= conflicts

        with session_factory() as session:
            run = session.get(models.AnalysisRun, second["analysis_run_id"])
            assert run is not None
            assert run.typed_paths == {
                "configuration_traffic_impact": [
                    "api-gateway-01",
                    "checkout-api-01",
                    "payment-api-01",
                ],
                "database_dependency": [
                    "checkout-api-01",
                    "payment-api-01",
                    "payment-db-01",
                ],
            }
            assert set(run.conflict_reason_codes) == {
                "STABLE_RAW_INGRESS",
                "NORMAL_DB_UTILIZATION",
            }
            assert run.topology_states["nodes"]
            assert set(run.evidence_requirements) == {
                "configuration_regression",
                "dos_or_traffic_surge",
                "database_connection_exhaustion",
            }


@pytest.mark.parametrize(
    ("scenario_id", "expected_hypothesis_type"),
    [
        ("database_connection_pool_exhaustion", "database_connection_exhaustion"),
        ("network_path_congestion", "network_path_congestion"),
        ("ddos_syn_flood", "dos_or_traffic_surge"),
        ("gaia_resource_saturation", "resource_saturation"),
        ("port_scan_reconnaissance", "external_probe"),
        ("hdfs_datanode_failure", "distributed_storage_node_failure"),
        ("trace_anomaly", "trace_latency_regression"),
        ("dns_resolution_failure", "dns_resolution_failure"),
        ("tls_certificate_failure", "certificate_or_tls_failure"),
    ],
)
def test_additional_catalogue_scenarios_publish_matching_rca(
    monkeypatch,
    scenario_id: str,
    expected_hypothesis_type: str,
) -> None:
    with _production_client(monkeypatch, raise_server_exceptions=True) as (
        client,
        _session_factory,
    ):
        assert client.post("/api/v1/simulator/reset").status_code == 200
        assert client.post("/api/v1/simulator/start").status_code == 200
        simulator_api.simulator_engine.complete_baseline()
        trigger = client.post(f"/api/v1/simulator/scenarios/{scenario_id}/trigger")
        assert trigger.status_code == 200, trigger.text

        incidents = client.get("/api/v1/incidents").json()["items"]
        assert incidents
        investigation = client.get(f"/api/v1/incidents/{incidents[0]['incident_id']}/investigation")
        assert investigation.status_code == 200, investigation.text
        payload = investigation.json()
        hypothesis_types = {item["hypothesis_type"] for item in payload["hypotheses"]}
        assert expected_hypothesis_type in hypothesis_types
        assert (
            min(payload["hypotheses"], key=lambda item: item["rank"])["hypothesis_type"]
            == expected_hypothesis_type
        )

        with _session_factory() as session:
            assert session.scalar(select(func.count()).select_from(models.QuarantinedEvent)) == 0


class _FailingAnalysisEngine:
    def analyse(self, incident, session, context):
        raise RuntimeError("injected production publication failure")


def test_failed_publication_and_audit_are_durable(monkeypatch) -> None:
    with _production_client(monkeypatch) as (client, session_factory):
        incident_id, payload = _replay(client)
        prior_run_id = payload["analysis_run_id"]
        with session_factory() as session:
            membership = session.scalar(
                select(models.IncidentEvent).where(models.IncidentEvent.incident_id == incident_id)
            )
            assert membership is not None
            event = session.get(models.Event, membership.event_id)
            assert event is not None
            event.raw_payload = {**event.raw_payload, "force_new_revision": True}
            session.commit()

        old_engine = orchestrator._analysis_engine
        orchestrator.register_analysis_engine(_FailingAnalysisEngine())
        try:
            response = client.post(f"/api/v1/incidents/{incident_id}/recompute")
        finally:
            orchestrator._analysis_engine = old_engine
        assert response.status_code == 500

        with session_factory() as session:
            incident = session.get(models.Incident, incident_id)
            assert incident is not None
            assert incident.current_analysis_run_id == prior_run_id
            failed = session.scalar(
                select(models.AnalysisRun).where(
                    models.AnalysisRun.incident_id == incident_id,
                    models.AnalysisRun.status == "failed",
                )
            )
            assert failed is not None
            assert failed.failure_reason
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(models.Hypothesis)
                    .where(models.Hypothesis.analysis_run_id == failed.id)
                )
                == 0
            )
            audit = session.scalar(
                select(models.AuditLog).where(
                    models.AuditLog.action == "PIPELINE_STAGE_FAILED",
                    models.AuditLog.object_id == incident_id,
                )
            )
            assert audit is not None
            assert audit.payload["analysis_run_id"] == failed.id


class _FailingResetSimulator(SimulatorEngine):
    def reset_state(self) -> None:
        raise RuntimeError("injected simulator reset failure")


def test_reset_hook_failure_rolls_back_database_reset(monkeypatch) -> None:
    with _production_client(monkeypatch) as (client, session_factory):
        incident_id, payload = _replay(client)
        original_simulator = simulator_api.simulator_engine
        simulator_api.simulator_engine = _FailingResetSimulator(background=False)
        try:
            response = client.post("/api/v1/simulator/reset")
        finally:
            simulator_api.simulator_engine = original_simulator
            reset_service.register_simulator(original_simulator)
        assert response.status_code == 500

        with session_factory() as session:
            incident = session.get(models.Incident, incident_id)
            assert incident is not None
            assert incident.current_analysis_run_id == payload["analysis_run_id"]
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(models.AuditLog)
                    .where(models.AuditLog.action == "DEMO_RESET")
                )
                == 1
            )
