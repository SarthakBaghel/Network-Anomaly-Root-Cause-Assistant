"""Template-first explanation orchestration without transaction ownership."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.config import settings
from app.contracts import AnalysisRun, AnalysisRunStatus, EvidenceItem, Hypothesis
from app.orchestration import ExplanationDraft

from .template_engine import (
    RecommendationLike,
    TemplateExplanationEngine,
    template_engine,
)
from .validator import validate_explanation_detailed


class StructuredExplanationProvider(Protocol):
    """Optional structured provider boundary; P5-09 supplies an implementation."""

    def generate(self, bundle: Mapping[str, Any]) -> Mapping[str, Any]: ...


class ExplanationServiceError(RuntimeError):
    """The always-available deterministic explanation could not be produced."""


@dataclass(frozen=True)
class ExplanationServiceResult:
    explanation_rows: list[ExplanationDraft]
    explanation_fallback_reason: str | None = None
    explanation_fallback_attempt_count: int = 0

    def as_analysis_result_kwargs(self) -> dict[str, Any]:
        """Return the exact keyword handoff accepted by ``AnalysisResult``."""

        return {
            "explanation_rows": list(self.explanation_rows),
            "explanation_fallback_reason": self.explanation_fallback_reason,
            "explanation_fallback_attempt_count": (
                self.explanation_fallback_attempt_count
            ),
        }


def _structured_recommendation(item: RecommendationLike) -> dict[str, Any]:
    allowed = (
        "step_id",
        "title",
        "step_type",
        "risk_level",
        "requires_human_approval",
        "instructions",
        "rationale",
        "preconditions",
        "rollback_note",
    )
    return {
        name: getattr(item, name)
        for name in allowed
        if hasattr(item, name)
    }


def build_structured_bundle(
    hypothesis: Hypothesis,
    evidence: Sequence[EvidenceItem],
    recommendations: Sequence[RecommendationLike],
) -> dict[str, Any]:
    """Build the only data shape an optional provider may receive.

    Canonical events and raw payloads are deliberately not accepted by this
    function, preventing raw logs from crossing the provider boundary.
    """

    return {
        "hypothesis": hypothesis.model_dump(mode="json"),
        "evidence": [item.model_dump(mode="json") for item in evidence],
        "recommendations": [
            _structured_recommendation(item) for item in recommendations
        ],
    }


class ExplanationService:
    """Generate template output first, then optionally improve presentation."""

    def __init__(
        self,
        *,
        mode: str | None = None,
        optional_provider: StructuredExplanationProvider | None = None,
        current_run_id_provider: Callable[[str], str | None] | None = None,
        deterministic_engine: TemplateExplanationEngine = template_engine,
    ) -> None:
        selected_mode = mode or settings.explanation_mode
        if selected_mode not in {"template", "llm"}:
            raise ValueError("explanation mode must be 'template' or 'llm'")
        self.mode = selected_mode
        self.optional_provider = optional_provider
        self.current_run_id_provider = current_run_id_provider
        self.deterministic_engine = deterministic_engine

    def generate(
        self,
        run: AnalysisRun,
        hypothesis: Hypothesis,
        evidence: Sequence[EvidenceItem],
        recommendations: Sequence[RecommendationLike],
        *,
        candidate_entity_type: str | None,
    ) -> ExplanationServiceResult:
        template = self.deterministic_engine.generate(
            hypothesis, evidence, recommendations
        )
        template_validation = validate_explanation_detailed(
            template,
            run,
            hypothesis,
            evidence,
            recommendations,
            candidate_entity_type=candidate_entity_type,
            current_analysis_run_id=run.analysis_run_id,
            require_current=False,
            expected_generator="template",
        )
        if not template_validation.valid:
            raise ExplanationServiceError(
                "deterministic template failed validation: "
                f"{template_validation.reason_code}"
            )
        rows = [ExplanationDraft(output=template_validation.output)]
        if self.mode == "template":
            return ExplanationServiceResult(explanation_rows=rows)

        if self.optional_provider is None:
            return ExplanationServiceResult(
                explanation_rows=rows,
                explanation_fallback_reason="LLM_PROVIDER_UNAVAILABLE",
                explanation_fallback_attempt_count=1,
            )

        bundle = build_structured_bundle(hypothesis, evidence, recommendations)
        last_reason = "LLM_GENERATION_FAILED"
        for attempt in (1, 2):
            try:
                candidate = self.optional_provider.generate(bundle)
            except Exception:
                last_reason = "LLM_GENERATION_FAILED"
                if attempt == 1:
                    continue
                return ExplanationServiceResult(
                    explanation_rows=rows,
                    explanation_fallback_reason=last_reason,
                    explanation_fallback_attempt_count=attempt,
                )

            current_run_id = self._current_run_id(run)
            if current_run_id != run.analysis_run_id:
                return ExplanationServiceResult(
                    explanation_rows=rows,
                    explanation_fallback_reason="LLM_RESULT_STALE",
                    explanation_fallback_attempt_count=attempt,
                )
            validation = validate_explanation_detailed(
                candidate,
                run,
                hypothesis,
                evidence,
                recommendations,
                candidate_entity_type=candidate_entity_type,
                current_analysis_run_id=current_run_id,
                require_current=True,
                expected_generator="llm",
            )
            if validation.valid:
                return ExplanationServiceResult(
                    explanation_rows=[
                        *rows,
                        ExplanationDraft(output=validation.output),
                    ]
                )
            if validation.reason_code in {
                "RUN_ID_MISMATCH",
                "INCIDENT_ID_MISMATCH",
                "STALE_ANALYSIS_RUN",
            }:
                return ExplanationServiceResult(
                    explanation_rows=rows,
                    explanation_fallback_reason="LLM_RESULT_STALE",
                    explanation_fallback_attempt_count=attempt,
                )
            last_reason = f"LLM_{validation.reason_code or 'VALIDATION_FAILED'}"
            if attempt == 2:
                return ExplanationServiceResult(
                    explanation_rows=rows,
                    explanation_fallback_reason=last_reason,
                    explanation_fallback_attempt_count=attempt,
                )

        raise AssertionError("unreachable explanation retry state")

    def _current_run_id(self, run: AnalysisRun) -> str | None:
        if self.current_run_id_provider is not None:
            return self.current_run_id_provider(run.incident_id)
        if run.status is AnalysisRunStatus.CURRENT:
            return run.analysis_run_id
        return None


explanation_service = ExplanationService()
