from __future__ import annotations

import json
from typing import Any

import pytest

from app.concepts import ConceptsAssistantError, OllamaConceptsAssistant


class FakeOllamaClient:
    def __init__(self, content: Any) -> None:
        self.content = content
        self.calls: list[dict[str, Any]] = []

    def chat(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"message": {"content": self.content}}


def test_each_query_contains_only_the_system_prompt_and_current_question() -> None:
    client = FakeOllamaClient(
        json.dumps({"answer": "TCP retransmission means a segment was sent again."})
    )
    assistant = OllamaConceptsAssistant(client=client)

    answer = assistant.answer("What is TCP retransmission?")

    assert answer == "TCP retransmission means a segment was sent again."
    assert len(client.calls) == 1
    messages = client.calls[0]["messages"]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[1] == {
        "role": "user",
        "content": "What is TCP retransmission?",
    }
    serialized = json.dumps(messages)
    assert "incident_id" not in serialized
    assert "analysis_run" not in serialized
    assert "previous" not in messages[1]["content"].lower()


def test_sequential_queries_do_not_send_conversation_history() -> None:
    client = FakeOllamaClient({"answer": "A concise independent answer."})
    assistant = OllamaConceptsAssistant(client=client)

    assistant.answer("What is packet loss?")
    assistant.answer("What is p95 latency?")

    assert len(client.calls) == 2
    assert client.calls[0]["messages"][1]["content"] == "What is packet loss?"
    assert client.calls[1]["messages"][1]["content"] == "What is p95 latency?"
    assert len(client.calls[1]["messages"]) == 2


def test_invalid_model_output_is_rejected() -> None:
    assistant = OllamaConceptsAssistant(client=FakeOllamaClient("not json"))

    with pytest.raises(ConceptsAssistantError, match="not valid JSON"):
        assistant.answer("What is packet loss?")
