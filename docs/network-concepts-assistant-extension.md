# Network Concepts Assistant Extension

**Status:** Implemented and verified on 2026-07-16  
**Relationship to the blueprint:** Additive, post-blueprint extension

## Purpose and limits

The original `BLUEPRINT.md` does not require a chatbot. This extension adds a
small global **Network Concepts Assistant** to help a presenter or operator
understand general terms such as packet loss, p95 latency, TCP
retransmissions, alerts, logs, traces, and common failure modes.

It is deliberately not page-aware. Ollama receives no incident snapshot, DOM
content, telemetry records, raw logs, files, or previous questions. The widget
states this limitation and asks users to include the exact metric or log text
in each question. Every answer replaces the previous answer in the UI.

## Stateless request boundary

Each request sends exactly two messages to local Ollama:

1. a fixed defensive network-operations tutor instruction; and
2. the current question.

No conversation history is stored by the frontend or backend. Keeping the
model process warm does not give it conversational memory because earlier
messages are never included in a subsequent request.

The tutor instruction prohibits claims that it can see the page and directs
the model to ask for the relevant metric name or log text when a question uses
ambiguous language such as “this”. Output is schema-constrained to one
plain-text answer of at most 2,000 characters.

## API and UI

`POST /api/v1/assistant/query` accepts:

```json
{ "question": "What does p95 latency mean?" }
```

The response includes the answer, model name, generation time, and the explicit
flag `context_used: false`.

The floating widget is available from both the operations overview and incident
investigation pages. It is positioned at the lower-left edge of the main
content so it does not cover the desktop navigation controls. Ollama loading
and failure states remain inside the widget and do not affect the simulator or
page polling.

## Local setup

Install and prepare the optional local model once:

```bash
.venv/bin/python -m pip install -e "backend[llm]"
ollama pull qwen2.5:3b
```

Then start the application normally:

```bash
./scripts/dev.sh
```

The concepts assistant uses local Ollama even when deterministic template
explanations remain enabled. `EXPLANATION_MODE=llm` is needed only when Ollama
should also narrate the incident explanation summary.

## Safety and failure behaviour

- The assistant is read-only and exposes no mutation or review tools.
- Its answers are educational and are not incorporated into RCA evidence.
- It cannot change hypothesis ranks, scores, recommendations, incidents, or
  audit records.
- Questions are limited to 500 characters and model answers to 2,000.
- Unavailable, slow, malformed, or invalid Ollama output produces a contained
  `ASSISTANT_UNAVAILABLE` error.
- The simulator and deterministic RCA continue to function without Ollama.

## Verification

Backend tests verify the two-message stateless boundary, absence of incident
context and history, output validation, request validation, and the unavailable
response. Frontend tests verify the context disclaimer, independent request
bodies, answer replacement, and isolated error rendering. The generated
OpenAPI document and TypeScript client remain the contract authority.
