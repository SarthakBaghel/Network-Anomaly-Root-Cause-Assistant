"""Person 5 deterministic explanation boundary."""

from .service import (
    ExplanationService,
    ExplanationServiceError,
    ExplanationServiceResult,
    StructuredExplanationProvider,
    build_structured_bundle,
    explanation_service,
)
from .llm_engine import OllamaExplanationProvider, OllamaProviderError
from .template_engine import (
    RecommendationLike,
    TemplateExplanationEngine,
    TemplateExplanationError,
    generate_template_explanation,
    template_engine,
)
from .validator import (
    ExplanationValidationResult,
    validate_explanation,
    validate_explanation_detailed,
)

__all__ = [
    "ExplanationService",
    "ExplanationServiceError",
    "ExplanationServiceResult",
    "ExplanationValidationResult",
    "OllamaExplanationProvider",
    "OllamaProviderError",
    "RecommendationLike",
    "StructuredExplanationProvider",
    "TemplateExplanationEngine",
    "TemplateExplanationError",
    "build_structured_bundle",
    "explanation_service",
    "generate_template_explanation",
    "template_engine",
    "validate_explanation",
    "validate_explanation_detailed",
]
