/**
 * Kagenti Platform Walkthrough Demo
 *
 * A single end-to-end test that demonstrates the full Kagenti workflow:
 *   1. Login to Kagenti via Keycloak
 *   2. Navigate to Agent Catalog
 *   3. Open the weather agent and send a query
 *   4. Wait for the agent response
 *   5. Navigate to MLflow to view experiment traces
 *   6. Navigate to Kiali to view service mesh traffic
 *
 * This test is designed for VIDEO RECORDING — it uses deliberate pauses
 * between actions so the viewer can follow along.
 *
 * Environment variables (set by run-playwright-demo.sh):
 *   KAGENTI_UI_URL   - Base URL of the Kagenti UI
 *   KEYCLOAK_USER    - Keycloak username
 *   KEYCLOAK_PASS    - Keycloak password
 *   MLFLOW_URL       - MLflow UI URL
 *   KIALI_URL        - Kiali UI URL
 *   PHOENIX_URL      - Phoenix UI URL (optional, alternative to MLflow)
 */
import { test, expect } from '@playwright/test';
import { demoLogin, KC_USER, KC_PASS } from './demo-auth';

// Demo pacing — pause so the viewer can see what's happening
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
const MLFLOW_URL = process.env.MLFLOW_URL || '';
const KIALI_URL = process.env.KIALI_URL || '';
const PHOENIX_URL = process.env.PHOENIX_URL || '';
const KUBEADMIN_PASS = process.env.KUBEADMIN_PASS || '';

test.describe('Kagenti Platform Walkthrough', () => {
  // Use a single browser context for the entire walkthrough (keeps auth state)
  test.describe.configure({ mode: 'serial' });

  test('Full platform demo: login → agent chat → traces → mesh', async ({ page }) => {
    test.setTimeout(300000); // 5 minutes for the full walkthrough

    // ================================================================
    // Track cursor position across navigations
    // ================================================================
    let lastCursorX = 960;  // Start at center of 1920x1080
    let lastCursorY = 540;

    // Inject a visible cursor follower (headless Playwright doesn't render cursor)
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
      // Restore Playwright's internal mouse position to match
      await page.mouse.move(lastCursorX, lastCursorY);
    };

    // Re-inject cursor after every navigation (page.goto resets the DOM)
    page.on('load', async () => {
      await injectCursor().catch(() => {});
    });

    // Helper: smooth continuous mouse movement to a target point
    const humanMove = async (toX: number, toY: number) => {
      await page.mouse.move(toX, toY, { steps: 25 });
      lastCursorX = toX;
      lastCursorY = toY;
    };

    // Helper: hover over element with smooth movement, brief pause, then click
    const demoClick = async (locator: any, description?: string) => {
      if (description) console.log(`[demo] Clicking: ${description}`);
      await locator.scrollIntoViewIfNeeded().catch(() => {});
      const box = await locator.boundingBox();
      if (box) {
        const offsetX = (Math.random() - 0.5) * box.width * 0.2;
        const offsetY = (Math.random() - 0.5) * box.height * 0.2;
        await humanMove(box.x + box.width / 2 + offsetX, box.y + box.height / 2 + offsetY);
        await page.waitForTimeout(200); // Brief hover before click
      }
      await locator.click();
    };

    // ================================================================
    // STEP 1: Navigate to Kagenti UI (go immediately to avoid white screen)
    // ================================================================
    console.log('[demo] Step 1: Navigate to Kagenti UI');
    await page.goto(UI_URL, { waitUntil: 'networkidle', timeout: 30000 });
    await injectCursor();
    markStep('intro');
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 2: Login via Keycloak (if Sign In button is visible)
    // ================================================================
    markStep('login');
    await demoLogin(page, demoClick);

    // Show the home page
    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // Helper: handle Keycloak re-auth if needed after navigation
    // ================================================================
    const handleKeycloakReauth = async () => {
      // Wait briefly for any Keycloak redirect to settle
      await page.waitForTimeout(2000);
      const url = page.url();

      // Check if redirected to Keycloak or got login_required error
      if (url.includes('/realms/') || url.includes('login_required')) {
        console.log('[demo] Auth redirect detected, re-authenticating...');

        if (url.includes('/realms/')) {
          // Already on Keycloak login page
          await page.waitForSelector('#username', { timeout: 10000 });
          await page.fill('#username', KC_USER);
          await page.fill('#password', KC_PASS);
          await page.click('#kc-login');
        } else {
          // Got bounced back with error — click Sign In again
          const reLoginBtn = page.getByRole('button', { name: /sign in|login/i });
          if (await reLoginBtn.first().isVisible({ timeout: 3000 }).catch(() => false)) {
            await reLoginBtn.first().click();
            await page.waitForSelector('#username', { timeout: 10000 });
            await page.fill('#username', KC_USER);
            await page.fill('#password', KC_PASS);
            await page.click('#kc-login');
          }
        }

        // Handle VERIFY_PROFILE
        await page.waitForLoadState('domcontentloaded', { timeout: 10000 }).catch(() => {});
        if (page.url().includes('required-action')) {
          const submitBtn = page.locator('input[type="submit"], button[type="submit"]');
          if (await submitBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
            await submitBtn.click();
          }
        }

        await page.waitForURL(
          (u) => u.toString().startsWith(UI_URL) && !u.toString().includes('/realms/'),
          { timeout: 30000 }
        ).catch(() => {});
        await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
        console.log(`[demo] Re-auth complete, URL: ${page.url()}`);
      }
    };

    // ================================================================
    // STEP 3: Navigate to Agent Catalog (via sidebar — SPA routing)
    // ================================================================
    markStep('agent_catalog');
    console.log('[demo] Step 3: Navigate to Agent Catalog');

    // IMPORTANT: Use sidebar clicks for SPA client-side routing.
    // page.goto() causes a full reload which loses the Keycloak JS tokens.
    const agentsLink = page.locator('nav a, [role="navigation"] a').filter({ hasText: /^Agents$/ });
    await demoClick(agentsLink.first(), 'Agents sidebar link').catch(async () => {
      await demoClick(page.getByRole('link', { name: /Agents/i }).first(), 'Agents link');
    });

    // Wait for agent catalog content to appear (SPA navigation)
    await page.waitForURL('**/agents', { timeout: 10000 }).catch(() => {});
    console.log(`[demo] Agent catalog URL: ${page.url()}`);

    // Wait for the heading to confirm page loaded
    const catalogHeading = page.getByRole('heading', { name: /Agent Catalog/i });
    await catalogHeading.waitFor({ timeout: 15000 }).catch(() => {
      console.log('[demo] Agent Catalog heading not found');
    });

    // Select the team1 namespace if needed (the agent list may require it)
    const nsSelector = page.locator('[aria-label="Select namespace"]')
      .or(page.getByRole('button', { name: /team1|Select namespace|namespace/i }));
    if (await nsSelector.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await nsSelector.first().click();
      await page.waitForTimeout(500);
      const team1Option = page.getByText('team1', { exact: true })
        .or(page.locator('[role="option"]').filter({ hasText: 'team1' }));
      if (await team1Option.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await team1Option.first().click();
        console.log('[demo] Selected team1 namespace');
        await page.waitForTimeout(PAUSE);
      }
    }

    // Wait for table to load with agent data
    await page.waitForTimeout(LONG_PAUSE);
    console.log(`[demo] Page content loaded, looking for agents...`);

    // ================================================================
    // STEP 4: Click on the Weather Agent (SPA routing)
    // ================================================================
    markStep('agent_detail');
    console.log('[demo] Step 4: Open weather-service agent');

    // Wait for the weather-service to appear (may take a moment after namespace selection)
    const weatherAgent = page.getByRole('button', { name: 'weather-service' })
      .or(page.getByText('weather-service', { exact: true }));
    if (await weatherAgent.first().isVisible({ timeout: 20000 }).catch(() => false)) {
      await weatherAgent.first().click();
      // Wait for SPA navigation to agent detail page
      await page.waitForURL('**/agents/**/**', { timeout: 10000 }).catch(() => {});
      console.log(`[demo] Agent detail URL: ${page.url()}`);
    } else {
      // Log page content for debugging
      const pageText = await page.locator('main, [class*="content"]').first().textContent().catch(() => '');
      console.log(`[demo] weather-service not found. Page text: "${pageText?.substring(0, 200)}"`);
      console.log(`[demo] Current URL: ${page.url()}`);
    }
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 5: Open Chat tab and send a query
    // ================================================================
    markStep('agent_chat');
    console.log('[demo] Step 5: Chat with the weather agent');

    // Wait for agent detail page to load fully
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(PAUSE);

    // Click on the Chat tab — try multiple selector strategies
    const chatTabSelectors = [
      page.getByRole('tab', { name: /Chat/i }),
      page.locator('button:has-text("Chat")'),
      page.locator('[data-ouia-component-id*="chat" i]'),
      page.locator('.pf-v5-c-tabs__link:has-text("Chat")'),
      // PatternFly tabs: the tab item text
      page.locator('li button').filter({ hasText: /Chat/i }),
    ];

    let chatTabFound = false;
    for (const selector of chatTabSelectors) {
      if (await selector.first().isVisible({ timeout: 2000 }).catch(() => false)) {
        console.log('[demo] Found Chat tab, clicking...');
        await selector.first().click();
        chatTabFound = true;
        await page.waitForTimeout(PAUSE);
        break;
      }
    }

    if (!chatTabFound) {
      console.log('[demo] Chat tab not found via selectors, trying tab by index...');
      // PatternFly tabs: try clicking the second tab (index 1, since first is usually "Details")
      const allTabs = page.locator('[role="tab"]');
      const tabCount = await allTabs.count();
      console.log(`[demo] Found ${tabCount} tabs`);
      for (let i = 0; i < tabCount; i++) {
        const tabText = await allTabs.nth(i).textContent();
        console.log(`[demo]   Tab ${i}: "${tabText?.trim()}"`);
      }
      // Click the tab containing "Chat" text
      for (let i = 0; i < tabCount; i++) {
        const tabText = await allTabs.nth(i).textContent() || '';
        if (tabText.toLowerCase().includes('chat')) {
          await allTabs.nth(i).click();
          chatTabFound = true;
          await page.waitForTimeout(PAUSE);
          break;
        }
      }
    }

    // Type a message
    const chatInputSelectors = [
      page.locator('[aria-label="Chat message input"]'),
      page.locator('textarea'),
      page.locator('[placeholder*="message" i]'),
      page.locator('[placeholder*="type" i]'),
    ];

    let chatInput = null;
    for (const selector of chatInputSelectors) {
      if (await selector.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        chatInput = selector.first();
        break;
      }
    }

    if (chatInput) {
      await chatInput.fill('What is the weather in San Francisco?');
      await page.waitForTimeout(PAUSE);

      // Click Send
      const sendButton = page.getByRole('button', { name: /Send/i })
        .or(page.locator('button:has(svg)').last());  // Paper plane icon button
      if (await sendButton.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await sendButton.first().click();
        console.log('[demo] Message sent, waiting for response...');
      }

      // Wait for the response
      await page.waitForTimeout(LONG_PAUSE);

      // Wait for streaming to complete
      try {
        await page.waitForFunction(
          () => {
            const messages = document.querySelectorAll('[style*="flex-start"] p, [style*="flex-start"] div');
            return messages.length > 0;
          },
          { timeout: 60000 }
        );
        console.log('[demo] Agent responded');
      } catch {
        console.log('[demo] Response wait timed out (agent may be slow)');
      }

      await page.waitForTimeout(LONG_PAUSE);

      // Show events panel if visible (streaming agents show events)
      markStep('agent_events');
      const eventsPanel = page.locator('button:has-text("Events")')
        .or(page.getByText('Events', { exact: true }));
      if (await eventsPanel.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoClick(eventsPanel.first(), 'Events panel');
        await page.waitForTimeout(LONG_PAUSE);
      } else {
        // Scroll down to show the full response
        await page.mouse.wheel(0, 200);
        await page.waitForTimeout(LONG_PAUSE);
      }
    } else {
      console.log('[demo] Chat input not found after trying all selectors');
      console.log(`[demo] Current URL: ${page.url()}`);
      await page.waitForTimeout(PAUSE);
    }

    // ================================================================
    // STEP 6: Navigate to MLflow to view traces
    // ================================================================
    if (MLFLOW_URL) {
      markStep('mlflow');
      console.log('[demo] Step 6: Navigate to MLflow');
      await page.goto(MLFLOW_URL, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
      await page.waitForTimeout(2000);

      // MLflow uses mlflow-oidc-auth plugin — two-stage login:
      //   1. MLflow's own OIDC login page at /oidc/ui/auth (has a "Sign in" button)
      //   2. Keycloak login page (fill credentials)
      //   3. Redirect back to MLflow

      // Stage 1: MLflow's OIDC login page — find and click any sign-in element
      if (page.url().includes('/oidc/') || page.url().includes('/auth') || page.url().includes('login')) {
        console.log('[demo] MLflow login page detected');
        await injectCursor();
        await page.waitForTimeout(LONG_PAUSE); // Show the login page in the video

        // Try multiple strategies to find the sign-in element
        const signInSelectors = [
          page.getByRole('button', { name: /sign in|login|log in/i }),
          page.getByRole('link', { name: /sign in|login|log in|keycloak|oidc/i }),
          page.locator('a:has-text("Sign in")'),
          page.locator('a:has-text("Login")'),
          page.locator('button:has-text("Sign in")'),
          page.locator('input[type="submit"]'),
          // MLflow OIDC plugin often has a simple link or form
          page.locator('a[href*="oidc"]'),
          page.locator('a[href*="login"]'),
          page.locator('form input[type="submit"], form button[type="submit"]'),
        ];

        let clicked = false;
        for (const selector of signInSelectors) {
          if (await selector.first().isVisible({ timeout: 1000 }).catch(() => false)) {
            const text = await selector.first().textContent().catch(() => '');
            await demoClick(selector.first(), `MLflow login (${text?.trim()})`);
            clicked = true;
            await page.waitForLoadState('domcontentloaded', { timeout: 15000 }).catch(() => {});
            await page.waitForTimeout(1000);
            break;
          }
        }

        if (!clicked) {
          // Log what's on the page for debugging
          const allLinks = await page.evaluate(() => {
            return Array.from(document.querySelectorAll('a, button, input')).map(e => ({
              tag: e.tagName, text: (e as any).textContent?.trim()?.substring(0, 50),
              href: (e as any).href || '', type: (e as any).type || ''
            }));
          });
          console.log(`[demo] No MLflow sign-in element found. Page elements: ${JSON.stringify(allLinks.slice(0, 10))}`);
          await page.waitForTimeout(PAUSE);
        }
      }

      // Stage 2: Keycloak login page (if not auto-logged in from existing session)
      if (page.url().includes('/realms/')) {
        console.log('[demo] MLflow redirected to Keycloak');
        const kcUsername = page.locator('#username');
        if (await kcUsername.isVisible({ timeout: 5000 }).catch(() => false)) {
          await page.fill('#username', KC_USER);
          await page.fill('#password', KC_PASS);
          await demoClick(page.locator('#kc-login'), 'MLflow Keycloak login');

          // Handle VERIFY_PROFILE if needed
          await page.waitForLoadState('domcontentloaded', { timeout: 10000 }).catch(() => {});
          if (page.url().includes('required-action')) {
            const submitBtn = page.locator('input[type="submit"], button[type="submit"]');
            if (await submitBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
              await submitBtn.click();
            }
          }
        }

        // Wait for redirect back to MLflow
        await page.waitForURL(
          (url) => !url.toString().includes('/realms/'),
          { timeout: 30000 }
        ).catch(() => {});
      }

      await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});

      // After OIDC login, MLflow may land on callback page — navigate to root
      if (!page.url().includes('#/experiments') && !page.url().endsWith('/')) {
        console.log(`[demo] MLflow post-login URL: ${page.url()}, navigating to root...`);
        await page.goto(MLFLOW_URL, { waitUntil: 'networkidle', timeout: 30000 }).catch(() => {});
      }

      await injectCursor();
      console.log(`[demo] MLflow loaded: ${page.url()}`);
      await page.waitForTimeout(LONG_PAUSE);

      // Navigate directly to the experiments list using hash routing
      markStep('mlflow_experiments');
      await page.goto(`${MLFLOW_URL}/#/experiments`, { waitUntil: 'networkidle', timeout: 15000 }).catch(() => {});
      await injectCursor();
      await page.waitForTimeout(LONG_PAUSE);
      console.log(`[demo] MLflow experiments: ${page.url()}`);

      // Click on "Default" experiment (experiment ID 0)
      const defaultExp = page.locator('a[href*="#/experiments/"]').first();
      if (await defaultExp.isVisible({ timeout: 8000 }).catch(() => false)) {
        await demoClick(defaultExp, 'Default experiment');
        await page.waitForTimeout(LONG_PAUSE);

        // Dismiss the "GenAI apps & agents" experiment type popup if present
        const confirmBtn = page.getByText('Confirm', { exact: true });
        if (await confirmBtn.first().isVisible({ timeout: 2000 }).catch(() => false)) {
          await confirmBtn.first().click({ force: true });
          console.log('[demo] Dismissed MLflow experiment type popup');
          await page.waitForTimeout(500);
        }

        // Click on "Traces" tab in the experiment view
        const tracesTab = page.locator('a[href*="/traces"]')
          .or(page.getByRole('tab', { name: /Traces/i }));
        if (await tracesTab.first().isVisible({ timeout: 5000 }).catch(() => false)) {
          await demoClick(tracesTab.first(), 'Traces tab');
          await page.waitForTimeout(LONG_PAUSE);
        } else {
          // Try direct hash navigation to traces
          console.log('[demo] Traces tab not found, navigating directly');
          await page.goto(`${MLFLOW_URL}/#/experiments/0/traces`, { waitUntil: 'networkidle', timeout: 15000 }).catch(() => {});
          await injectCursor();
          await page.waitForTimeout(LONG_PAUSE);
        }

        // Dismiss popup if it appeared
        if (await confirmBtn.first().isVisible({ timeout: 1000 }).catch(() => false)) {
          await confirmBtn.first().click({ force: true });
          await page.waitForTimeout(500);
        }
      } else {
        console.log('[demo] No experiments found, showing MLflow page');
        await page.waitForTimeout(LONG_PAUSE);
      }

      // Always mark mlflow_traces — we should be on traces view by now
      markStep('mlflow_traces');
      await page.waitForTimeout(LONG_PAUSE);

      // Click on the first trace (most recent — our agent chat)
      markStep('mlflow_detail');
      const traceSelectors = [
        page.locator('a:has-text("tr-")').first(),
        page.locator('[role="row"] a').first(),
        page.locator('table a').first(),
      ];
      let traceClicked = false;
      for (const sel of traceSelectors) {
        if (await sel.isVisible({ timeout: 3000 }).catch(() => false)) {
          await demoClick(sel, 'Latest trace (from agent chat)');
          traceClicked = true;
          break;
        }
      }
      if (traceClicked) {
        await page.waitForTimeout(5000);
        console.log('[demo] Showing trace detail');
      } else {
        console.log('[demo] No trace links found');
      }
      await page.waitForTimeout(LONG_PAUSE);
    } else {
      console.log('[demo] Step 6: MLflow URL not set, skipping');
    }

    // ================================================================
    // STEP 7: Navigate to Phoenix for trace details
    // ================================================================
    if (PHOENIX_URL) {
      markStep('phoenix');
      console.log('[demo] Step 7: Navigate to Phoenix traces');
      await page.goto(PHOENIX_URL, { waitUntil: 'networkidle', timeout: 30000 }).catch(() => {});
      await injectCursor();
      await page.waitForTimeout(LONG_PAUSE);

      // Click on Traces tab/link if available
      const tracesNav = page.getByRole('link', { name: /Traces/i })
        .or(page.locator('a[href*="trace"]'));
      if (await tracesNav.first().isVisible({ timeout: 5000 }).catch(() => false)) {
        await demoClick(tracesNav.first(), 'Phoenix Traces');
        await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
        await page.waitForTimeout(LONG_PAUSE);

        // Click on the first trace to see detail
        await page.waitForTimeout(2000); // Wait for traces to load

        // Phoenix uses table rows or clickable trace items
        const phoenixTraceSelectors = [
          page.locator('table tbody tr').first(),
          page.locator('[role="row"]').nth(1),
          page.locator('[class*="trace"] a, [class*="row"]').first(),
        ];
        let phoenixTraceClicked = false;
        for (const sel of phoenixTraceSelectors) {
          if (await sel.isVisible({ timeout: 3000 }).catch(() => false)) {
            await demoClick(sel, 'Phoenix trace detail');
            phoenixTraceClicked = true;
            break;
          }
        }
        if (phoenixTraceClicked) {
          await page.waitForTimeout(3000); // Wait for detail to render
          console.log('[demo] Showing Phoenix trace detail');
        }
        await page.waitForTimeout(LONG_PAUSE);
      } else {
        console.log('[demo] Phoenix traces nav not found — showing landing page');
        await page.waitForTimeout(LONG_PAUSE);
      }
    }

    // Always mark phoenix_traces even if nav wasn't found
    markStep('phoenix_traces');
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 8: Navigate to Kiali for service mesh view
    // ================================================================
    markStep('kiali');
    if (KIALI_URL) {
      console.log('[demo] Step 8: Navigate to Kiali');
      await page.goto(KIALI_URL, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
      await page.waitForTimeout(PAUSE);

      // Kiali on OpenShift uses OAuth — login with kubeadmin
      const currentUrl = page.url();
      if (currentUrl.includes('oauth') || currentUrl.includes('login')) {
        console.log('[demo] Kiali requires OpenShift OAuth login');

        if (KUBEADMIN_PASS) {
          // Look for "kube:admin" or "htpasswd" identity provider option
          const kubeadminLink = page.getByRole('link', { name: /kube.*admin|htpasswd|my_htpasswd_provider/i })
            .or(page.locator('a:has-text("kube")'));
          if (await kubeadminLink.first().isVisible({ timeout: 5000 }).catch(() => false)) {
            await kubeadminLink.first().click();
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
            await loginBtn.first().click();
            console.log('[demo] Submitted kubeadmin credentials');
            await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
          }

          // Handle OAuth authorize page
          const authorizeBtn = page.getByRole('button', { name: /allow|authorize|approve/i })
            .or(page.locator('input[name="approve"]'));
          if (await authorizeBtn.first().isVisible({ timeout: 5000 }).catch(() => false)) {
            await authorizeBtn.first().click();
            await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
          }
        } else {
          console.log('[demo] No KUBEADMIN_PASS set, skipping Kiali OAuth');
        }
      }

      await injectCursor();
      await page.waitForTimeout(LONG_PAUSE);

      // Navigate to the Traffic Graph view
      markStep('kiali_graph');
      const graphLink = page.getByRole('link', { name: /Traffic Graph/i })
        .or(page.getByRole('link', { name: /Graph/i }))
        .or(page.locator('a[href*="graph"]'));
      if (await graphLink.first().isVisible({ timeout: 5000 }).catch(() => false)) {
        await demoClick(graphLink.first(), 'Traffic Graph');
        await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
        await page.waitForTimeout(PAUSE);

        // Open namespace selector and select all namespaces
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
        }

        // Change time range to "Last 10m"
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
        }

        // Wait for graph to render
        await page.waitForTimeout(LONG_PAUSE);

        // Zoom to fit — click the "Zoom to Fit" button in the graph toolbar
        const zoomFitButton = page.locator('button[title="Zoom to fit"], button[aria-label="Zoom to fit"]')
          .or(page.locator('#toolbar_zoom_to_fit'))
          .or(page.locator('button:has(svg)').filter({ has: page.locator('[data-icon="expand"]') }));
        if (await zoomFitButton.first().isVisible({ timeout: 3000 }).catch(() => false)) {
          await demoClick(zoomFitButton.first(), 'Zoom to fit');
          await page.waitForTimeout(PAUSE);
        } else {
          // Try keyboard shortcut for zoom to fit
          console.log('[demo] Zoom to fit button not found, using keyboard shortcut');
          await page.keyboard.press('Control+Shift+f');
          await page.waitForTimeout(PAUSE);
        }

        // Enable Security display option
        markStep('kiali_security');
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

          // Toggle Animation
          const animationToggle = page.getByText('Animation', { exact: true })
            .or(page.locator('label:has-text("Animation")'));
          if (await animationToggle.first().isVisible({ timeout: 3000 }).catch(() => false)) {
            await demoClick(animationToggle.first(), 'Animation toggle');
            await page.waitForTimeout(500);
          }

          // Close display dropdown
          await page.keyboard.press('Escape');
        }

        // Let the animated graph render for a few seconds
        console.log('[demo] Showing Kiali traffic graph with security and animation...');
        await page.waitForTimeout(5000);
      } else {
        // kiali_security markStep still needs to fire even if graph link not found
        markStep('kiali_security');
        await page.waitForTimeout(LONG_PAUSE);
      }
    } else {
      // Mark all kiali sub-steps even if skipped
      markStep('kiali_graph');
      markStep('kiali_security');
      console.log('[demo] Step 8: Kiali URL not set, skipping');
    }

    // ================================================================
    // FINAL: Show completion
    // ================================================================
    markStep('end');
    console.log('[demo] Walkthrough complete!');

    // Write timestamps file for narration sync
    const fs = require('fs');
    const path = require('path');
    const scriptDir = process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, '..');
    const tsFile = path.join(scriptDir, '..', 'walkthrough-demo-timestamps.json');
    fs.writeFileSync(tsFile, JSON.stringify(stepTimestamps, null, 2));
    console.log(`[demo] Timestamps written to ${tsFile}`);

    // Long final pause so narration can finish without video cutting
    await page.waitForTimeout(15000);
  });
});
