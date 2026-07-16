"""Stateless, page-independent network concepts assistant backed by local Ollama."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class OllamaClientLike(Protocol):
    def chat(self, **kwargs: Any) -> Any: ...


class ConceptsAssistantError(RuntimeError):
    """The local concepts assistant could not produce a valid answer."""


class _ModelAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=2_000)


_SYSTEM_PROMPT = """You are a concise defensive network-operations tutor.
Answer only general questions about networking, observability, logs, metrics,
distributed systems, incident response, and root-cause-analysis terminology.
You do not have access to the user's current page, incident, telemetry, files,
or previous questions. Never imply that you can see them. If a question uses
ambiguous words such as 'this', ask the user to include the metric name, log
message, or relevant text. Do not invent application-specific values or facts.
Keep the answer practical, plain-language, and under 250 words. Return JSON
matching the supplied schema and nothing else."""


def _message_content(response: Any) -> Any:
    message = (
        response.get("message")
        if isinstance(response, Mapping)
        else getattr(response, "message", None)
    )
    if isinstance(message, Mapping):
        return message.get("content")
    return getattr(message, "content", None)


class OllamaConceptsAssistant:
    """Answer one independent concepts question per local Ollama request."""

    def __init__(
        self,
        *,
        host: str = "http://localhost:11434",
        model: str = "qwen2.5:3b",
        timeout_seconds: float = 30.0,
        client: OllamaClientLike | None = None,
    ) -> None:
        self.host = host
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._client = client

    def _client_or_raise(self) -> OllamaClientLike:
        if self._client is not None:
            return self._client
        try:
            import ollama
        except ImportError as exc:
            raise ConceptsAssistantError(
                "the optional Ollama Python package is not installed"
            ) from exc
        self._client = ollama.Client(host=self.host, timeout=self.timeout_seconds)
        return self._client

    def answer(self, question: str) -> str:
        normalized = question.strip()
        if len(normalized) < 3 or len(normalized) > 500:
            raise ConceptsAssistantError("question length is outside the supported range")

        try:
            response = self._client_or_raise().chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": normalized},
                ],
                format=_ModelAnswer.model_json_schema(),
                options={"temperature": 0.1, "seed": 0, "num_predict": 350},
                stream=False,
            )
        except ConceptsAssistantError:
            raise
        except Exception as exc:
            raise ConceptsAssistantError("local Ollama request failed") from exc

        content = _message_content(response)
        if isinstance(content, Mapping):
            payload: Any = dict(content)
        elif isinstance(content, str):
            try:
                payload = json.loads(content)
            except json.JSONDecodeError as exc:
                raise ConceptsAssistantError("Ollama response was not valid JSON") from exc
        else:
            raise ConceptsAssistantError("Ollama response did not contain an answer")

        try:
            parsed = _ModelAnswer.model_validate(payload)
        except ValidationError as exc:
            raise ConceptsAssistantError("Ollama response failed validation") from exc
        return parsed.answer.strip()


__all__ = ["ConceptsAssistantError", "OllamaConceptsAssistant"]
