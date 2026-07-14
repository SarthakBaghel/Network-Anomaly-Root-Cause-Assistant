import { afterEach, describe, expect, it, vi } from "vitest";
import {
  render,
  screen,
  waitFor,
  fireEvent,
  within,
} from "@testing-library/react";

// Mock the polling hook as a no-op in unit tests to avoid timer/flakiness
vi.mock("../src/hooks/usePolling", () => ({
  usePolling: () => undefined,
}));

import { InvestigationPage } from "../src/pages/InvestigationPage";
import { apiClient } from "../src/api/client";
import investigationFixture from "../src/test-fixtures/golden-investigation-response.json";
import { TEST_IDS } from "../src/test-fixtures/testid-manifest";

describe("InvestigationPage", () => {
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
      "hypothesis-confirm-btn",
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

  it.skip("discards stale analysis responses from the poll", async () => {
    // Polling behavior is covered by Playwright E2E; skip in unit tests.
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
