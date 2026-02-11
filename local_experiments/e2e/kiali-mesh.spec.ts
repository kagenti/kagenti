/**
 * Kagenti Kiali Service Mesh Visualization Demo
 *
 * A deep dive into Kiali service mesh visualization:
 *   1. Login to Kagenti via Keycloak
 *   2. Navigate to Kiali (page.goto KIALI_URL)
 *   3. Handle Kiali OAuth login (OpenShift kubeadmin)
 *   4. Navigate to Traffic Graph
 *   5. Select namespaces
 *   6. Change time range
 *   7. Zoom to fit
 *   8. Enable Security overlay
 *   9. Enable Animation
 *  10. Pause on animated graph
 *
 * Environment variables (set by run-playwright-demo.sh):
 *   KAGENTI_UI_URL   - Base URL of the Kagenti UI
 *   KEYCLOAK_USER    - Keycloak username
 *   KEYCLOAK_PASS    - Keycloak password
 *   KIALI_URL        - Kiali UI URL
 *   KUBEADMIN_PASS   - OpenShift kubeadmin password
 */
import { test, expect } from '@playwright/test';

const PAUSE = 2000;
const LONG_PAUSE = 3000;

// Timestamp tracking for narration sync
const stepTimestamps: { step: string; time: number }[] = [];
const demoStartTime = Date.now();
const markStep = (step: string) => {
  const elapsed = (Date.now() - demoStartTime) / 1000;
  stepTimestamps.push({ step, time: elapsed });
  console.log(`[demo-ts] ${elapsed.toFixed(1)}s — ${step}`);
};

const UI_URL = process.env.KAGENTI_UI_URL || '';
const KC_USER = process.env.KEYCLOAK_USER || 'admin';
const KC_PASS = process.env.KEYCLOAK_PASS || 'admin';
const KIALI_URL = process.env.KIALI_URL || '';
const KUBEADMIN_PASS = process.env.KUBEADMIN_PASS || '';

test.describe('Kiali Service Mesh Demo', () => {
  test.describe.configure({ mode: 'serial' });

  test('Kiali mesh: login, graph, namespaces, security, animation', async ({ page }) => {
    test.setTimeout(300000); // 5 minutes for Kiali OAuth flows

    // ================================================================
    // Cursor tracking and injection
    // ================================================================
    let lastCursorX = 960;
    let lastCursorY = 540;

    const injectCursor = async () => {
      await page.evaluate(([startX, startY]) => {
        if (document.getElementById('pw-cursor')) return;
        const cursor = document.createElement('div');
        cursor.id = 'pw-cursor';
        cursor.style.cssText = `
          width: 20px; height: 20px;
          background: rgba(255, 50, 50, 0.7);
          border: 2px solid rgba(255, 255, 255, 0.9);
          border-radius: 50%;
          position: fixed;
          top: ${startY - 10}px; left: ${startX - 10}px;
          z-index: 999999;
          pointer-events: none;
          transition: transform 0.15s ease;
          box-shadow: 0 0 8px rgba(0,0,0,0.4);
        `;
        document.body.appendChild(cursor);
        document.addEventListener('mousemove', (e) => {
          cursor.style.left = (e.clientX - 10) + 'px';
          cursor.style.top = (e.clientY - 10) + 'px';
        });
        document.addEventListener('mousedown', () => {
          cursor.style.transform = 'scale(0.7)';
          cursor.style.background = 'rgba(255, 50, 50, 0.95)';
        });
        document.addEventListener('mouseup', () => {
          cursor.style.transform = 'scale(1)';
          cursor.style.background = 'rgba(255, 50, 50, 0.7)';
        });
      }, [lastCursorX, lastCursorY]);
      await page.mouse.move(lastCursorX, lastCursorY);
    };

    page.on('load', async () => {
      await injectCursor().catch(() => {});
    });

    const humanMove = async (toX: number, toY: number) => {
      await page.mouse.move(toX, toY, { steps: 25 });
      lastCursorX = toX;
      lastCursorY = toY;
    };

    const demoClick = async (locator: any, description?: string) => {
      if (description) console.log(`[demo] Clicking: ${description}`);
      await locator.scrollIntoViewIfNeeded().catch(() => {});
      const box = await locator.boundingBox();
      if (box) {
        const offsetX = (Math.random() - 0.5) * box.width * 0.2;
        const offsetY = (Math.random() - 0.5) * box.height * 0.2;
        await humanMove(box.x + box.width / 2 + offsetX, box.y + box.height / 2 + offsetY);
        await page.waitForTimeout(200);
      }
      await locator.click();
    };

    // ================================================================
    // STEP 1: Navigate to Kagenti UI
    // ================================================================
    console.log('[demo] Step 1: Navigate to Kagenti UI');
    await page.goto(UI_URL, { waitUntil: 'networkidle', timeout: 30000 });
    await injectCursor();
    markStep('intro');
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 2: Login via Keycloak (if needed)
    // ================================================================
    markStep('login');
    console.log('[demo] Step 2: Login via Keycloak');
    const loginButton = page.getByRole('button', { name: /sign in|login|log in/i })
      .or(page.getByRole('link', { name: /sign in|login|log in/i }));

    if (await loginButton.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(loginButton.first(), 'Sign In button');

      await page.waitForURL(
        (url) => url.toString().includes('/realms/'),
        { timeout: 15000 }
      );
      await page.waitForSelector('#username', { timeout: 10000 });
      await page.waitForTimeout(PAUSE);

      await page.fill('#username', KC_USER);
      await page.waitForTimeout(500);
      await page.fill('#password', KC_PASS);
      await page.waitForTimeout(500);
      await demoClick(page.locator('#kc-login'), 'Keycloak Sign In');

      // Handle VERIFY_PROFILE
      await page.waitForLoadState('domcontentloaded', { timeout: 10000 }).catch(() => {});
      if (page.url().includes('VERIFY_PROFILE') || page.url().includes('required-action')) {
        const emailField = page.locator('#email');
        if (await emailField.isVisible({ timeout: 2000 }).catch(() => false)) {
          if (!(await emailField.inputValue())) await emailField.fill('admin@kagenti.local');
        }
        const firstNameField = page.locator('#firstName');
        if (await firstNameField.isVisible({ timeout: 1000 }).catch(() => false)) {
          if (!(await firstNameField.inputValue())) await firstNameField.fill('Admin');
        }
        const lastNameField = page.locator('#lastName');
        if (await lastNameField.isVisible({ timeout: 1000 }).catch(() => false)) {
          if (!(await lastNameField.inputValue())) await lastNameField.fill('User');
        }
        const submitBtn = page.locator('input[type="submit"], button[type="submit"]');
        if (await submitBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
          await submitBtn.click();
        }
      }

      await page.waitForURL(
        (url) => url.toString().startsWith(UI_URL) && !url.toString().includes('/realms/'),
        { timeout: 30000 }
      );
      await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
      console.log('[demo] Login successful');
    } else {
      console.log('[demo] No login button — auth disabled');
    }

    await page.waitForTimeout(LONG_PAUSE);

    // ASSERT: We're on the Kagenti UI (not stuck on Keycloak)
    expect(page.url()).not.toContain('/realms/');

    // ================================================================
    // STEP 3: Navigate to Kiali
    // ================================================================
    markStep('kiali_navigate');

    if (KIALI_URL) {
      console.log('[demo] Step 3: Navigate to Kiali');
      await page.goto(KIALI_URL, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
      await page.waitForTimeout(PAUSE);

      // ================================================================
      // STEP 4: Handle Kiali OAuth login (OpenShift kubeadmin)
      // ================================================================
      markStep('kiali_login');

      const currentUrl = page.url();
      if (currentUrl.includes('oauth') || currentUrl.includes('login')) {
        console.log('[demo] Kiali requires OpenShift OAuth login');

        if (KUBEADMIN_PASS) {
          // Look for "kube:admin" or "htpasswd" identity provider option
          const kubeadminLink = page.getByRole('link', { name: /kube.*admin|htpasswd|my_htpasswd_provider/i })
            .or(page.locator('a:has-text("kube")'));
          if (await kubeadminLink.first().isVisible({ timeout: 5000 }).catch(() => false)) {
            await demoClick(kubeadminLink.first(), 'kubeadmin identity provider');
            await page.waitForLoadState('domcontentloaded', { timeout: 10000 }).catch(() => {});
          }

          // Fill kubeadmin credentials
          const userField = page.locator('#inputUsername, #username, input[name="username"]');
          const passField = page.locator('#inputPassword, #password, input[name="password"]');
          if (await userField.first().isVisible({ timeout: 5000 }).catch(() => false)) {
            await userField.first().fill('kubeadmin');
            await passField.first().fill(KUBEADMIN_PASS);
            await page.waitForTimeout(500);

            const loginBtn = page.locator('button[type="submit"], input[type="submit"]');
            await demoClick(loginBtn.first(), 'Submit kubeadmin credentials');
            console.log('[demo] Submitted kubeadmin credentials');
            await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
          }

          // Handle OAuth authorize page
          const authorizeBtn = page.getByRole('button', { name: /allow|authorize|approve/i })
            .or(page.locator('input[name="approve"]'));
          if (await authorizeBtn.first().isVisible({ timeout: 5000 }).catch(() => false)) {
            await demoClick(authorizeBtn.first(), 'Authorize OAuth');
            await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
          }
        } else {
          console.log('[demo] No KUBEADMIN_PASS set, skipping Kiali OAuth');
        }
      }

      await injectCursor();
      await page.waitForTimeout(LONG_PAUSE);

      // ================================================================
      // STEP 5: Navigate to Traffic Graph
      // ================================================================
      markStep('kiali_graph');
      console.log('[demo] Step 5: Navigate to Traffic Graph');

      const graphLink = page.getByRole('link', { name: /Traffic Graph/i })
        .or(page.getByRole('link', { name: /Graph/i }))
        .or(page.locator('a[href*="graph"]'));
      if (await graphLink.first().isVisible({ timeout: 5000 }).catch(() => false)) {
        await demoClick(graphLink.first(), 'Traffic Graph');
        await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
        await page.waitForTimeout(PAUSE);
      } else {
        console.log('[demo] Traffic Graph link not found');
      }

      await page.waitForTimeout(LONG_PAUSE);

      // ================================================================
      // STEP 6: Select namespaces
      // ================================================================
      markStep('kiali_namespaces');
      console.log('[demo] Step 6: Select namespaces');

      const nsSelector = page.locator('button:has-text("Select Namespaces")');
      if (await nsSelector.isVisible({ timeout: 5000 }).catch(() => false)) {
        await demoClick(nsSelector, 'Select Namespaces');
        await page.waitForTimeout(500);

        // Click "Select all"
        const selectAll = page.getByText('Select all', { exact: true })
          .or(page.locator('input[aria-label="Select all"]'));
        if (await selectAll.first().isVisible({ timeout: 3000 }).catch(() => false)) {
          await demoClick(selectAll.first(), 'Select all namespaces');
          await page.waitForTimeout(PAUSE);
        }

        // Close the dropdown by clicking elsewhere
        await page.keyboard.press('Escape');
        await page.waitForTimeout(PAUSE);
      } else {
        console.log('[demo] Namespace selector not found');
      }

      // ================================================================
      // STEP 7: Change time range
      // ================================================================
      markStep('kiali_timerange');
      console.log('[demo] Step 7: Change time range');

      const timeRange = page.locator('button:has-text("Last 1m")')
        .or(page.locator('button:has-text("Last 5m")'))
        .or(page.locator('[aria-label*="time range"]'));
      if (await timeRange.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoClick(timeRange.first(), 'Time range selector');
        await page.waitForTimeout(300);
        const fiveMin = page.getByText('Last 5m', { exact: true })
          .or(page.locator('[role="option"]:has-text("5m")'));
        if (await fiveMin.first().isVisible({ timeout: 3000 }).catch(() => false)) {
          await demoClick(fiveMin.first(), 'Last 5 minutes');
        }
        await page.waitForTimeout(PAUSE);
      } else {
        console.log('[demo] Time range selector not found');
      }

      // Wait for graph to render
      await page.waitForTimeout(LONG_PAUSE);

      // Zoom to fit
      const zoomFitButton = page.locator('button[title="Zoom to fit"], button[aria-label="Zoom to fit"]')
        .or(page.locator('#toolbar_zoom_to_fit'))
        .or(page.locator('button:has(svg)').filter({ has: page.locator('[data-icon="expand"]') }));
      if (await zoomFitButton.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoClick(zoomFitButton.first(), 'Zoom to fit');
        await page.waitForTimeout(PAUSE);
      } else {
        console.log('[demo] Zoom to fit button not found, using keyboard shortcut');
        await page.keyboard.press('Control+Shift+f');
        await page.waitForTimeout(PAUSE);
      }

      // ================================================================
      // STEP 8: Enable Security overlay
      // ================================================================
      markStep('kiali_security');
      console.log('[demo] Step 8: Enable Security overlay');

      const displayDropdown = page.locator('button:has-text("Display")');
      if (await displayDropdown.isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoClick(displayDropdown, 'Display options');
        await page.waitForTimeout(500);

        // Toggle Security
        const securityToggle = page.getByText('Security', { exact: true })
          .or(page.locator('label:has-text("Security")'));
        if (await securityToggle.first().isVisible({ timeout: 3000 }).catch(() => false)) {
          await demoClick(securityToggle.first(), 'Security toggle');
          await page.waitForTimeout(500);
        }

        await page.waitForTimeout(PAUSE);
      } else {
        console.log('[demo] Display dropdown not found');
      }

      // ================================================================
      // STEP 9: Enable Animation
      // ================================================================
      markStep('kiali_animation');
      console.log('[demo] Step 9: Enable Animation');

      // Display dropdown may still be open, or re-open it
      if (!(await displayDropdown.isVisible({ timeout: 1000 }).catch(() => false))) {
        // Display dropdown closed, no need to re-open for animation if it was part of same menu
      }

      // Try to find animation toggle (may be in same Display dropdown)
      const animationToggle = page.getByText('Animation', { exact: true })
        .or(page.locator('label:has-text("Animation")'));
      if (await animationToggle.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoClick(animationToggle.first(), 'Animation toggle');
        await page.waitForTimeout(500);
      } else {
        // Re-open Display dropdown to find Animation
        if (await displayDropdown.isVisible({ timeout: 2000 }).catch(() => false)) {
          await demoClick(displayDropdown, 'Display options (re-open)');
          await page.waitForTimeout(500);
          if (await animationToggle.first().isVisible({ timeout: 3000 }).catch(() => false)) {
            await demoClick(animationToggle.first(), 'Animation toggle');
            await page.waitForTimeout(500);
          }
        }
      }

      // Close display dropdown
      await page.keyboard.press('Escape');
      await page.waitForTimeout(PAUSE);

      // Let the animated graph render for a few seconds
      console.log('[demo] Showing Kiali traffic graph with security and animation...');
      await page.waitForTimeout(5000);

    } else {
      console.log('[demo] Kiali URL not set, skipping Kiali sections');
      markStep('kiali_login');
      markStep('kiali_graph');
      markStep('kiali_namespaces');
      markStep('kiali_timerange');
      markStep('kiali_security');
      markStep('kiali_animation');
    }

    // ================================================================
    // FINAL: End
    // ================================================================
    markStep('end');
    console.log('[demo] Kiali service mesh demo complete!');

    // Write timestamps
    const fs = require('fs');
    const path = require('path');
    const scriptDir = process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, '..');
    const tsFile = path.join(scriptDir, '..', 'kiali-mesh-timestamps.json');
    fs.writeFileSync(tsFile, JSON.stringify(stepTimestamps, null, 2));
    console.log(`[demo] Timestamps written to ${tsFile}`);

    await page.waitForTimeout(10000);
  });
});
