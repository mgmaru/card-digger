/**
 * The acceptance flow (MVP specification section 11).
 *
 * Drives the real screens through the real backend. The backend it talks to is
 * `scripts/acceptance_app.py`, which is the same application wired to a
 * marketplace in memory — not a second one that behaves similarly. Nothing
 * here reaches Mercari, which is what lets this run in CI at all.
 *
 * Both servers are started by Playwright and stopped with it, so a run leaves
 * nothing behind and cannot silently pass against a stale process.
 */

import { defineConfig, devices } from "@playwright/test";

const BACKEND = "http://127.0.0.1:8000";
const FRONTEND = "http://127.0.0.1:5173";

export default defineConfig({
  testDir: "./e2e",
  // Vitest owns `tests/`; this owns `e2e/`. Neither ever sees the other's
  // files, so `vitest run` and `playwright test` cannot pick up each other's.
  fullyParallel: false,
  // One at a time. Both projects drive the same backend process, and the
  // acceptance app deliberately keeps one collection in flight at a time.
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],
  use: {
    baseURL: FRONTEND,
    trace: "retain-on-failure",
  },

  /**
   * Two widths, not four.
   *
   * The visual direction changes exactly four variables below 600px, so the
   * branch is settled by stepping either side of that boundary once. 390px is
   * inside the narrow case, where the grid floor drops to 150px and two
   * columns is the minimum; 1280px is the ordinary desktop width.
   *
   * Chromium only. This is a single user running locally, and adding WebKit is
   * a line in this file on the day that stops being true.
   */
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } },
    },
    {
      name: "mobile",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 390, height: 844 },
        isMobile: false,
        hasTouch: true,
      },
    },
  ],

  webServer: [
    {
      command:
        "uv run --frozen uvicorn --factory scripts.acceptance_app:create_acceptance_app --port 8000",
      cwd: "../backend",
      url: `${BACKEND}/api/health`,
      reuseExistingServer: !process.env.CI,
      stdout: "ignore",
      stderr: "pipe",
      timeout: 60_000,
    },
    {
      command: "npm run dev",
      url: FRONTEND,
      reuseExistingServer: !process.env.CI,
      stdout: "ignore",
      stderr: "pipe",
      timeout: 60_000,
    },
  ],
});
