import { test, expect } from '@playwright/test';
import { loginIfNeeded } from './helpers/auth';

test('check history endpoint response', async ({ page }) => {
  test.setTimeout(120000);

  let historyResponse = '';
  page.on('response', async (resp) => {
    if (resp.url().includes('/history')) {
      try {
        historyResponse = await resp.text();
      } catch {}
    }
  });

  await page.goto('/');
  await loginIfNeeded(page);
  
  await page.locator('nav a, nav button', { hasText: 'Sessions' }).first().click();
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2000);
  await page.getByText('+ New Session').click();
  // Handle New Session modal
  const startBtn = page.getByRole('button', { name: /^Start$/ });
  if (await startBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
    await startBtn.click();
    await page.waitForTimeout(500);
  }
  await page.waitForTimeout(500);
  
  const input = page.locator('textarea').first();
  await input.fill('Run the command: echo history-debug-test');
  await page.getByRole('button', { name: /Send/i }).click();
  await expect(input).toBeEnabled({ timeout: 180000 });
  await page.waitForTimeout(3000);
  
  // Parse and display the history response
  console.log('=== HISTORY RESPONSE ===');
  try {
    const data = JSON.parse(historyResponse);
    console.log(`Total: ${data.total}, Messages: ${data.messages?.length}`);
    for (const msg of (data.messages || []).slice(0, 10)) {
      const parts = msg.parts || [];
      const kind = parts[0]?.kind || '?';
      const type = parts[0]?.type || '';
      const text = (parts[0]?.text || '').substring(0, 100);
      console.log(`  role=${msg.role} kind=${kind} type=${type} text=${text}`);
    }
  } catch (e) {
    console.log('Parse error:', historyResponse?.substring(0, 500));
  }
});
