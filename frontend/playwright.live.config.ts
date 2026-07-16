import { defineConfig, devices } from "@playwright/test";

const databaseUrl =
  process.env.LIVE_E2E_DATABASE_URL ??
  "sqlite:////tmp/network-anomaly-rca-playwright-live.db";
const apiPort = process.env.LIVE_E2E_API_PORT ?? "8000";
const frontendPort = process.env.LIVE_E2E_FRONTEND_PORT ?? "4173";
const apiOrigin = `http://127.0.0.1:${apiPort}`;
const frontendOrigin = `http://127.0.0.1:${frontendPort}`;

export default defineConfig({
  testDir: "tests/e2e",
  testMatch: "**/live_*.spec.ts",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: frontendOrigin,
    actionTimeout: 20_000,
    trace: "on-first-retry",
  },
  webServer: [
    {
      command: [
        "cd ..",
        `DATABASE_URL=${databaseUrl} .venv/bin/alembic -c backend/alembic.ini upgrade head`,
        `DATABASE_URL=${databaseUrl} PYTHONPATH=backend .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port ${apiPort}`,
      ].join(" && "),
      url: `${apiOrigin}/api/v1/health`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command:
        `VITE_ENABLE_MSW=false VITE_API_BASE_URL=${apiOrigin}/api/v1 npm run dev -- --host 127.0.0.1 --port ${frontendPort}`,
      url: frontendOrigin,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
  projects: [
    {
      name: "chromium-live-backend",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
