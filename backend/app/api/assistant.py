from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.concepts import ConceptsAssistantError, OllamaConceptsAssistant
from app.config import settings
from app.contracts import ConceptAssistantRequest, ConceptAssistantResponse

from .error_responses import ERROR_RESPONSES


router = APIRouter(prefix="/assistant", tags=["assistant"], responses=ERROR_RESPONSES)

concepts_assistant = OllamaConceptsAssistant(
    host=settings.ollama_host,
    model=settings.ollama_model,
    timeout_seconds=settings.ollama_timeout_seconds,
)


@router.post(
    "/query",
    response_model=ConceptAssistantResponse,
    operation_id="query_network_concepts_assistant",
)
def query(request: ConceptAssistantRequest) -> ConceptAssistantResponse:
    try:
        answer = concepts_assistant.answer(request.question)
    except ConceptsAssistantError as exc:
        raise HTTPException(
            503,
            detail={
                "code": "ASSISTANT_UNAVAILABLE",
                "message": (
                    "The local Network Concepts Assistant is unavailable. "
                    "Confirm that Ollama is running and the configured model is installed."
                ),
            },
        ) from exc

    return ConceptAssistantResponse(
        generated_at=datetime.now(timezone.utc),
        answer=answer,
        model=settings.ollama_model,
        context_used=False,
    )
