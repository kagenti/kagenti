import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright configuration for Kagenti UI E2E tests.
 *
 * Environment Variables:
 *   KAGENTI_UI_URL: The base URL for the UI (default: http://localhost:5173)
 *   CI: Set to any value to enable CI mode (screenshots, traces on failure)
 *
 * Usage:
 *   npm run test:e2e           # Run all E2E tests
 *   npm run test:e2e:ui        # Run with Playwright UI
 *   npm run test:e2e:debug     # Run in debug mode
 *
 * For Kind cluster:
 *   # Start the backend port-forward
 *   kubectl port-forward -n kagenti-system svc/kagenti-backend 8000:8000
 *   # Start the UI dev server
 *   npm run dev
 *   # Run tests
 *   npm run test:e2e
 *
 * For OpenShift:
 *   KAGENTI_UI_URL=https://kagenti-ui.apps.cluster.example.com npm run test:e2e
 */
export default defineConfig({
  testDir: './e2e',
  /* Ignore demo specs — those are for video recording only */
  testIgnore: ['**/demos/**'],
  /* Run tests in files in parallel */
  fullyParallel: true,
  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,
  /* Retry on CI only */
  retries: process.env.CI ? 2 : 0,
  /* Opt out of parallel tests on CI. */
  workers: process.env.CI ? 1 : undefined,
  /* Reporter to use */
  reporter: [
    ['html', { outputFolder: 'playwright-report' }],
    ['list'],
  ],
  /* Shared settings for all the projects below */
  use: {
    /* Base URL to use in actions like `await page.goto('/')`. */
    baseURL: process.env.KAGENTI_UI_URL || 'http://localhost:3000',

    /* Collect trace when retrying the failed test */
    trace: 'on-first-retry',

    /* Take screenshot on failure */
    screenshot: 'only-on-failure',

    /* Accept self-signed certificates (HyperShift/OpenShift routes use cluster CA) */
    ignoreHTTPSErrors: true,
  },

  /* Configure projects for major browsers */
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    // Uncomment to test on additional browsers
    // {
    //   name: 'firefox',
    //   use: { ...devices['Desktop Firefox'] },
    // },
    // {
    //   name: 'webkit',
    //   use: { ...devices['Desktop Safari'] },
    // },
  ],

  /* Run your local dev server before starting the tests */
  webServer: process.env.KAGENTI_UI_URL ? undefined : {
    command: 'npm run dev',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 120 * 1000,
  },
});
