import { test, expect } from "@playwright/test";

import fixture from "../../src/test-fixtures/golden-investigation-response.json" with { type: "json" };
import {
  TEST_IDS,
  anomalyRowTestId,
  auditRowTestId,
  evidenceItemTestId,
  evidenceRequestTestId,
  evidenceSectionTestId,
  evidenceSectionToggleTestId,
  hypothesisConfirmTestId,
  incidentRowTestId,
  sourceHealthTestId,
} from "../../src/test-fixtures/testid-manifest";

test("golden path exploration and review flow", async ({ page }) => {
  const firstHypothesis = fixture.hypotheses[0];
  const missingEvidence = Object.values(fixture.evidence_by_hypothesis)
    .flat()
    .find((item) => item.kind === "missing");
  if (!missingEvidence) throw new Error("Golden fixture must contain missing evidence");

  await page.goto("/");

  await expect(page.getByTestId(TEST_IDS.incidentList)).toBeVisible();
  await expect(page.getByTestId(sourceHealthTestId("simulator.prometheus"))).toBeVisible();
  await expect(page.getByTestId(sourceHealthTestId("fixture.cmdb_topology"))).toBeVisible();
  await expect(page.getByTestId(TEST_IDS.simulatorState)).toContainText("stopped");

  await page.getByTestId(TEST_IDS.scenarioTrigger).click();
  await expect(page.getByTestId(TEST_IDS.simulatorState)).toContainText("completed");
  await expect(page.getByTestId(anomalyRowTestId("ano_forwarded_rps_001"))).toBeVisible();

  await page.getByTestId(incidentRowTestId(fixture.incident.incident_id)).click();
  await expect(page.getByTestId(TEST_IDS.investigationPanel)).toBeVisible();
  await expect(page.getByTestId(TEST_IDS.timelinePanel)).toBeVisible();
  await expect(page.getByTestId(TEST_IDS.topologyGraph)).toBeVisible();
  await expect(page.getByTestId(TEST_IDS.evidencePanel)).toBeVisible();
  for (const kind of ["observed", "correlated", "conflicting", "missing"]) {
    await expect(page.getByTestId(evidenceSectionTestId(kind))).toBeVisible();
  }

  await page.getByTestId(evidenceSectionToggleTestId("missing")).click();
  await page.getByTestId(evidenceItemTestId(missingEvidence.evidence_id)).click();
  await expect(page.getByTestId(TEST_IDS.eventModal)).toBeVisible();
  await expect(page.getByTestId(TEST_IDS.eventModalBody)).toContainText(missingEvidence.statement);
  await page.getByTestId(TEST_IDS.evidenceCloseModal).click();

  await page.getByTestId(evidenceRequestTestId(firstHypothesis.hypothesis_id)).click();
  await expect(page.getByTestId(auditRowTestId("aud_mock_1"))).toBeVisible();

  await page.getByTestId(hypothesisConfirmTestId(firstHypothesis.hypothesis_id)).click();
  await expect(page.getByTestId(TEST_IDS.incidentStatus)).toContainText("resolved");
  await expect(page.getByTestId(auditRowTestId("aud_mock_2"))).toBeVisible();
  await expect(page.getByTestId(TEST_IDS.auditTrailPanel)).toBeVisible();
});
