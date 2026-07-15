from __future__ import annotations

import argparse
import json
import sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
BACKEND_FIXTURES = BACKEND / "tests" / "fixtures"
FRONTEND_FIXTURES = ROOT / "frontend" / "src" / "test-fixtures"
sys.path.insert(0, str(BACKEND))

from app.api import simulator as simulator_api  # noqa: E402
from app.db import models  # noqa: E402
from app.db import session as db_session  # noqa: E402
from app.main import app  # noqa: E402
from app.incidents.manager import serialize_incident_bundle  # noqa: E402
from app.orchestration import reset_service  # noqa: E402
from app.orchestration.orchestrator import orchestrator  # noqa: E402
from app.rca import WEIGHT_VALUES  # noqa: E402
from app.simulator.engine import SimulatorEngine  # noqa: E402


SCENARIO_ID = "gateway_rate_limit_disabled"
GOLDEN_INCIDENT_ID = "inc_001"
GOLDEN_RUN_ID = "run_007"
GOLDEN_GENERATED_AT = "2026-07-14T09:31:41.500Z"
GOLDEN_CREATED_AT = "2026-07-14T09:31:41.000Z"
GOLDEN_COMPLETED_AT = "2026-07-14T09:31:41.320Z"


def pretty(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _expect(response, status_code: int = 200) -> dict[str, Any]:
    if response.status_code != status_code:
        raise RuntimeError(
            f"production request failed ({response.status_code}): {response.text}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("production request did not return an object")
    return payload


@contextmanager
def _production_client() -> Iterator[tuple[TestClient, sessionmaker]]:
    """Run the real application pipeline against an isolated in-memory database."""

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
    old_session_factory = db_session.SessionLocal
    old_simulator = simulator_api.simulator_engine
    old_components = (
        orchestrator._detector,
        orchestrator._incident_manager,
        orchestrator._analysis_engine,
        reset_service._simulator_hook,
    )
    db_session.SessionLocal = session_factory
    simulator_api.simulator_engine = simulator
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, session_factory
    finally:
        db_session.SessionLocal = old_session_factory
        simulator_api.simulator_engine = old_simulator
        (
            orchestrator._detector,
            orchestrator._incident_manager,
            orchestrator._analysis_engine,
            reset_service._simulator_hook,
        ) = old_components
        engine.dispose()


def _production_snapshot() -> dict[str, Any]:
    """Reset and replay through production routes, then collect actual handoffs."""

    with _production_client() as (client, session_factory):
        _expect(client.post("/api/v1/simulator/reset"))
        _expect(client.post(f"/api/v1/simulator/scenarios/{SCENARIO_ID}/trigger"))

        incident_list = _expect(client.get("/api/v1/incidents"))
        incidents = incident_list.get("items", [])
        if len(incidents) != 1:
            raise RuntimeError(
                f"production replay must create exactly one incident, got {len(incidents)}"
            )
        incident_id = incidents[0]["incident_id"]
        investigation = _expect(
            client.get(f"/api/v1/incidents/{incident_id}/investigation")
        )
        run_id = investigation["analysis_run_id"]

        events: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": 200}
            if cursor is not None:
                params["cursor"] = cursor
            events_envelope = _expect(client.get("/api/v1/events", params=params))
            page = events_envelope.get("items", [])
            if not isinstance(page, list):
                raise RuntimeError("production events response contains a non-list page")
            events.extend(page)
            cursor = events_envelope.get("next_cursor")
            if cursor is None:
                break
        if not events:
            raise RuntimeError("production replay returned no events")
        events.sort(key=lambda item: (item["timestamp"], item["event_id"]))

        with session_factory() as session:
            run = session.get(models.AnalysisRun, run_id)
            if run is None:
                raise RuntimeError("published production analysis run is missing")
            incident_bundle = serialize_incident_bundle(session, incident_id)
            run_metadata = {
                "typed_paths": deepcopy(run.typed_paths),
                "conflict_reason_codes": list(run.conflict_reason_codes),
                "evidence_requirements": deepcopy(run.evidence_requirements),
            }

        top_hypothesis = min(investigation["hypotheses"], key=lambda item: item["rank"])
        review_envelope = _expect(
            client.post(
                f"/api/v1/incidents/{incident_id}/review",
                json={
                    "analysis_run_id": run_id,
                    "hypothesis_id": top_hypothesis["hypothesis_id"],
                    "decision": "confirmed",
                    "client_action_id": "golden-review-action-001",
                    "reviewer": "team-demo-user",
                    "comment": "Confirmed from the production-generated golden replay.",
                },
            )
        )
        audit = client.get(f"/api/v1/incidents/{incident_id}/audit")
        if audit.status_code != 200 or not isinstance(audit.json(), list):
            raise RuntimeError(f"production audit request failed: {audit.text}")

        return {
            "investigation": investigation,
            "incident_bundle": incident_bundle,
            "events": events,
            "run_metadata": run_metadata,
            "review": review_envelope["review"],
            "audit": audit.json(),
        }


def _id_mapping(investigation: dict[str, Any], review: dict[str, Any], audit: list[dict[str, Any]]) -> dict[str, str]:
    mapping = {
        investigation["incident"]["incident_id"]: GOLDEN_INCIDENT_ID,
        investigation["analysis_run_id"]: GOLDEN_RUN_ID,
    }
    hypotheses = sorted(investigation["hypotheses"], key=lambda item: item["rank"])
    for index, hypothesis in enumerate(hypotheses, 1):
        mapping[hypothesis["hypothesis_id"]] = f"hyp_{index:03d}"

    evidence_index = 1
    recommendation_index = 1
    for hypothesis in hypotheses:
        hypothesis_id = hypothesis["hypothesis_id"]
        for item in investigation["evidence_by_hypothesis"][hypothesis_id]:
            mapping[item["evidence_id"]] = f"ev_{evidence_index:03d}"
            evidence_index += 1
        for item in investigation["recommendations_by_hypothesis"][hypothesis_id]:
            mapping[item["recommendation_id"]] = f"rec_{recommendation_index:03d}"
            recommendation_index += 1

    mapping[review["review_id"]] = "rev_001"
    return mapping


def _replace_ids(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {
            mapping.get(str(key), str(key)): _replace_ids(item, mapping)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_ids(item, mapping) for item in value]
    if isinstance(value, str):
        replaced = value
        for runtime_id, golden_id in sorted(
            mapping.items(), key=lambda item: len(item[0]), reverse=True
        ):
            replaced = replaced.replace(runtime_id, golden_id)
        return replaced
    return value


def _normalize_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    mapping = _id_mapping(
        snapshot["investigation"], snapshot["review"], snapshot["audit"]
    )
    normalized = _replace_ids(deepcopy(snapshot), mapping)
    investigation = normalized["investigation"]
    investigation["generated_at"] = GOLDEN_GENERATED_AT
    investigation["analysis_run"]["created_at"] = GOLDEN_CREATED_AT
    investigation["analysis_run"]["completed_at"] = GOLDEN_COMPLETED_AT
    for rows in investigation["evidence_by_hypothesis"].values():
        for item in rows:
            item["created_at"] = GOLDEN_CREATED_AT
    normalized["review"]["created_at"] = "2026-07-14T09:32:30.000Z"
    return normalized


def _expected_analysis(investigation: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "version": "golden-expected-analysis-1.0",
        "analysis_run_id": investigation["analysis_run_id"],
        "incident_id": investigation["incident"]["incident_id"],
        "algorithm_version": investigation["analysis_run"]["algorithm_version"],
        "weights": WEIGHT_VALUES,
        "hypotheses": investigation["hypotheses"],
        "typed_paths": metadata["typed_paths"],
        "conflict_reason_codes": metadata["conflict_reason_codes"],
    }


def _phase3_seed(investigation: dict[str, Any]) -> dict[str, Any]:
    top_hypothesis_id = min(
        investigation["hypotheses"], key=lambda item: item["rank"]
    )["hypothesis_id"]
    evidence = sorted(
        investigation["evidence_by_hypothesis"][top_hypothesis_id],
        key=lambda item: item["evidence_id"],
    )
    missing = next(item for item in evidence if item["kind"] == "missing")
    non_missing = next(item for item in evidence if item["kind"] != "missing")
    excluded = next(
        item for item in investigation["timeline"] if item["attachment_decision"] == "excluded"
    )
    return {
        "incident_id": investigation["incident"]["incident_id"],
        "current_analysis_run_id": investigation["analysis_run_id"],
        "current_hypothesis_ids": [item["hypothesis_id"] for item in investigation["hypotheses"]],
        "excluded_event_id": excluded["event"]["event_id"],
        "initial_review_ids": [],
        "missing_evidence_id": missing["evidence_id"],
        "non_missing_evidence_id": non_missing["evidence_id"],
        "superseded_analysis_run_id": "run_006",
        "superseded_hypothesis_id": "hyp_old",
    }


def build_outputs() -> dict[Path, str]:
    snapshot = _normalize_snapshot(_production_snapshot())
    investigation = snapshot["investigation"]
    review = snapshot["review"]
    audit_order = {
        "EVENT_EXCLUDED": 1,
        "ANALYSIS_PUBLISHED": 2,
        "REVIEW_CONFIRMED": 3,
    }
    audit = sorted(
        (
            item
            for item in snapshot["audit"]
            if item["action"] in audit_order
            and (
                item["action"] != "ANALYSIS_PUBLISHED"
                or item["analysis_run_id"] == GOLDEN_RUN_ID
            )
        ),
        key=lambda item: (audit_order[item["action"]], item["object_id"]),
    )
    for index, item in enumerate(audit, 1):
        item["audit_id"] = f"audit_{index:03d}"
        item["timestamp"] = f"2026-07-14T09:32:{index:02d}.000Z"
        if item["action"] == "ANALYSIS_PUBLISHED":
            item["payload"]["prior_run_id"] = "run_006"
        if item["action"] == "REVIEW_CONFIRMED":
            item["request_id"] = "req_golden_review_001"
            item["payload"]["request_id"] = "req_golden_review_001"
    if [item["evidence_score"] for item in investigation["hypotheses"]] != [92.1, 65.6, 41.5]:
        raise RuntimeError("production replay no longer reproduces the approved RCA scores")
    if investigation["incident"]["anomaly_count"] != 9:
        raise RuntimeError("production replay no longer reproduces nine actionable anomalies")

    review_examples = {
        "schema_version": "1.0",
        "version": "review-examples-1.0",
        "records": [review],
    }
    audit_examples = {
        "schema_version": "1.0",
        "version": "audit-examples-1.0",
        "records": audit,
    }
    return {
        BACKEND_FIXTURES / "golden_expected_analysis.json": pretty(
            _expected_analysis(investigation, snapshot["run_metadata"])
        ),
        BACKEND_FIXTURES / "golden_incident_bundle.json": pretty(
            snapshot["incident_bundle"]
        ),
        BACKEND_FIXTURES / "golden_investigation_response.json": pretty(investigation),
        BACKEND_FIXTURES / "golden_review_examples.json": pretty(review_examples),
        BACKEND_FIXTURES / "golden_audit_examples.json": pretty(audit_examples),
        BACKEND_FIXTURES / "phase3_review_seed.json": pretty(
            _phase3_seed(investigation)
        ),
        FRONTEND_FIXTURES / "golden-investigation-response.json": pretty(investigation),
        FRONTEND_FIXTURES / "golden-events.json": pretty(snapshot["events"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate normalized handoff artifacts from a real production replay."
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = build_outputs()
    stale: list[str] = []
    for path, content in outputs.items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    if stale:
        raise SystemExit("production-generated handoff artifacts are stale: " + ", ".join(stale))
    print(
        f"{'validated' if args.check else 'generated'} {len(outputs)} "
        "handoff artifacts from production replay"
    )


if __name__ == "__main__":
    main()
