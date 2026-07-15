"""Strict backend validation for deterministic and optional explanations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.contracts import (
    AnalysisRun,
    AnalysisRunStatus,
    EvidenceItem,
    ExplanationOutput,
    Hypothesis,
)
from app.playbooks.engine import get_step

from .template_engine import RecommendationLike


@dataclass(frozen=True)
class ExplanationValidationResult:
    output: ExplanationOutput | None
    reason_code: str | None = None

    @property
    def valid(self) -> bool:
        return self.output is not None


def _invalid(reason_code: str) -> ExplanationValidationResult:
    return ExplanationValidationResult(output=None, reason_code=reason_code)


def validate_explanation_detailed(
    output: Mapping[str, Any] | ExplanationOutput,
    run: AnalysisRun,
    hypothesis: Hypothesis,
    evidence: Sequence[EvidenceItem],
    recommendations: Sequence[RecommendationLike],
    *,
    candidate_entity_type: str | None,
    current_analysis_run_id: str | None,
    require_current: bool = True,
    expected_generator: str | None = None,
) -> ExplanationValidationResult:
    """Validate one explanation without raising or changing deterministic data."""

    try:
        parsed = (
            output
            if isinstance(output, ExplanationOutput)
            else ExplanationOutput.model_validate(output)
        )
    except (TypeError, ValidationError, ValueError):
        return _invalid("SCHEMA_INVALID")

    if expected_generator is not None and parsed.generator != expected_generator:
        return _invalid("GENERATOR_MISMATCH")
    if parsed.analysis_run_id != run.analysis_run_id:
        return _invalid("RUN_ID_MISMATCH")
    if parsed.incident_id != run.incident_id:
        return _invalid("INCIDENT_ID_MISMATCH")
    if hypothesis.analysis_run_id != run.analysis_run_id:
        return _invalid("HYPOTHESIS_RUN_MISMATCH")
    if hypothesis.incident_id != run.incident_id:
        return _invalid("HYPOTHESIS_INCIDENT_MISMATCH")
    if parsed.hypothesis_id != hypothesis.hypothesis_id:
        return _invalid("HYPOTHESIS_ID_MISMATCH")
    if require_current and (
        run.status is not AnalysisRunStatus.CURRENT
        or current_analysis_run_id != run.analysis_run_id
    ):
        return _invalid("STALE_ANALYSIS_RUN")
    if "probable root cause" not in parsed.summary.lower():
        return _invalid("CAUSAL_WORDING_INVALID")
    if "confirmed" in parsed.summary.lower():
        return _invalid("CAUSAL_WORDING_INVALID")

    evidence_by_id = {item.evidence_id: item for item in evidence}
    for claim in parsed.claims:
        if not claim.evidence_ids:
            return _invalid("CLAIM_WITHOUT_EVIDENCE")
        for evidence_id in claim.evidence_ids:
            item = evidence_by_id.get(evidence_id)
            if item is None:
                return _invalid("EVIDENCE_ID_NOT_FOUND")
            if (
                item.analysis_run_id != run.analysis_run_id
                or item.incident_id != run.incident_id
                or item.hypothesis_id != hypothesis.hypothesis_id
            ):
                return _invalid("EVIDENCE_SCOPE_MISMATCH")

    recommended_ids = {item.step_id for item in recommendations}
    classified_steps = (
        (parsed.diagnostic_step_ids, "diagnostic"),
        (parsed.remediation_step_ids, "remediation"),
    )
    for step_ids, expected_type in classified_steps:
        if len(step_ids) != len(set(step_ids)):
            return _invalid("DUPLICATE_PLAYBOOK_STEP")
        for step_id in step_ids:
            if step_id not in recommended_ids:
                return _invalid("PLAYBOOK_STEP_NOT_RECOMMENDED")
            step = get_step(step_id)
            if step is None:
                return _invalid("PLAYBOOK_STEP_NOT_WHITELISTED")
            if step["step_type"] != expected_type:
                return _invalid("PLAYBOOK_STEP_TYPE_MISMATCH")
            if hypothesis.hypothesis_type not in step["applicable_hypothesis_types"]:
                return _invalid("PLAYBOOK_STEP_NOT_APPLICABLE")
            if (
                candidate_entity_type is None
                or candidate_entity_type not in step["applicable_entity_types"]
            ):
                return _invalid("PLAYBOOK_STEP_NOT_APPLICABLE")

    return ExplanationValidationResult(output=parsed)


def validate_explanation(
    output: Mapping[str, Any] | ExplanationOutput,
    run: AnalysisRun,
    hypothesis: Hypothesis,
    evidence: Sequence[EvidenceItem],
    recommendations: Sequence[RecommendationLike],
    *,
    candidate_entity_type: str | None,
    current_analysis_run_id: str | None,
    require_current: bool = True,
    expected_generator: str | None = None,
) -> ExplanationOutput | None:
    """Return a validated explanation or ``None`` for unrecoverable output."""

    return validate_explanation_detailed(
        output,
        run,
        hypothesis,
        evidence,
        recommendations,
        candidate_entity_type=candidate_entity_type,
        current_analysis_run_id=current_analysis_run_id,
        require_current=require_current,
        expected_generator=expected_generator,
    ).output
