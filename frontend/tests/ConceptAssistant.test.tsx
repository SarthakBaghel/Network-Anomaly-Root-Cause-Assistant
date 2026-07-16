import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { ConceptAssistant } from "../src/components/ConceptAssistant";
import { server } from "../src/mocks/server";
import { TEST_IDS } from "../src/test-fixtures/testid-manifest";


describe("ConceptAssistant", () => {
  it("labels itself as independent and without page context", () => {
    render(<ConceptAssistant />);

    fireEvent.click(screen.getByTestId(TEST_IDS.conceptsAssistantToggle));

    expect(screen.getByTestId(TEST_IDS.conceptsAssistantPanel)).toHaveTextContent(
      "Independent questions · no page context or memory",
    );
    expect(screen.queryByText(/cannot see this page/i)).not.toBeInTheDocument();
  });

  it("sends only the current question and replaces the prior answer", async () => {
    const requestBodies: unknown[] = [];
    server.use(
      http.post("*/api/v1/assistant/query", async ({ request }) => {
        const body = await request.json();
        requestBodies.push(body);
        return HttpResponse.json({
          generated_at: "2026-07-16T04:30:00Z",
          answer: `Answer ${requestBodies.length}`,
          model: "qwen2.5:3b",
          context_used: false,
        });
      }),
    );
    render(<ConceptAssistant />);
    fireEvent.click(screen.getByTestId(TEST_IDS.conceptsAssistantToggle));

    const input = screen.getByTestId(TEST_IDS.conceptsAssistantInput);
    fireEvent.change(input, { target: { value: "What is packet loss?" } });
    fireEvent.click(screen.getByTestId(TEST_IDS.conceptsAssistantSubmit));
    expect(await screen.findByTestId(TEST_IDS.conceptsAssistantAnswer)).toHaveTextContent(
      "Answer 1",
    );

    fireEvent.change(input, { target: { value: "What is p95 latency?" } });
    fireEvent.click(screen.getByTestId(TEST_IDS.conceptsAssistantSubmit));
    await waitFor(() =>
      expect(screen.getByTestId(TEST_IDS.conceptsAssistantAnswer)).toHaveTextContent(
        "Answer 2",
      ),
    );

    expect(requestBodies).toEqual([
      { question: "What is packet loss?" },
      { question: "What is p95 latency?" },
    ]);
    expect(screen.queryByText("Answer 1")).not.toBeInTheDocument();
  });

  it("keeps Ollama failures inside the widget", async () => {
    server.use(
      http.post("*/api/v1/assistant/query", () =>
        HttpResponse.json(
          {
            error: {
              code: "ASSISTANT_UNAVAILABLE",
              message: "The local Network Concepts Assistant is unavailable.",
              details: [],
            },
          },
          { status: 503 },
        ),
      ),
    );
    render(<ConceptAssistant />);
    fireEvent.click(screen.getByTestId(TEST_IDS.conceptsAssistantToggle));
    fireEvent.change(screen.getByTestId(TEST_IDS.conceptsAssistantInput), {
      target: { value: "What is packet loss?" },
    });
    fireEvent.click(screen.getByTestId(TEST_IDS.conceptsAssistantSubmit));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "ASSISTANT_UNAVAILABLE",
    );
    expect(screen.getByTestId(TEST_IDS.conceptsAssistantPanel)).toBeInTheDocument();
  });
});
