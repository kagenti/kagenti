/**
 * Kagenti Home Page Overview Demo
 *
 * A walkthrough demo covering:
 *   1. Home page statistics and layout
 *   2. Quick action cards
 *   3. Theme switching (light/dark)
 *   4. Navigation sidebar structure
 *   5. User menu
 *
 * Environment variables (set by run-playwright-demo.sh):
 *   KAGENTI_UI_URL   - Base URL of the Kagenti UI
 *   KEYCLOAK_USER    - Keycloak username
 *   KEYCLOAK_PASS    - Keycloak password
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

test.describe('Kagenti Home Page Overview', () => {
  test.describe.configure({ mode: 'serial' });

  test('Home page walkthrough: stats, actions, theme, navigation', async ({ page }) => {
    test.setTimeout(180000); // 3 minutes

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
    // ASSERT: Page loaded
    await expect(page).toHaveURL(/./);
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

      // Handle VERIFY_PROFILE (optional — not all logins trigger this)
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

    // ASSERT: We're on the Kagenti UI (not stuck on Keycloak)
    expect(page.url()).not.toContain('/realms/');

    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // STEP 3: Home page statistics
    // ================================================================
    markStep('home_stats');
    console.log('[demo] Step 3: Show home page statistics');

    // Wait for stats cards to load (they fetch data via React Query)
    await page.waitForTimeout(PAUSE);

    // ASSERT: Cards are visible on the home page
    const statCards = page.locator('.pf-v5-c-card').or(page.locator('[class*="card"]'));
    const cardCount = await statCards.count();
    console.log(`[demo] Found ${cardCount} cards on home page`);
    expect(cardCount, 'Home page should have at least 1 card').toBeGreaterThan(0);

    // Hover over each stat card to highlight them
    for (let i = 0; i < Math.min(cardCount, 4); i++) {
      const card = statCards.nth(i);
      if (await card.isVisible({ timeout: 2000 }).catch(() => false)) {
        const box = await card.boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(800);
        }
      }
    }
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 4: Quick action cards
    // ================================================================
    markStep('home_actions');
    console.log('[demo] Step 4: Show quick action cards');

    // Scroll down to see action cards
    await page.mouse.wheel(0, 300);
    await page.waitForTimeout(PAUSE);

    // ASSERT: Quick action cards are visible (View Agents, View Tools, etc.)
    // These are PatternFly Button variant="link" with onClick, not <a> tags
    const actionButtons = page.getByRole('button', { name: /View Agents|View Tools|View Dashboards|Open Admin/i });
    const actionCount = await actionButtons.count();
    expect(actionCount, 'Home page should have quick action buttons (View Agents/Tools/Dashboards/Admin)').toBeGreaterThan(0);

    for (let i = 0; i < Math.min(actionCount, 4); i++) {
      const btn = actionButtons.nth(i);
      if (await btn.isVisible({ timeout: 2000 }).catch(() => false)) {
        const box = await btn.boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(600);
        }
      }
    }
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 5: Theme switching
    // ================================================================
    markStep('home_theme');
    console.log('[demo] Step 5: Theme switching');

    // Look for theme selector in the toolbar
    const themeButton = page.locator('button:has-text("Theme")')
      .or(page.locator('[aria-label*="theme" i]'))
      .or(page.locator('button:has-text("Light")')
      .or(page.locator('button:has-text("Dark")')));

    // ASSERT: Theme selector exists
    await expect(themeButton.first()).toBeVisible({ timeout: 5000 });
    await demoClick(themeButton.first(), 'Theme selector');
    await page.waitForTimeout(500);

    // Click Dark theme option
    const darkOption = page.getByText('Dark', { exact: true })
      .or(page.locator('[role="menuitem"]:has-text("Dark")'));
    if (await darkOption.first().isVisible({ timeout: 2000 }).catch(() => false)) {
      await demoClick(darkOption.first(), 'Dark theme');
      await page.waitForTimeout(LONG_PAUSE);
    }

    // Switch back to Light
    if (await themeButton.first().isVisible({ timeout: 2000 }).catch(() => false)) {
      await demoClick(themeButton.first(), 'Theme selector');
      await page.waitForTimeout(500);
      const lightOption = page.getByText('Light', { exact: true })
        .or(page.locator('[role="menuitem"]:has-text("Light")'));
      if (await lightOption.first().isVisible({ timeout: 2000 }).catch(() => false)) {
        await demoClick(lightOption.first(), 'Light theme');
        await page.waitForTimeout(PAUSE);
      }
    }

    // ================================================================
    // STEP 6: Navigation sidebar
    // ================================================================
    markStep('home_navigation');
    console.log('[demo] Step 6: Sidebar navigation');

    // Scroll back to top
    await page.mouse.wheel(0, -500);
    await page.waitForTimeout(500);

    // ASSERT: Sidebar navigation exists
    const navItems = page.locator('nav a, [role="navigation"] a');
    const navCount = await navItems.count();
    console.log(`[demo] Found ${navCount} navigation items`);
    expect(navCount, 'Sidebar should have navigation items').toBeGreaterThan(0);

    // Hover through sidebar navigation items
    for (let i = 0; i < navCount; i++) {
      const item = navItems.nth(i);
      if (await item.isVisible({ timeout: 1000 }).catch(() => false)) {
        const box = await item.boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(400);
        }
      }
    }
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 7: User menu
    // ================================================================
    markStep('home_user_menu');
    console.log('[demo] Step 7: User dropdown menu');

    // Find user dropdown in the toolbar
    const userDropdown = page.locator('[aria-label*="user" i]')
      .or(page.locator('button:has-text("admin")')
      .or(page.locator('button:has-text("temp-admin")')))
      .or(page.locator('.pf-v5-c-masthead button').last());

    // ASSERT: User dropdown exists
    await expect(userDropdown.first()).toBeVisible({ timeout: 5000 });
    await demoClick(userDropdown.first(), 'User menu');
    await page.waitForTimeout(LONG_PAUSE);

    // Close the menu
    await page.keyboard.press('Escape');
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // FINAL: End
    // ================================================================
    markStep('end');
    console.log('[demo] Home overview complete!');

    // Write timestamps
    const fs = require('fs');
    const path = require('path');
    const scriptDir = process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, '..');
    const tsFile = path.join(scriptDir, '..', 'home-overview-timestamps.json');
    fs.writeFileSync(tsFile, JSON.stringify(stepTimestamps, null, 2));
    console.log(`[demo] Timestamps written to ${tsFile}`);

    await page.waitForTimeout(10000);
  });
});
