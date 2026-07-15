"""Always-available deterministic explanation generation (P5-08)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from jinja2 import Environment, StrictUndefined

from app.contracts import EvidenceItem, ExplanationOutput, Hypothesis


class RecommendationLike(Protocol):
    """Structural subset shared by catalogue and API recommendations."""

    step_id: str
    step_type: str


class TemplateExplanationError(ValueError):
    """Input records do not form one run-scoped hypothesis bundle."""


_ENVIRONMENT = Environment(
    autoescape=False,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
_SUMMARY_TEMPLATE = _ENVIRONMENT.from_string(
    "The probable root cause is {{ cause }} affecting {{ entity_id }}."
)
_CLAIM_TEMPLATE = _ENVIRONMENT.from_string(
    "{% if prefix %}{{ prefix }}: {% endif %}{{ statement }}"
)
_CAUSE_LABELS = {
    "configuration_regression": "a configuration regression",
    "dos_or_traffic_surge": "a denial-of-service or traffic surge",
    "database_connection_exhaustion": "database connection exhaustion",
    "network_path_congestion": "network path congestion",
    "upstream_service_failure": "an upstream service failure",
    "dns_resolution_failure": "a DNS resolution failure",
    "certificate_or_tls_failure": "a certificate or TLS failure",
}
_KIND_ORDER = {"observed": 0, "correlated": 1, "conflicting": 2, "missing": 3}
_CLAIM_PREFIX = {
    "observed": "Observed evidence",
    "correlated": "Correlated signal",
    "conflicting": "Conflicting evidence",
    "missing": "Missing evidence",
}


def _scope_check(hypothesis: Hypothesis, evidence: Sequence[EvidenceItem]) -> None:
    for item in evidence:
        if item.analysis_run_id != hypothesis.analysis_run_id:
            raise TemplateExplanationError(
                "evidence analysis_run_id does not match hypothesis"
            )
        if item.incident_id != hypothesis.incident_id:
            raise TemplateExplanationError(
                "evidence incident_id does not match hypothesis"
            )
        if item.hypothesis_id != hypothesis.hypothesis_id:
            raise TemplateExplanationError(
                "evidence hypothesis_id does not match hypothesis"
            )


def _step_ids(
    recommendations: Sequence[RecommendationLike], step_type: str
) -> list[str]:
    return sorted(
        {
            recommendation.step_id
            for recommendation in recommendations
            if recommendation.step_type == step_type
        }
    )


def generate_template_explanation(
    hypothesis: Hypothesis,
    evidence: Sequence[EvidenceItem],
    recommendations: Sequence[RecommendationLike],
) -> ExplanationOutput:
    """Render a deterministic, offline explanation for one hypothesis.

    An empty evidence or recommendation sequence is valid. Claims are emitted
    only when an evidence record exists, so every emitted claim is traceable.
    """

    _scope_check(hypothesis, evidence)
    cause = _CAUSE_LABELS.get(
        hypothesis.hypothesis_type,
        hypothesis.hypothesis_type.replace("_", " "),
    )
    summary = _SUMMARY_TEMPLATE.render(
        cause=cause,
        entity_id=hypothesis.candidate_entity_id,
    ).strip()
    ordered_evidence = sorted(
        evidence,
        key=lambda item: (
            _KIND_ORDER[item.kind.value],
            item.created_at,
            item.reason_code,
            item.source_event_id or "",
            item.evidence_id,
        ),
    )
    claims = [
        {
            "claim": _CLAIM_TEMPLATE.render(
                prefix=_CLAIM_PREFIX[item.kind.value],
                statement=item.statement.rstrip("."),
            ).strip()
            + ".",
            "evidence_ids": [item.evidence_id],
        }
        for item in ordered_evidence
    ]
    output = ExplanationOutput(
        analysis_run_id=hypothesis.analysis_run_id,
        incident_id=hypothesis.incident_id,
        hypothesis_id=hypothesis.hypothesis_id,
        generator="template",
        summary=summary,
        claims=claims,
        diagnostic_step_ids=_step_ids(recommendations, "diagnostic"),
        remediation_step_ids=_step_ids(recommendations, "remediation"),
    )
    if "probable root cause" not in output.summary.lower():
        raise TemplateExplanationError("template summary must say probable root cause")
    if "confirmed" in output.summary.lower():
        raise TemplateExplanationError("template summary must not claim confirmation")
    return output


class TemplateExplanationEngine:
    """Object-oriented facade used by the explanation service."""

    def generate(
        self,
        hypothesis: Hypothesis,
        evidence: Sequence[EvidenceItem],
        recommendations: Sequence[RecommendationLike],
    ) -> ExplanationOutput:
        return generate_template_explanation(hypothesis, evidence, recommendations)


template_engine = TemplateExplanationEngine()
