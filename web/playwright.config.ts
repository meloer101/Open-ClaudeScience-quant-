import { defineConfig, devices } from "@playwright/test";

// End-to-end tests drive the real FastAPI backend and the real Vite dev
// server together (not mocks) - see e2e/global-setup.ts for how a fixture
// run gets seeded into the actual runs/ directory both processes read from.
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  globalTeardown: "./e2e/global-teardown.ts",
  fullyParallel: false,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "uv run uvicorn quantbench.api.server:app --port 8000",
      cwd: "..",
      url: "http://localhost:8000/api/runs",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: "npm run dev",
      url: "http://localhost:5173",
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
  ],
});
