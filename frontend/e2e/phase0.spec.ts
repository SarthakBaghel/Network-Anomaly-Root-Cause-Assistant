import { expect, test } from '@playwright/test'

test('renders the MSW-backed investigation shell', async ({ page }) => {
  await page.goto('/incidents/inc_001')

  await expect(page.getByTestId('investigation-panel')).toBeVisible()
  await expect(page.getByTestId('hypothesis-row-hyp_001')).toContainText('92.1')
  await expect(page.getByTestId('evidence-panel')).toBeVisible()
  await expect(page.getByTestId('topology-graph')).toBeVisible()
  await expect(page.getByTestId('hypothesis-confirm-btn')).toBeVisible()
})
