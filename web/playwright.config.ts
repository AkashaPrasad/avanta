import { defineConfig, devices } from '@playwright/test'

/** AVANTA end-to-end suite.
 *
 *  Every spec drives the real built application through a real browser and
 *  stubs only the HTTP boundary, so a passing run means the interface renders
 *  and behaves — not that a mock returned what a mock was told to return.
 *
 *  The dev server is started with VITE_API_BASE pointed at its own origin so
 *  that every API call is same-origin and can be intercepted by page.route()
 *  without a CORS preflight in the way. Nothing in the suite touches a live
 *  satellite, AIS or reanalysis endpoint.
 */

const PORT = Number(process.env.E2E_PORT ?? 5173)
const BASE_URL = `http://localhost:${PORT}`

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  // trace is captured on the first retry, so at least one retry has to exist.
  retries: process.env.CI ? 2 : 1,
  workers: process.env.CI ? 2 : undefined,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  timeout: 60_000,
  expect: { timeout: 15_000 },

  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    colorScheme: 'dark',
    // Entry animations fade text in over half a second. Auditing or measuring
    // mid-fade reads a transient colour that no user ever sees for long enough
    // to matter, and makes every run depend on when the frame was captured.
    // The app honours prefers-reduced-motion, so the suite runs settled.
    reducedMotion: 'reduce',
  },

  projects: [
    {
      name: 'desktop-1440x900',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'laptop-1024x768',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1024, height: 768 } },
    },
    {
      name: 'tablet-768x1024',
      use: { ...devices['Desktop Chrome'], viewport: { width: 768, height: 1024 } },
    },
  ],

  webServer: {
    command: `npx vite --port ${PORT} --strictPort`,
    url: BASE_URL,
    reuseExistingServer: true,
    timeout: 120_000,
    stdout: 'ignore',
    stderr: 'pipe',
    env: {
      // Same-origin API base: page.route('**/api/v1/**') then intercepts every
      // call with no cross-origin preflight to service.
      VITE_API_BASE: BASE_URL,
    },
  },
})
