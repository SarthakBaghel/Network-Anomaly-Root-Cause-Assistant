import { useEffect, useRef, useState, type FormEvent } from "react";

import { assistantApi } from "../api/assistant";
import { ApiClientError } from "../api/client";
import { TEST_IDS } from "../test-fixtures/testid-manifest";
import { SparklesIcon, XIcon } from "./icons";
import { Button } from "./ui/Button";

const EXAMPLE_QUESTIONS = [
  "What is packet loss?",
  "What does p95 latency mean?",
  "What is a SYN flood?",
] as const;

function displayError(error: unknown) {
  if (error instanceof ApiClientError) {
    return `${error.payload.code}: ${error.payload.message}`;
  }
  return "UNEXPECTED_ERROR: The assistant could not answer this question.";
}

export function ConceptAssistant() {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [submittedQuestion, setSubmittedQuestion] = useState<string | null>(null);
  const [answer, setAnswer] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const requestRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open]);

  useEffect(
    () => () => {
      requestRef.current?.abort();
    },
    [],
  );

  async function ask(nextQuestion: string) {
    const normalized = nextQuestion.trim();
    if (normalized.length < 3 || loading) return;

    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setSubmittedQuestion(normalized);
    setAnswer(null);
    setError(null);
    setLoading(true);

    try {
      const response = await assistantApi.query(
        { question: normalized },
        controller.signal,
      );
      if (!controller.signal.aborted) {
        setAnswer(response.answer);
        setQuestion("");
      }
    } catch (requestError) {
      if (!controller.signal.aborted) setError(displayError(requestError));
    } finally {
      if (!controller.signal.aborted) setLoading(false);
      if (requestRef.current === controller) requestRef.current = null;
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void ask(question);
  }

  return (
    <>
      {open ? (
        <section
          role="dialog"
          aria-label="Network Concepts Assistant"
          aria-modal="false"
          data-testid={TEST_IDS.conceptsAssistantPanel}
          className="fixed bottom-20 left-4 right-4 z-50 flex max-h-[min(620px,calc(100vh-6rem))] flex-col overflow-hidden rounded-lg border border-accent-cyan/30 bg-surface shadow-glass-lg md:left-[17rem] md:right-auto md:w-[390px]"
        >
          <header className="flex items-start justify-between border-b border-border-subtle bg-surface-strong px-4 py-3">
            <div className="flex gap-2.5">
              <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent-cyan/10 text-accent-cyan">
                <SparklesIcon className="h-4 w-4" />
              </span>
              <div>
                <h2 className="text-sm font-semibold text-text-primary">
                  Network Concepts Assistant
                </h2>
                <p className="mt-0.5 text-[11px] text-text-muted">
                  Independent questions · no page context or memory
                </p>
              </div>
            </div>
            <button
              type="button"
              aria-label="Close Network Concepts Assistant"
              data-testid={TEST_IDS.conceptsAssistantClose}
              onClick={() => setOpen(false)}
              className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-white/5 hover:text-text-primary"
            >
              <XIcon className="h-4 w-4" />
            </button>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {!submittedQuestion ? (
              <div className="space-y-3">
                <p className="text-sm leading-6 text-text-secondary">
                  Ask about general networking, metrics, logs, traces, or RCA terminology.
                </p>
                <div className="flex flex-wrap gap-2" aria-label="Example questions">
                  {EXAMPLE_QUESTIONS.map((example) => (
                    <button
                      key={example}
                      type="button"
                      onClick={() => setQuestion(example)}
                      className="rounded-full border border-border-subtle bg-surface-soft px-3 py-1.5 text-left text-xs text-text-secondary transition-colors hover:border-accent-cyan/40 hover:text-accent-cyan"
                    >
                      {example}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="space-y-3" aria-live="polite">
                <div className="rounded-md border border-border-subtle bg-surface-soft px-3 py-2.5">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                    Current question
                  </p>
                  <p className="mt-1 text-sm text-text-primary">{submittedQuestion}</p>
                </div>
                {loading ? (
                  <div className="flex items-center gap-2 text-sm text-text-secondary" role="status">
                    <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-accent-cyan border-t-transparent" />
                    Asking local Ollama…
                  </div>
                ) : null}
                {answer ? (
                  <div
                    data-testid={TEST_IDS.conceptsAssistantAnswer}
                    className="whitespace-pre-wrap rounded-md border border-accent-cyan/20 bg-accent-cyan/5 px-3 py-3 text-sm leading-6 text-text-secondary"
                  >
                    {answer}
                  </div>
                ) : null}
                {error ? (
                  <p
                    role="alert"
                    className="rounded-md border border-accent-red/30 bg-accent-red/10 px-3 py-2.5 text-sm text-accent-red"
                  >
                    {error}
                  </p>
                ) : null}
              </div>
            )}
          </div>

          <form onSubmit={submit} className="border-t border-border-subtle p-3">
            <label htmlFor="concept-assistant-question" className="sr-only">
              Ask a network concepts question
            </label>
            <textarea
              id="concept-assistant-question"
              ref={inputRef}
              data-testid={TEST_IDS.conceptsAssistantInput}
              value={question}
              maxLength={500}
              rows={2}
              disabled={loading}
              placeholder="Example: What does tcp_retransmissions_total mean?"
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void ask(question);
                }
              }}
              className="w-full resize-none rounded-md border border-border-strong bg-surface-soft px-3 py-2 text-sm text-text-primary outline-none transition-colors placeholder:text-text-muted focus:border-accent-cyan disabled:opacity-60"
            />
            <div className="mt-2 flex items-center justify-between gap-3">
              <span className="text-[10px] text-text-muted">{question.length}/500</span>
              <Button
                type="submit"
                variant="primary"
                loading={loading}
                disabled={question.trim().length < 3}
                data-testid={TEST_IDS.conceptsAssistantSubmit}
                className="px-4 py-1.5"
              >
                Ask
              </Button>
            </div>
          </form>
        </section>
      ) : null}

      <button
        type="button"
        aria-label="Open Network Concepts Assistant"
        aria-expanded={open}
        data-testid={TEST_IDS.conceptsAssistantToggle}
        onClick={() => setOpen((current) => !current)}
        className="fixed bottom-5 left-4 z-50 flex items-center gap-2 rounded-full border border-accent-cyan/40 bg-surface-strong px-3.5 py-2.5 text-sm font-semibold text-accent-cyan shadow-glass-lg transition-colors hover:border-accent-cyan hover:bg-accent-cyan/10 md:left-[17rem]"
      >
        <SparklesIcon className="h-4 w-4" />
        <span className="hidden sm:inline">Ask network concepts</span>
      </button>
    </>
  );
}
