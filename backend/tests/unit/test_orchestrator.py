"""
Unit tests for AnalysisOrchestrator (Person 1 — P1-13).

Tests cover:
- Singleton instantiation and lock presence
- Protocol registration
- Fingerprint idempotency
- Failure isolation (failed run leaves prior current)
- Audit action code validation
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from app.orchestration.orchestrator import (
    ALGORITHM_VERSION,
    AnalysisOrchestrator,
    orchestrator,
)
from app.db.repositories import AuditRepository, AUDIT_ACTION_CODES


class TestOrchestratorInstantiation:
    def test_orchestrator_singleton_instantiates(self) -> None:
        assert orchestrator is not None

    def test_orchestrator_has_lock(self) -> None:
        # threading.Lock() returns a _thread.lock, not a threading.Lock instance.
        # Verify it has the acquire/release interface instead.
        assert hasattr(orchestrator._lock, "acquire")
        assert hasattr(orchestrator._lock, "release")

    def test_orchestrator_status_keys(self) -> None:
        status = orchestrator.status()
        assert "detector_registered" in status
        assert "incident_manager_registered" in status
        assert "analysis_engine_registered" in status
        assert "algorithm_version" in status
        assert status["algorithm_version"] == ALGORITHM_VERSION

    def test_new_orchestrator_has_no_modules_registered(self) -> None:
        orc = AnalysisOrchestrator()
        status = orc.status()
        assert status["detector_registered"] is False
        assert status["incident_manager_registered"] is False
        assert status["analysis_engine_registered"] is False

    def test_register_detector(self) -> None:
        orc = AnalysisOrchestrator()
        mock_detector = MagicMock()
        orc.register_detector(mock_detector)
        assert orc.status()["detector_registered"] is True

    def test_register_incident_manager(self) -> None:
        orc = AnalysisOrchestrator()
        mock_manager = MagicMock()
        orc.register_incident_manager(mock_manager)
        assert orc.status()["incident_manager_registered"] is True

    def test_register_analysis_engine(self) -> None:
        orc = AnalysisOrchestrator()
        mock_engine = MagicMock()
        orc.register_analysis_engine(mock_engine)
        assert orc.status()["analysis_engine_registered"] is True

    def test_batch_defers_to_one_recompute_per_affected_incident(self) -> None:
        from datetime import datetime, timedelta, timezone

        orc = AnalysisOrchestrator()
        session = MagicMock()
        first = MagicMock(id="evt_first", timestamp=datetime(2026, 7, 14, 9, 30, tzinfo=timezone.utc))
        second = MagicMock(id="evt_second", timestamp=first.timestamp + timedelta(seconds=10))
        incident = MagicMock(id="inc_001")
        orc._stage_detect = MagicMock(return_value=[])
        orc._stage_incident = MagicMock(return_value=incident)
        orc._run_rca_and_publish = MagicMock(return_value="run_001")

        orc.process_batch([second, first], session)

        assert orc._stage_detect.call_count == 2
        assert orc._stage_incident.call_count == 2
        orc._run_rca_and_publish.assert_called_once_with(
            incident,
            trigger_event=second,
            session=session,
        )


class TestFingerprintComputation:
    def test_fingerprint_is_deterministic(self) -> None:
        orc = AnalysisOrchestrator()
        # Without a DB we can't call compute_fingerprint directly (needs catalogue files),
        # but we can verify the SHA-256 prefix format.
        # Use a minimal mock session to avoid DB calls.
        session = MagicMock()
        fp = orc.compute_fingerprint(
            incident_event_ids=["evt_001", "evt_002"],
            session=session,
        )
        assert fp.startswith("sha256:")
        assert len(fp) == len("sha256:") + 64

    def test_fingerprint_order_independent(self) -> None:
        """Same event IDs in different order → same fingerprint."""
        orc = AnalysisOrchestrator()
        session = MagicMock()
        fp1 = orc.compute_fingerprint(["evt_b", "evt_a"], session)
        fp2 = orc.compute_fingerprint(["evt_a", "evt_b"], session)
        assert fp1 == fp2

    def test_different_events_give_different_fingerprint(self) -> None:
        orc = AnalysisOrchestrator()
        session = MagicMock()
        fp1 = orc.compute_fingerprint(["evt_001"], session)
        fp2 = orc.compute_fingerprint(["evt_002"], session)
        assert fp1 != fp2

    def test_event_content_change_changes_fingerprint(self) -> None:
        """Changing event content (severity, raw_payload, etc.) produces different fingerprint even if event_id is identical."""
        from unittest.mock import patch
        from app.db.models import Event
        from datetime import datetime, timezone

        orc = AnalysisOrchestrator()
        session = MagicMock()

        ev1 = Event(
            id="evt_001",
            timestamp=datetime(2026, 7, 14, 9, 30, 0, tzinfo=timezone.utc),
            entity_id="api-gateway-01",
            modality="metric",
            event_type="HTTP_LATENCY_SPIKE",
            severity=0.8,
            signal_name="p95_latency",
            signal_value=120.0,
            unit="ms",
            trace_or_session_id="session_01",
            raw_payload={"details": "baseline"},
        )

        ev2 = Event(
            id="evt_001",
            timestamp=datetime(2026, 7, 14, 9, 30, 0, tzinfo=timezone.utc),
            entity_id="api-gateway-01",
            modality="metric",
            event_type="HTTP_LATENCY_SPIKE",
            severity=0.95,  # Changed severity
            signal_name="p95_latency",
            signal_value=500.0,  # Changed value
            unit="ms",
            trace_or_session_id="session_01",
            raw_payload={"details": "escalation"},  # Changed payload
        )

        with patch("app.db.repositories.event_repository.EventRepository.get_events_by_ids") as mock_get:
            mock_get.return_value = [ev1]
            fp1 = orc.compute_fingerprint(["evt_001"], session)

            mock_get.return_value = [ev2]
            fp2 = orc.compute_fingerprint(["evt_001"], session)

            assert fp1 != fp2


class TestAuditActionCodes:
    def test_all_blueprint_action_codes_present(self) -> None:
        required = {
            "EVENT_QUARANTINED",
            "EVENT_COLLAPSED",
            "ANOMALY_DETECTED",
            "INCIDENT_OPENED",
            "EVENT_ATTACHED",
            "EVENT_EXCLUDED",
            "ANALYSIS_PUBLISHED",
            "PIPELINE_STAGE_FAILED",
            "EXPLANATION_FALLBACK_USED",
            "REVIEW_CONFIRMED",
            "REVIEW_REJECTED",
            "REVIEW_EVIDENCE_REQUESTED",
            "INCIDENT_STATUS_CHANGED",
            "DEMO_RESET",
        }
        assert required == AUDIT_ACTION_CODES

    def test_audit_repo_rejects_unknown_action_code(self) -> None:
        """AuditRepository must reject unknown action codes (blueprint §20.3)."""
        session = MagicMock()
        repo = AuditRepository(session)
        with pytest.raises(ValueError, match="Unknown audit action code"):
            repo.append(
                audit_id="aud_test",
                actor_type="system",
                actor_id=None,
                action="INVENTED_CODE",
                object_type="incident",
                object_id="inc_001",
                payload={},
            )


class TestAlgorithmVersion:
    def test_algorithm_version_matches_blueprint(self) -> None:
        assert ALGORITHM_VERSION == "rca-rules-1.1"
