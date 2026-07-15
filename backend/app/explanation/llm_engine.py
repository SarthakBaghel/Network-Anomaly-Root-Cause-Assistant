"""Optional offline Ollama narration provider (P5-09).

The provider accepts only the structured hypothesis/evidence/playbook bundle
created by :func:`build_structured_bundle`. It never receives canonical events
or raw payloads, and its output remains subject to the deterministic validator.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol

from app.contracts import ExplanationOutput


class OllamaClientLike(Protocol):
    def chat(self, **kwargs: Any) -> Any: ...


class OllamaProviderError(RuntimeError):
    """The optional local narration provider could not return structured JSON."""


_ALLOWED_BUNDLE_KEYS = {"hypothesis", "evidence", "recommendations"}
_FORBIDDEN_INPUT_KEYS = {
    "canonical_event",
    "canonical_events",
    "event",
    "events",
    "log",
    "logs",
    "raw_log",
    "raw_logs",
    "raw_payload",
}

_SYSTEM_PROMPT = """You are an offline incident-explanation narrator.
Return exactly one JSON object matching the supplied JSON schema.
Set generator to 'llm' and copy the supplied run, incident, and hypothesis IDs exactly.
Use only the structured hypothesis, evidence, and playbook records supplied.
Every claim must cite one or more supplied evidence_id values.
Use only supplied playbook step_id values.
Do not create evidence, recommendations, scores, ranks, or identifiers.
Do not change or restate evidence_score or rank as output fields.
The summary must say 'probable root cause' and must never say 'confirmed'.
Return JSON only, with no markdown or commentary."""


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_INPUT_KEYS or _contains_forbidden_key(item):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _message_content(response: Any) -> Any:
    if isinstance(response, Mapping):
        message = response.get("message")
    else:
        message = getattr(response, "message", None)
    if isinstance(message, Mapping):
        return message.get("content")
    return getattr(message, "content", None)


class OllamaExplanationProvider:
    """Generate a schema-constrained explanation through local Ollama."""

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
            raise OllamaProviderError(
                "optional Python package 'ollama' is not installed"
            ) from exc
        self._client = ollama.Client(
            host=self.host,
            timeout=self.timeout_seconds,
        )
        return self._client

    def generate(self, bundle: Mapping[str, Any]) -> Mapping[str, Any]:
        if set(bundle) != _ALLOWED_BUNDLE_KEYS:
            raise OllamaProviderError(
                "Ollama input must contain only hypothesis, evidence, and recommendations"
            )
        if _contains_forbidden_key(bundle):
            raise OllamaProviderError("raw event or log fields are forbidden")

        serialized_bundle = json.dumps(
            bundle,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        try:
            response = self._client_or_raise().chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": serialized_bundle},
                ],
                format=ExplanationOutput.model_json_schema(),
                options={"temperature": 0, "seed": 0},
                stream=False,
            )
        except OllamaProviderError:
            raise
        except Exception as exc:
            raise OllamaProviderError("local Ollama request failed") from exc

        content = _message_content(response)
        if isinstance(content, Mapping):
            payload = dict(content)
        elif isinstance(content, str):
            try:
                payload = json.loads(content)
            except json.JSONDecodeError as exc:
                raise OllamaProviderError(
                    "Ollama response was not valid JSON"
                ) from exc
        else:
            raise OllamaProviderError("Ollama response did not contain message content")
        if not isinstance(payload, dict):
            raise OllamaProviderError("Ollama response JSON must be an object")
        return payload


__all__ = [
    "OllamaClientLike",
    "OllamaExplanationProvider",
    "OllamaProviderError",
]
