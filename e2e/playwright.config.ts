import { defineConfig, devices } from "@playwright/test";

/**
 * Browser tests against the running local stack (`make up && make demo`).
 *
 *   pnpm test       user journeys (project e2e)
 *   pnpm qa         crawl every page at desktop and mobile widths (project qa)
 *   pnpm capture    README screenshots and the tour GIF (project capture)
 *
 * The suites share one demo database, so they run in a single worker, in file order.
 */
const desktop = { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } };

export default defineConfig({
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  outputDir: "test-results",
  use: {
    baseURL: process.env.WEB_URL ?? "http://localhost:3130",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "e2e", testDir: "tests", use: desktop },
    { name: "qa", testDir: "qa", use: desktop },
    {
      name: "capture",
      testDir: "capture",
      use: { ...desktop, deviceScaleFactor: 2, colorScheme: "light" },
    },
  ],
});
