import { defineConfig, devices } from "@playwright/test";

const databaseUrl =
  process.env.LIVE_E2E_DATABASE_URL ??
  "sqlite:////tmp/network-anomaly-rca-playwright-live.db";

export default defineConfig({
  testDir: "tests/e2e",
  testMatch: "**/live_*.spec.ts",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:4173",
    actionTimeout: 20_000,
    trace: "on-first-retry",
  },
  webServer: [
    {
      command: [
        "cd ..",
        `DATABASE_URL=${databaseUrl} .venv/bin/alembic -c backend/alembic.ini upgrade head`,
        `DATABASE_URL=${databaseUrl} PYTHONPATH=backend .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000`,
      ].join(" && "),
      url: "http://127.0.0.1:8000/api/v1/health",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command:
        "VITE_ENABLE_MSW=false VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1 npm run dev -- --host 127.0.0.1 --port 4173",
      url: "http://127.0.0.1:4173",
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
