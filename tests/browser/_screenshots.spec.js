/**
 * Screenshot capture script (not part of the regression suite).
 * Run with the platform already serving on http://localhost:5001:
 *   npx playwright test tests/browser/_screenshots.spec.js
 *
 * Output: docs/screenshots/*.png
 */
import { test, expect } from '@playwright/test';
import path from 'path';

const OUT = path.resolve(process.cwd(), 'docs', 'screenshots');

async function waitReady(page) {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () =>
      window.ChartTradingController?.getState?.().ready === true &&
      window.OrderPanelOnChart?.buyButton &&
      window.OrderPanelOnChart.buyButton.disabled === false,
    null,
    { timeout: 30_000 }
  );
  // Give the chart a moment to fully render bars/indicators.
  await page.waitForTimeout(1500);
}

test('01 overview', async ({ page }) => {
  await waitReady(page);
  await page.screenshot({ path: path.join(OUT, '01-overview.png'), fullPage: false });
});

test('02 drag tp sl', async ({ page }) => {
  await waitReady(page);

  // Programmatically place SL and TP via the OrderPanelOnChart controller so
  // the persistent price lines + draggable hit areas appear on the chart.
  await page.evaluate(() => {
    const panel = window.OrderPanelOnChart;
    const price = window.ChartManager?.getLastPrice?.() ||
                  window.ChartTradingController?.getState?.()?.underlyingPrice;
    if (panel && price) {
      // Set TP ~1% above, SL ~0.5% below the underlying.
      panel.setTakeProfit?.(price * 1.01);
      panel.setStopLoss?.(price * 0.995);
    }
  });
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(OUT, '02-drag-tp-sl.png'), fullPage: false });
});

test('03 buy limit trigger', async ({ page }) => {
  await waitReady(page);

  await page.evaluate(() => {
    const panel = window.OrderPanelOnChart;
    const price = window.ChartManager?.getLastPrice?.() ||
                  window.ChartTradingController?.getState?.()?.underlyingPrice;
    if (panel && price) {
      // Drag the buy pill below live price -> limit-trigger mode.
      panel.setEntryTrigger?.(price * 0.997);
    }
  });
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(OUT, '03-buy-limit-trigger.png'), fullPage: false });
});

test('04 side panel', async ({ page }) => {
  await waitReady(page);
  // Clip the right-hand trading panel only.
  const viewport = page.viewportSize();
  const panel = await page.locator('#trading-panel, .trading-panel, aside').first();
  let clip;
  try {
    const box = await panel.boundingBox({ timeout: 2000 });
    if (box) clip = { x: box.x, y: box.y, width: box.width, height: box.height };
  } catch (e) { /* fall through */ }
  if (!clip) {
    // Fallback: right ~340px of the viewport
    clip = { x: viewport.width - 360, y: 0, width: 360, height: viewport.height };
  }
  await page.screenshot({ path: path.join(OUT, '04-side-panel.png'), clip });
});
