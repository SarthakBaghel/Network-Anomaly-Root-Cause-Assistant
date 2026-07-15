from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from app.contracts import (
    AnalysisRun,
    AnalysisRunStatus,
    EvidenceItem,
    EvidenceKind,
    ExplanationOutput,
    Hypothesis,
    PlaybookRecommendation,
)
from app.explanation import (
    ExplanationService,
    OllamaExplanationProvider,
    OllamaProviderError,
    build_structured_bundle,
    generate_template_explanation,
    validate_explanation_detailed,
)


NOW = datetime(2026, 7, 14, 9, 31, 41, tzinfo=timezone.utc)
FACTORS = {
    "symptom_compatibility": 1.0,
    "topology_relevance": 1.0,
    "direct_logs_alerts": 0.6,
    "propagation_consistency": 1.0,
    "metric_anomaly": 0.91,
    "change_causal_fit": 1.0,
    "temporal_proximity": 1.0,
    "historical_similarity": 0.5,
}


def _run() -> AnalysisRun:
    return AnalysisRun(
        analysis_run_id="run_007",
        incident_id="inc_001",
        revision=7,
        status="current",
        trigger_event_id="evt_001",
        input_fingerprint=f"sha256:{'a' * 64}",
        created_at=NOW,
        completed_at=NOW,
        algorithm_version="rca-rules-1.1",
    )


def _hypothesis() -> Hypothesis:
    return Hypothesis(
        hypothesis_id="hyp_001",
        analysis_run_id="run_007",
        incident_id="inc_001",
        hypothesis_type="configuration_regression",
        candidate_entity_id="api-gateway-01",
        rank=1,
        evidence_score=92.1,
        evidence_coverage={"available": 2, "expected": 3},
        factor_scores=FACTORS,
        summary="A gateway configuration regression best explains the incident.",
    )


def _evidence() -> list[EvidenceItem]:
    return [
        EvidenceItem(
            evidence_id="ev_001",
            analysis_run_id="run_007",
            incident_id="inc_001",
            hypothesis_id="hyp_001",
            kind=EvidenceKind.OBSERVED,
            source_event_id="evt_001",
            statement="Gateway forwarded request rate reached 7,800 requests/s.",
            relevance=0.95,
            reason_code="METRIC_THRESHOLD_EXCEEDED",
            created_at=NOW,
        ),
        EvidenceItem(
            evidence_id="ev_002",
            analysis_run_id="run_007",
            incident_id="inc_001",
            hypothesis_id="hyp_001",
            kind=EvidenceKind.MISSING,
            source_event_id=None,
            statement="Obtain WAF decision logs.",
            relevance=0.5,
            reason_code="MISSING_WAF_DECISION_LOGS",
            created_at=NOW,
        ),
    ]


def _recommendations() -> list[PlaybookRecommendation]:
    return [
        PlaybookRecommendation(
            recommendation_id="rec_001",
            analysis_run_id="run_007",
            incident_id="inc_001",
            hypothesis_id="hyp_001",
            step_id="inspect-config-diff",
            title="Inspect configuration diff",
            step_type="diagnostic",
            risk_level="low",
            requires_human_approval=True,
            instructions="Compare current and prior configuration.",
            rationale="Catalogue-backed diagnostic.",
        ),
        PlaybookRecommendation(
            recommendation_id="rec_002",
            analysis_run_id="run_007",
            incident_id="inc_001",
            hypothesis_id="hyp_001",
            step_id="propose-config-rollback",
            title="Propose configuration rollback",
            step_type="remediation",
            risk_level="low",
            requires_human_approval=True,
            instructions="Propose re-enabling the rate limiter.",
            rationale="Catalogue-backed remediation; never automatically executed.",
        ),
    ]


def _llm_payload(
    *,
    run_id: str = "run_007",
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "analysis_run_id": run_id,
        "incident_id": "inc_001",
        "hypothesis_id": "hyp_001",
        "generator": "llm",
        "summary": (
            "The probable root cause is a gateway configuration regression."
        ),
        "claims": [
            {
                "claim": "Forwarded traffic increased after the change.",
                "evidence_ids": evidence_ids or ["ev_001"],
            }
        ],
        "diagnostic_step_ids": ["inspect-config-diff"],
        "remediation_step_ids": ["propose-config-rollback"],
    }


class FakeProvider:
    def __init__(self, responses: list[Mapping[str, Any] | Exception]) -> None:
        self.responses = responses
        self.calls: list[Mapping[str, Any]] = []

    def generate(self, bundle: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append(bundle)
        response = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response


class FakeOllamaClient:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def chat(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"message": {"content": json.dumps(self.payload)}}


def test_template_is_valid_when_optional_inputs_are_absent() -> None:
    result = ExplanationService(mode="template").generate(
        _run(),
        _hypothesis(),
        [],
        [],
        candidate_entity_type="gateway",
    )

    assert result.explanation_fallback_reason is None
    assert len(result.explanation_rows) == 1
    output = result.explanation_rows[0].output
    assert ExplanationOutput.model_validate(output.model_dump(mode="json")) == output
    assert output.claims == []
    assert output.diagnostic_step_ids == []
    assert output.remediation_step_ids == []
    assert "probable root cause" in output.summary.lower()
    assert "confirmed" not in output.summary.lower()


def test_every_template_claim_has_an_existing_evidence_id() -> None:
    evidence = _evidence()
    output = generate_template_explanation(
        _hypothesis(), evidence, _recommendations()
    )

    existing_ids = {item.evidence_id for item in evidence}
    assert output.claims
    assert all(claim.evidence_ids for claim in output.claims)
    assert all(
        evidence_id in existing_ids
        for claim in output.claims
        for evidence_id in claim.evidence_ids
    )


def test_fabricated_evidence_id_retries_once_then_keeps_template() -> None:
    invalid = _llm_payload(evidence_ids=["ev_fabricated"])
    provider = FakeProvider([invalid, invalid])
    result = ExplanationService(mode="llm", optional_provider=provider).generate(
        _run(),
        _hypothesis(),
        _evidence(),
        _recommendations(),
        candidate_entity_type="gateway",
    )

    assert len(provider.calls) == 2
    assert [row.output.generator for row in result.explanation_rows] == ["template"]
    assert result.explanation_fallback_reason == "LLM_EVIDENCE_ID_NOT_FOUND"
    assert result.explanation_fallback_attempt_count == 2


def test_wrong_analysis_run_id_is_discarded_as_stale() -> None:
    provider = FakeProvider([_llm_payload(run_id="run_old")])
    result = ExplanationService(mode="llm", optional_provider=provider).generate(
        _run(),
        _hypothesis(),
        _evidence(),
        _recommendations(),
        candidate_entity_type="gateway",
    )

    assert len(provider.calls) == 1
    assert [row.output.generator for row in result.explanation_rows] == ["template"]
    assert result.explanation_fallback_reason == "LLM_RESULT_STALE"
    assert result.explanation_fallback_attempt_count == 1


def test_result_is_discarded_when_incident_pointer_becomes_stale() -> None:
    provider = FakeProvider([_llm_payload()])
    service = ExplanationService(
        mode="llm",
        optional_provider=provider,
        current_run_id_provider=lambda _incident_id: "run_newer",
    )
    result = service.generate(
        _run(),
        _hypothesis(),
        _evidence(),
        _recommendations(),
        candidate_entity_type="gateway",
    )

    assert len(provider.calls) == 1
    assert [row.output.generator for row in result.explanation_rows] == ["template"]
    assert result.explanation_fallback_reason == "LLM_RESULT_STALE"


def test_active_building_run_accepts_valid_llm_result() -> None:
    provider = FakeProvider([_llm_payload()])
    building_run = _run().model_copy(
        update={
            "status": AnalysisRunStatus.BUILDING,
            "completed_at": None,
        }
    )
    result = ExplanationService(mode="llm", optional_provider=provider).generate(
        building_run,
        _hypothesis(),
        _evidence(),
        _recommendations(),
        candidate_entity_type="gateway",
        current_run_id_provider=lambda _incident_id: building_run.analysis_run_id,
    )

    assert [row.output.generator for row in result.explanation_rows] == [
        "template",
        "llm",
    ]
    assert result.explanation_fallback_reason is None


def test_llm_generation_failure_retries_once_then_keeps_template() -> None:
    provider = FakeProvider([RuntimeError("offline"), RuntimeError("offline")])
    result = ExplanationService(mode="llm", optional_provider=provider).generate(
        _run(),
        _hypothesis(),
        _evidence(),
        _recommendations(),
        candidate_entity_type="gateway",
    )

    assert len(provider.calls) == 2
    assert [row.output.generator for row in result.explanation_rows] == ["template"]
    assert result.explanation_fallback_reason == "LLM_GENERATION_FAILED"
    assert result.explanation_fallback_attempt_count == 2


def test_valid_structured_provider_output_is_appended_not_replaced() -> None:
    provider = FakeProvider([_llm_payload()])
    result = ExplanationService(mode="llm", optional_provider=provider).generate(
        _run(),
        _hypothesis(),
        _evidence(),
        _recommendations(),
        candidate_entity_type="gateway",
    )

    assert [row.output.generator for row in result.explanation_rows] == [
        "template",
        "llm",
    ]
    assert result.explanation_fallback_reason is None
    assert set(provider.calls[0]) == {"hypothesis", "evidence", "recommendations"}
    assert "raw_payload" not in str(provider.calls[0])


def test_validator_rejects_score_override_and_unapproved_playbook_step() -> None:
    payload = _llm_payload()
    payload["evidence_score"] = 100.0
    invalid_schema = validate_explanation_detailed(
        payload,
        _run(),
        _hypothesis(),
        _evidence(),
        _recommendations(),
        candidate_entity_type="gateway",
        current_analysis_run_id="run_007",
        expected_generator="llm",
    )
    assert invalid_schema.reason_code == "SCHEMA_INVALID"

    payload = _llm_payload()
    payload["summary"] = "probable root cause"
    invalid_summary = validate_explanation_detailed(
        payload,
        _run(),
        _hypothesis(),
        _evidence(),
        _recommendations(),
        candidate_entity_type="gateway",
        current_analysis_run_id="run_007",
        expected_generator="llm",
    )
    assert invalid_summary.reason_code == "CAUSAL_WORDING_INVALID"

    payload = _llm_payload()
    payload["diagnostic_step_ids"] = ["invented-step"]
    invalid_step = validate_explanation_detailed(
        payload,
        _run(),
        _hypothesis(),
        _evidence(),
        _recommendations(),
        candidate_entity_type="gateway",
        current_analysis_run_id="run_007",
        expected_generator="llm",
    )
    assert invalid_step.reason_code == "PLAYBOOK_STEP_NOT_RECOMMENDED"


def test_structured_bundle_has_no_event_or_raw_log_field() -> None:
    bundle = build_structured_bundle(
        _hypothesis(), _evidence(), _recommendations()
    )

    assert set(bundle) == {"hypothesis", "evidence", "recommendations"}
    serialized = str(bundle).lower()
    assert "raw_payload" not in serialized
    assert "canonicalevent" not in serialized


def test_ollama_provider_sends_only_structured_schema_constrained_input() -> None:
    bundle = build_structured_bundle(
        _hypothesis(), _evidence(), _recommendations()
    )
    client = FakeOllamaClient(_llm_payload())
    provider = OllamaExplanationProvider(
        model="test-model",
        client=client,
    )

    result = provider.generate(bundle)

    assert result == _llm_payload()
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["model"] == "test-model"
    assert call["stream"] is False
    assert call["options"] == {"temperature": 0, "seed": 0}
    output_schema = call["format"]
    output_properties = output_schema["properties"]
    assert output_properties["analysis_run_id"]["const"] == "run_007"
    assert output_properties["incident_id"]["const"] == "inc_001"
    assert output_properties["hypothesis_id"]["const"] == "hyp_001"
    assert output_properties["generator"]["const"] == "llm"
    assert output_properties["summary"]["minLength"] == 60
    assert output_properties["summary"]["maxLength"] == 600
    assert output_properties["summary"]["pattern"] == (
        r"^The probable root cause is .+ affecting .+ because .+\.$"
    )
    assert set(
        output_schema["$defs"]["ExplanationClaim"]["properties"][
            "evidence_ids"
        ]["items"]["enum"]
    ) == {"ev_001", "ev_002"}
    assert output_properties["diagnostic_step_ids"]["items"]["enum"] == [
        "inspect-config-diff"
    ]
    assert output_properties["remediation_step_ids"]["items"]["enum"] == [
        "propose-config-rollback"
    ]
    assert json.loads(call["messages"][1]["content"]) == bundle
    assert "raw_payload" not in call["messages"][1]["content"].lower()
    assert "do not create evidence" in call["messages"][0]["content"].lower()


def test_ollama_provider_rejects_raw_fields_before_calling_client() -> None:
    client = FakeOllamaClient(_llm_payload())
    provider = OllamaExplanationProvider(client=client)
    unsafe = build_structured_bundle(
        _hypothesis(), _evidence(), _recommendations()
    )
    unsafe["hypothesis"]["raw_payload"] = {
        "message": "must not cross provider boundary"
    }

    try:
        provider.generate(unsafe)
    except OllamaProviderError as exc:
        assert "raw event or log fields" in str(exc)
    else:
        raise AssertionError("unsafe Ollama input was accepted")
    assert client.calls == []


def test_real_ollama_provider_output_still_passes_service_validator() -> None:
    client = FakeOllamaClient(_llm_payload())
    provider = OllamaExplanationProvider(client=client)

    result = ExplanationService(mode="llm", optional_provider=provider).generate(
        _run(),
        _hypothesis(),
        _evidence(),
        _recommendations(),
        candidate_entity_type="gateway",
    )

    assert [row.output.generator for row in result.explanation_rows] == [
        "template",
        "llm",
    ]
    assert result.explanation_fallback_reason is None
