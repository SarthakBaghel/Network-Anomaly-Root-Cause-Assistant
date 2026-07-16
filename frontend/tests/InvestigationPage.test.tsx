import { afterEach, describe, expect, it, vi } from "vitest";
import {
  render,
  screen,
  waitFor,
  fireEvent,
  within,
  act,
} from "@testing-library/react";

let pollCallback: (() => void) | null = null;
vi.mock("../src/hooks/usePolling", async () => {
  const React = await import("react");
  return {
    usePolling: (callback: () => void) => {
      React.useEffect(() => {
        pollCallback = callback;
        void callback();
      }, [callback]);
    },
  };
});

import { InvestigationPage } from "../src/pages/InvestigationPage";
import { incidentsApi } from "../src/api/incidents";
import { ApiClientError } from "../src/api/client";
import investigationFixture from "../src/test-fixtures/golden-investigation-response.json";
import {
  TEST_IDS,
  evidenceItemTestId,
  hypothesisConfirmTestId,
} from "../src/test-fixtures/testid-manifest";

describe("InvestigationPage", () => {
  afterEach(() => {
    pollCallback = null;
    vi.restoreAllMocks();
  });
  it("renders an initial not-found error instead of an endless loading skeleton", async () => {
    vi.spyOn(incidentsApi, "getInvestigation").mockRejectedValue(new ApiClientError(404, {
      code: "INCIDENT_NOT_FOUND",
      message: "Incident not found.",
      details: [],
    }));
    vi.spyOn(incidentsApi, "getAudit").mockResolvedValue({ generated_at: "2026-07-14T09:32:00Z", items: [], next_cursor: null });

    render(<InvestigationPage incidentId="missing" />);

    expect(await screen.findByText("INCIDENT_NOT_FOUND: Incident not found.")).toBeInTheDocument();
    expect(screen.queryByText("Loading incident investigation...")).not.toBeInTheDocument();
  });

  it("renders an initial network error instead of an endless loading skeleton", async () => {
    vi.spyOn(incidentsApi, "getInvestigation").mockRejectedValue(new Error("Network unavailable"));
    vi.spyOn(incidentsApi, "getAudit").mockResolvedValue({ generated_at: "2026-07-14T09:32:00Z", items: [], next_cursor: null });

    render(<InvestigationPage incidentId="inc_001" />);

    expect(await screen.findByText("UNEXPECTED_ERROR: Unable to load investigation snapshot")).toBeInTheDocument();
    expect(screen.queryByText("Loading incident investigation...")).not.toBeInTheDocument();
  });
  it("renders all evidence categories in the explorer", async () => {
    vi.spyOn(incidentsApi, "getInvestigation").mockResolvedValue(investigationFixture as any);
    vi.spyOn(incidentsApi, "getAudit").mockResolvedValue({ generated_at: "2026-07-14T09:32:00Z", items: [], next_cursor: null });

    render(<InvestigationPage incidentId="inc_001" />);

    const evidencePanel = await screen.findByTestId(TEST_IDS.evidencePanel);
    expect(evidencePanel).toBeInTheDocument();
    expect(
      within(evidencePanel).getAllByText(/Verified observed facts/i).length,
    ).toBeGreaterThan(0);
    expect(
      within(evidencePanel).getAllByText(/Correlated signals/i).length,
    ).toBeGreaterThan(0);
    expect(
      within(evidencePanel).getAllByText(/Conflicting evidence/i).length,
    ).toBeGreaterThan(0);
    expect(
      within(evidencePanel).getAllByText(/Missing evidence/i).length,
    ).toBeGreaterThan(0);
  });

  it("downloads timestamped Markdown and PDF shift-handover reports", async () => {
    vi.spyOn(incidentsApi, "getInvestigation").mockResolvedValue(investigationFixture as any);
    vi.spyOn(incidentsApi, "getAudit").mockResolvedValue({ generated_at: "2026-07-14T09:32:00Z", items: [], next_cursor: null });
    const download = vi.spyOn(incidentsApi, "downloadHandover").mockImplementation(async (_incidentId, format) => ({
      blob: new Blob([format], { type: format === "pdf" ? "application/pdf" : "text/markdown" }),
      filename: `handover.${format}`,
    }));
    const createObjectUrl = vi.fn(() => "blob:handover");
    const revokeObjectUrl = vi.fn();
    Object.defineProperty(window.URL, "createObjectURL", { configurable: true, value: createObjectUrl });
    Object.defineProperty(window.URL, "revokeObjectURL", { configurable: true, value: revokeObjectUrl });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    render(<InvestigationPage incidentId="inc_001" />);

    fireEvent.click(await screen.findByTestId(TEST_IDS.handoverMarkdown));
    await waitFor(() => expect(download).toHaveBeenCalledWith("inc_001", "md"));
    await waitFor(() => expect(screen.getByText("Markdown shift-handover report downloaded.")).toBeInTheDocument());

    fireEvent.click(screen.getByTestId(TEST_IDS.handoverPdf));
    await waitFor(() => expect(download).toHaveBeenCalledWith("inc_001", "pdf"));
    await waitFor(() => expect(screen.getByText("PDF shift-handover report downloaded.")).toBeInTheDocument());
    expect(createObjectUrl).toHaveBeenCalledTimes(2);
    expect(revokeObjectUrl).toHaveBeenCalledTimes(2);
    expect(click).toHaveBeenCalledTimes(2);
  });

  it("disables confirm button and posts with client_action_id", async () => {
    const postSpy = vi.spyOn(incidentsApi, "submitReview").mockResolvedValue({} as any);
    vi.spyOn(incidentsApi, "getInvestigation").mockResolvedValue(investigationFixture as any);
    vi.spyOn(incidentsApi, "getAudit").mockResolvedValue({ generated_at: "2026-07-14T09:32:00Z", items: [], next_cursor: null });

    render(<InvestigationPage incidentId="inc_001" />);

    const hypothesisRows = await screen.findAllByTestId(
      "hypothesis-row-hyp_001",
    );
    const hypothesisRow = hypothesisRows[0];
    const confirmButton = within(hypothesisRow).getByTestId(
      hypothesisConfirmTestId("hyp_001"),
    );
    fireEvent.click(confirmButton);

    await waitFor(() => expect(confirmButton).toBeDisabled());
    await waitFor(() => expect(postSpy).toHaveBeenCalled());

    const [, body] = postSpy.mock.calls[0];
    expect(body).toHaveProperty("client_action_id");
    expect(body).toMatchObject({
      decision: "confirmed",
      hypothesis_id: "hyp_001",
    });
  });

  it("discards stale analysis responses from the poll", async () => {
    let callCount = 0;

    vi.spyOn(incidentsApi, "getInvestigation").mockImplementation(async () => {
      callCount += 1;
      if (callCount === 1) return investigationFixture as any;
      return {
        ...investigationFixture,
        generated_at: "2026-07-14T09:31:42.000Z",
        analysis_run: { ...investigationFixture.analysis_run, revision: 6 },
        analysis_run_id: "run_006",
      } as any;
    });
    vi.spyOn(incidentsApi, "getAudit").mockResolvedValue({ generated_at: "2026-07-14T09:32:00Z", items: [], next_cursor: null });

    render(<InvestigationPage incidentId="inc_001" />);

    await waitFor(() => expect(incidentsApi.getInvestigation).toHaveBeenCalledTimes(1));
    await act(async () => {
      if (pollCallback) {
        await pollCallback();
      }
    });

    expect(
      screen.queryByTestId(TEST_IDS.staleAnalysisBanner),
    ).not.toBeInTheDocument();
  });

  it("shows stale-analysis banner when poll returns a newer analysis snapshot", async () => {
    let callCount = 0;

    vi.spyOn(incidentsApi, "getInvestigation").mockImplementation(async () => {
      callCount += 1;
      if (callCount === 1) return investigationFixture as any;
      return {
        ...investigationFixture,
        generated_at: "2026-07-14T09:31:42.000Z",
        analysis_run: { ...investigationFixture.analysis_run, revision: 8 },
        analysis_run_id: "run_008",
        incident: { ...investigationFixture.incident, title: "Replacement snapshot title" },
      } as any;
    });
    vi.spyOn(incidentsApi, "getAudit").mockResolvedValue({ generated_at: "2026-07-14T09:32:00Z", items: [], next_cursor: null });

    render(<InvestigationPage incidentId="inc_001" />);

    await waitFor(() => expect(incidentsApi.getInvestigation).toHaveBeenCalledTimes(1));
    await act(async () => {
      if (pollCallback) {
        await pollCallback();
      }
    });

    const banner = await screen.findByTestId(TEST_IDS.staleAnalysisBanner);
    expect(banner).toHaveTextContent(
      "Analysis updated; now displaying the latest snapshot.",
    );
    expect(screen.getByText("Replacement snapshot title")).toBeInTheDocument();
  });

  it("renders timeline attached and excluded events separately", async () => {
    vi.spyOn(incidentsApi, "getInvestigation").mockResolvedValue(investigationFixture as any);
    vi.spyOn(incidentsApi, "getAudit").mockResolvedValue({ generated_at: "2026-07-14T09:32:00Z", items: [], next_cursor: null });

    render(<InvestigationPage incidentId="inc_001" />);

    const panels = await screen.findAllByTestId(TEST_IDS.timelinePanel);
    let attached = 0;
    let excluded = 0;
    panels.forEach((panel) => {
      const a = panel.querySelectorAll('circle[data-attached="true"]');
      const e = panel.querySelectorAll('circle[data-attached="false"]');
      attached += a.length;
      excluded += e.length;
    });

    expect(attached).toBeGreaterThan(0);
    expect(excluded).toBeGreaterThan(0);
  });

  it("rejects an older generated_at response for the same analysis revision", async () => {
    let callCount = 0;
    vi.spyOn(incidentsApi, "getInvestigation").mockImplementation(async () => {
      callCount += 1;
      if (callCount === 1) return investigationFixture as any;
      return {
        ...investigationFixture,
        generated_at: "2026-07-14T09:30:00Z",
        incident: { ...investigationFixture.incident, title: "Stale title must not render" },
      } as any;
    });
    vi.spyOn(incidentsApi, "getAudit").mockResolvedValue({ generated_at: "2026-07-14T09:32:00Z", items: [], next_cursor: null });
    render(<InvestigationPage incidentId="inc_001" />);
    await screen.findByText(investigationFixture.incident.title);
    await act(async () => { await pollCallback?.(); });
    expect(screen.queryByText("Stale title must not render")).not.toBeInTheDocument();
  });

  it("opens missing evidence as a concrete collection request", async () => {
    vi.spyOn(incidentsApi, "getInvestigation").mockResolvedValue(investigationFixture as any);
    vi.spyOn(incidentsApi, "getAudit").mockResolvedValue({ generated_at: "2026-07-14T09:32:00Z", items: [], next_cursor: null });
    render(<InvestigationPage incidentId="inc_001" />);
    const missing = Object.values(investigationFixture.evidence_by_hypothesis).flat().find((item) => item.kind === "missing")!;
    fireEvent.click(await screen.findByTestId(evidenceItemTestId(missing.evidence_id)));
    expect(await screen.findByRole("dialog")).toHaveTextContent("Evidence collection request");
    expect(screen.getByTestId(TEST_IDS.eventModalBody)).toHaveTextContent(missing.statement);
  });

  it("shows attachment details for accepted evidence without fabricating a record", async () => {
    vi.spyOn(incidentsApi, "getInvestigation").mockResolvedValue(investigationFixture as any);
    vi.spyOn(incidentsApi, "getAudit").mockResolvedValue({ generated_at: "2026-07-14T09:32:00Z", items: [], next_cursor: null });
    render(<InvestigationPage incidentId="inc_001" />);
    const accepted = Object.values(investigationFixture.evidence_by_hypothesis)
      .flat()
      .find((item) => item.kind === "observed" && item.source_event_id)!;

    fireEvent.click(await screen.findByTestId(evidenceItemTestId(accepted.evidence_id)));

    const modal = await screen.findByRole("dialog");
    expect(modal).toHaveTextContent("Raw CanonicalEvent");
    expect(modal).toHaveTextContent("Attachment score");
    expect(modal).toHaveTextContent(String(accepted.source_event_id));
  });

  it("renders the explanation-fallback state from the append-only audit", async () => {
    vi.spyOn(incidentsApi, "getInvestigation").mockResolvedValue(investigationFixture as any);
    vi.spyOn(incidentsApi, "getAudit").mockResolvedValue({ generated_at: "2026-07-14T09:32:00Z", items: [{
      audit_id: "aud_fallback_001",
      timestamp: "2026-07-14T09:31:42Z",
      actor_type: "system",
      actor_id: null,
      action: "EXPLANATION_FALLBACK_USED",
      object_type: "analysis_run",
      object_id: "run_007",
      request_id: "req_fallback_001",
      analysis_run_id: "run_007",
      payload: {},
    }] as any, next_cursor: null });

    render(<InvestigationPage incidentId="inc_001" />);

    expect(await screen.findByTestId(TEST_IDS.explanationFallbackBanner)).toHaveTextContent("template")
  });

  it("surfaces a frozen review-conflict message", async () => {
    vi.spyOn(incidentsApi, "getInvestigation").mockResolvedValue(investigationFixture as any);
    vi.spyOn(incidentsApi, "getAudit").mockResolvedValue({ generated_at: "2026-07-14T09:32:00Z", items: [], next_cursor: null });
    vi.spyOn(incidentsApi, "submitReview").mockRejectedValue(new ApiClientError(409, {
      code: "REVIEW_CONFLICT",
      message: "A terminal decision already exists.",
      details: [],
    }));

    render(<InvestigationPage incidentId="inc_001" />);
    fireEvent.click(await screen.findByTestId(hypothesisConfirmTestId("hyp_001")));

    expect(await screen.findByTestId(TEST_IDS.genericBanner)).toHaveTextContent("Decision already recorded")
  });
});
