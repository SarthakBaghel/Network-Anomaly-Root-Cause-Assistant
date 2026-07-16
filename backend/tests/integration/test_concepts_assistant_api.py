from fastapi.testclient import TestClient

import app.api.assistant as assistant_api
from app.concepts import ConceptsAssistantError
from app.main import app


class StubAssistant:
    def __init__(self, *, error: bool = False) -> None:
        self.error = error
        self.questions: list[str] = []

    def answer(self, question: str) -> str:
        self.questions.append(question)
        if self.error:
            raise ConceptsAssistantError("offline")
        return "Packet loss is the percentage of packets that do not reach their destination."


def test_query_returns_a_stateless_concepts_answer(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    stub = StubAssistant()
    monkeypatch.setattr(assistant_api, "concepts_assistant", stub)

    response = TestClient(app).post(
        "/api/v1/assistant/query",
        json={"question": "  What is packet loss?  "},
    )

    assert response.status_code == 200
    assert stub.questions == ["What is packet loss?"]
    assert response.json() == {
        "generated_at": response.json()["generated_at"],
        "answer": "Packet loss is the percentage of packets that do not reach their destination.",
        "model": "qwen2.5:3b",
        "context_used": False,
    }


def test_query_validates_question_length() -> None:
    response = TestClient(app).post(
        "/api/v1/assistant/query",
        json={"question": " ? "},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_query_reports_ollama_unavailability(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(assistant_api, "concepts_assistant", StubAssistant(error=True))

    response = TestClient(app).post(
        "/api/v1/assistant/query",
        json={"question": "What is packet loss?"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ASSISTANT_UNAVAILABLE"
