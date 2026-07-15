import { test, expect } from "@playwright/test";

test("golden path exploration and review flow", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator('[data-testid="incident-list"]')).toBeVisible();
  await expect(
    page.locator('[data-testid="source-health-simulator.prometheus"]'),
  ).toBeVisible();
  await expect(
    page.locator('[data-testid="source-health-simulator.syslog"]'),
  ).toBeVisible();

  await expect(page.locator("text=Scenario not triggered")).toBeVisible();
  await page.click('[data-testid="scenario-trigger-btn"]');
  await expect(page.locator("text=Scenario triggered")).toBeVisible();

  await page.click('[data-testid="incident-row-inc_001"]');
  await expect(
    page.locator('[data-testid="investigation-panel"]'),
  ).toBeVisible();
  await expect(page.locator('[data-testid="timeline-panel"]')).toBeVisible();
  await expect(page.locator('[data-testid="topology-graph"]')).toBeVisible();
  await expect(page.locator('[data-testid="evidence-panel"]')).toBeVisible();

  await expect(page.locator("text=Verified observed facts")).toBeVisible();
  await expect(page.locator("text=Correlated signals")).toBeVisible();
  await expect(page.locator("text=Conflicting evidence")).toBeVisible();
  await expect(page.locator("text=Missing evidence")).toBeVisible();

  const confirmButton = page.getByRole("button", { name: /Confirm/i });
  await expect(confirmButton).toBeVisible();
  await confirmButton.click();
  await expect(confirmButton).toBeDisabled();

  await expect(page.locator('[data-testid="audit-trail-panel"]')).toBeVisible();
});
