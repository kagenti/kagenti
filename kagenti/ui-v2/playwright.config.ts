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
  /* Run tests in files in parallel */
  fullyParallel: true,
  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,
  /* Retry on CI only */
  retries: process.env.CI ? 2 : 0,
  /* Run tests in parallel — 4 workers for speed on both CI and local. */
  workers: process.env.CI ? 4 : undefined,
  /* Reporter to use */
  reporter: [
    ['html', { outputFolder: 'playwright-report' }],
    ['list'],
  ],
  /* Per-test timeout: 60s on CI to accommodate Keycloak OAuth redirects */
  timeout: process.env.CI ? 60000 : 30000,

  /* Assertion timeout: 15s on CI (Keycloak redirect adds latency before elements appear) */
  expect: {
    timeout: process.env.CI ? 15000 : 5000,
  },

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
    /* Auth setup — logs in once and saves storage state for all tests */
    {
      name: 'setup',
      testMatch: /auth\.setup\.ts/,
    },
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        /* Use authenticated state from setup project */
        storageState: 'playwright/.auth/user.json',
      },
      dependencies: ['setup'],
    },
    // Uncomment to test on additional browsers
    // {
    //   name: 'firefox',
    //   use: {
    //     ...devices['Desktop Firefox'],
    //     storageState: 'playwright/.auth/user.json',
    //   },
    //   dependencies: ['setup'],
    // },
    // {
    //   name: 'webkit',
    //   use: {
    //     ...devices['Desktop Safari'],
    //     storageState: 'playwright/.auth/user.json',
    //   },
    //   dependencies: ['setup'],
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
