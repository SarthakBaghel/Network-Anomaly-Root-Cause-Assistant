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
const usePollingMock = vi.fn((callback: () => void) => {
  pollCallback = callback;
});
vi.mock("../src/hooks/usePolling", () => ({
  usePolling: (...args: any[]) => {
    pollCallback = args[0];
  },
}));

import { InvestigationPage } from "../src/pages/InvestigationPage";
import { apiClient } from "../src/api/client";
import investigationFixture from "../src/test-fixtures/golden-investigation-response.json";
import {
  TEST_IDS,
  hypothesisConfirmTestId,
} from "../src/test-fixtures/testid-manifest";

describe("InvestigationPage", () => {
  afterEach(() => {
    pollCallback = null;
    usePollingMock.mockReset();
    vi.restoreAllMocks();
  });
  it("renders all evidence categories in the explorer", async () => {
    vi.spyOn(apiClient, "get").mockImplementation((url: string) => {
      if (url.includes("/investigation")) {
        return Promise.resolve({ data: investigationFixture });
      }
      if (url.includes("/audit")) {
        return Promise.resolve({ data: [] });
      }
      return Promise.resolve({ data: {} });
    });

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

  it("disables confirm button and posts with client_action_id", async () => {
    const postSpy = vi.spyOn(apiClient, "post").mockResolvedValue({ data: {} });
    vi.spyOn(apiClient, "get").mockImplementation((url: string) => {
      if (url.includes("/investigation")) {
        return Promise.resolve({ data: investigationFixture });
      }
      if (url.includes("/audit")) {
        return Promise.resolve({ data: [] });
      }
      return Promise.resolve({ data: {} });
    });

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

    const [url, body] = postSpy.mock.calls[0];
    expect(url).toMatch(/\/incidents\/inc_001\/review$/);
    expect(body).toHaveProperty("client_action_id");
    expect(body).toMatchObject({
      decision: "confirmed",
      hypothesis_id: "hyp_001",
    });
  });

  it("discards stale analysis responses from the poll", async () => {
    let callCount = 0;

    vi.spyOn(apiClient, "get").mockImplementation((url: string) => {
      if (url.includes("/investigation")) {
        callCount += 1;
        if (callCount === 1) {
          return Promise.resolve({ data: investigationFixture });
        }

        return Promise.resolve({
          data: {
            ...investigationFixture,
            analysis_run: {
              ...investigationFixture.analysis_run,
              revision: 6,
            },
            analysis_run_id: "run_006",
          },
        });
      }

      if (url.includes("/audit")) {
        return Promise.resolve({ data: [] });
      }

      return Promise.resolve({ data: {} });
    });

    render(<InvestigationPage incidentId="inc_001" />);

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
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

    vi.spyOn(apiClient, "get").mockImplementation((url: string) => {
      if (url.includes("/investigation")) {
        callCount += 1;
        if (callCount === 1) {
          return Promise.resolve({ data: investigationFixture });
        }

        return Promise.resolve({
          data: {
            ...investigationFixture,
            analysis_run: {
              ...investigationFixture.analysis_run,
              revision: 8,
            },
            analysis_run_id: "run_008",
          },
        });
      }

      if (url.includes("/audit")) {
        return Promise.resolve({ data: [] });
      }

      return Promise.resolve({ data: {} });
    });

    render(<InvestigationPage incidentId="inc_001" />);

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    await act(async () => {
      if (pollCallback) {
        await pollCallback();
      }
    });

    const banner = await screen.findByTestId(TEST_IDS.staleAnalysisBanner);
    expect(banner).toHaveTextContent(
      "Analysis updated; now displaying the latest snapshot.",
    );
  });

  it("renders timeline attached and excluded events separately", async () => {
    vi.spyOn(apiClient, "get").mockImplementation((url: string) => {
      if (url.includes("/investigation")) {
        return Promise.resolve({ data: investigationFixture });
      }
      if (url.includes("/audit")) {
        return Promise.resolve({ data: [] });
      }
      return Promise.resolve({ data: {} });
    });

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
});
