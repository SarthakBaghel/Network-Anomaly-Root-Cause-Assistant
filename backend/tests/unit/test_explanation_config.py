from __future__ import annotations

import pytest

from app.config import load_settings


def test_template_mode_does_not_require_valid_ollama_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXPLANATION_MODE", "template")
    monkeypatch.setenv("OLLAMA_HOST", "https://remote.example.test:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "not-a-number")

    configured = load_settings()

    assert configured.explanation_mode == "template"
    assert configured.ollama_host == "http://localhost:11434"
    assert configured.ollama_model == "qwen2.5:3b"
    assert configured.ollama_timeout_seconds == 30.0


def test_llm_mode_accepts_only_a_local_ollama_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXPLANATION_MODE", "llm")
    monkeypatch.setenv("OLLAMA_HOST", "https://remote.example.test:11434")

    with pytest.raises(RuntimeError, match="local Ollama server"):
        load_settings()


def test_llm_mode_normalizes_local_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXPLANATION_MODE", "llm")
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11434/")
    monkeypatch.setenv("OLLAMA_MODEL", "phi3:mini")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "45")

    configured = load_settings()

    assert configured.ollama_host == "http://127.0.0.1:11434"
    assert configured.ollama_model == "phi3:mini"
    assert configured.ollama_timeout_seconds == 45.0
