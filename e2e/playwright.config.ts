import { defineConfig, devices } from "@playwright/test";

// Runs against an instance that is already up, so the same tests check a local build,
// CI, or the hosted demo. PW_CHANNEL=msedge uses an installed Edge instead of a download.
export default defineConfig({
  testDir: "./tests",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8010",
    trace: "retain-on-failure",
  },
  projects: [{ name: "desktop", use: { ...devices["Desktop Chrome"], channel: process.env.PW_CHANNEL } }],
});
