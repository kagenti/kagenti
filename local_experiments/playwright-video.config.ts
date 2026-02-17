/**
 * Playwright Video Recording Config
 *
 * Standalone config for recording Playwright test runs with video.
 * Used by run-playwright-demo.sh — not meant for CI.
 *
 * Environment variables:
 *   KAGENTI_UI_URL       - Base URL of the Kagenti UI (required)
 *   PLAYWRIGHT_TEST_DIR  - Path to the e2e test directory (set by run-playwright-demo.sh)
 *   PLAYWRIGHT_OUTPUT_DIR - Path for test artifacts output (set by run-playwright-demo.sh)
 */
import { defineConfig, devices } from '@playwright/test';
import * as path from 'path';

const testDir = process.env.PLAYWRIGHT_TEST_DIR || path.join(__dirname, '..', 'kagenti', 'ui-v2', 'e2e');
const outputDir = process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, 'test-results');

export default defineConfig({
  testDir,
  outputDir,

  fullyParallel: false,   // sequential for coherent video recording
  retries: 0,             // no retries for demo recording
  workers: 1,             // single worker for sequential execution

  reporter: [['list']],

  globalSetup: path.join(__dirname, 'keycloak-auth-setup.ts'),

  use: {
    baseURL: process.env.KAGENTI_UI_URL,

    // Video recording — the main purpose of this config
    video: {
      mode: 'on',
      size: { width: 1920, height: 1080 },
    },

    // Slow down actions for demo-quality pacing
    launchOptions: {
      slowMo: 500,
    },

    // Screenshots at each step
    screenshot: 'on',

    // Collect traces for debugging
    trace: 'on',

    // Accept self-signed certs (HyperShift/OpenShift routes)
    ignoreHTTPSErrors: true,

    // Use saved Keycloak auth state
    storageState: path.join(__dirname, '.auth', 'state.json'),

    // Viewport for consistent recording
    viewport: { width: 1920, height: 1080 },
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  // No dev server — always run against a live cluster
});
