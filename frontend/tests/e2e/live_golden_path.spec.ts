import { expect, test } from "@playwright/test";

import { TEST_IDS } from "../../src/test-fixtures/testid-manifest";

test("real UI completes reset, replay, investigation, review, and audit", async ({
  page,
}) => {
  const backendResponses: string[] = [];
  page.on("response", (response) => {
    if (response.url().startsWith("http://127.0.0.1:8000/api/v1/")) {
      backendResponses.push(response.url());
    }
  });

  await page.goto("/");
  await expect(page.getByTestId(TEST_IDS.incidentList)).toBeVisible();
  await expect(page.getByTestId(TEST_IDS.simulatorState)).not.toContainText(
    "loading",
  );

  await page.getByTestId(TEST_IDS.simulatorReset).click();
  await expect(page.getByTestId(TEST_IDS.simulatorState)).toContainText("stopped");
  await expect(page.getByTestId(/^incident-row-/)).toHaveCount(0);

  await page.getByTestId(TEST_IDS.scenarioTrigger).click();
  await expect(page.getByTestId(TEST_IDS.simulatorState)).toContainText(
    "completed",
  );
  await expect(page.getByTestId(/^anomaly-row-/).first()).toBeVisible();

  const incidentRow = page.getByTestId(/^incident-row-/).first();
  await expect(incidentRow).toBeVisible();
  const incidentHref = await incidentRow.getAttribute("href");
  expect(incidentHref).toMatch(/^\/incidents\/inc_[a-f0-9]+$/);
  expect(incidentHref).not.toBe("/incidents/inc_001");
  await incidentRow.click();

  await expect(page.getByTestId(TEST_IDS.investigationPanel)).toBeVisible();
  await expect(page.getByTestId(TEST_IDS.timelinePanel)).toBeVisible();
  await expect(page.getByTestId(TEST_IDS.topologyGraph)).toBeVisible();
  await expect(page.getByTestId(TEST_IDS.evidencePanel)).toBeVisible();
  await expect(page.getByText(/^Analysis run run_[a-f0-9]+$/)).toBeVisible();
  await expect(page.getByText("Analysis run run_007")).toHaveCount(0);

  const requestEvidence = page.getByTestId(/^evidence-request-btn-/).first();
  await expect(requestEvidence).toBeEnabled();
  await requestEvidence.click();
  await expect(
    page.getByTestId(TEST_IDS.auditTrailPanel).getByText("REVIEW_EVIDENCE_REQUESTED"),
  ).toBeVisible();

  const confirm = page.getByTestId(/^hypothesis-confirm-btn-/).first();
  await expect(confirm).toBeEnabled();
  await confirm.click();
  await expect(page.getByTestId(TEST_IDS.incidentStatus)).toContainText("resolved");
  await expect(
    page.getByTestId(TEST_IDS.auditTrailPanel).getByText("REVIEW_CONFIRMED"),
  ).toBeVisible();

  await page.getByTestId(TEST_IDS.auditFilter).fill("REVIEW_CONFIRMED");
  await expect(
    page.getByTestId(TEST_IDS.auditTrailPanel).getByText("REVIEW_CONFIRMED"),
  ).toBeVisible();
  expect(backendResponses.some((url) => url.endsWith("/simulator/reset"))).toBe(true);
  expect(backendResponses.some((url) => url.includes("/investigation"))).toBe(true);
  expect(backendResponses.some((url) => url.endsWith("/review"))).toBe(true);
  expect(backendResponses.some((url) => url.endsWith("/audit"))).toBe(true);
});
