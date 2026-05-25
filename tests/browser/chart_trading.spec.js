import { test, expect } from '@playwright/test';

test('chart controls are gated until trading state is ready', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });

  // Wait until the on-chart order panel has been built.
  await page.waitForFunction(() => window.OrderPanelOnChart?.panelContainer, null, { timeout: 20_000 });

  const early = await page.evaluate(() => ({
    ready: window.TradingPanel?.isReady === true,
    controllerReady: window.ChartTradingController?.getState?.().ready === true,
    buyDisabled: window.OrderPanelOnChart?.buyButton?.disabled === true,
    strike: window.TradingPanel?.selectedStrike,
    dte: window.TradingPanel?.dte
  }));

  // Before symbol config + quote arrive the controller MUST report not-ready
  // and the buy button MUST be disabled.
  expect(early.controllerReady).toBe(false);
  expect(early.buyDisabled).toBe(true);

  // Once the trading panel finishes loading symbol/contracts/quote, the
  // controller flips to ready and the buy button is enabled.
  await page.waitForFunction(
    () =>
      window.ChartTradingController?.getState?.().ready === true &&
      window.OrderPanelOnChart?.buyButton &&
      window.OrderPanelOnChart.buyButton.disabled === false,
    null,
    { timeout: 20_000 }
  );

  const ready = await page.evaluate(() => ({
    strike: window.TradingPanel.selectedStrike,
    dte: window.TradingPanel.dte,
    snapshot: window.ChartTradingController.getState()
  }));

  expect(ready.strike).toBeGreaterThan(0);
  expect(ready.dte).toBeGreaterThan(0);
  expect(ready.snapshot.symbol).toBeTruthy();
  expect(ready.snapshot.premium).toBeGreaterThan(0);
  expect(ready.snapshot.contracts).toBeGreaterThan(0);
});

test('tp drag updates one persistent chart price line', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () =>
      window.ChartTradingController?.getState?.().ready === true &&
      window.OrderPanelOnChart?.buyButton &&
      window.OrderPanelOnChart.buyButton.disabled === false,
    null,
    { timeout: 20_000 }
  );

  await page.evaluate(() => {
    window.__dragProbe = [];
    const series = window.ChartManager.getSeries();
    const originalCreate = series.createPriceLine.bind(series);
    const originalRemove = series.removePriceLine.bind(series);
    series.createPriceLine = function (options) {
      window.__dragProbe.push({ fn: 'createPriceLine', title: options.title });
      return originalCreate(options);
    };
    series.removePriceLine = function (line) {
      window.__dragProbe.push({ fn: 'removePriceLine' });
      return originalRemove(line);
    };
  });

  const tpBtn = page.locator('.order-panel-on-chart .tp-btn');
  await tpBtn.waitFor({ state: 'visible', timeout: 5_000 });
  const box = await tpBtn.boundingBox();
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;

  await page.mouse.move(x, y);
  await page.mouse.down();
  for (let i = 1; i <= 8; i++) {
    await page.mouse.move(x, y - i * 16);
    await page.waitForTimeout(40);
  }
  await page.mouse.up();

  const probe = await page.evaluate(() => window.__dragProbe);
  const creates = probe.filter(p => p.fn === 'createPriceLine');
  const removes = probe.filter(p => p.fn === 'removePriceLine');
  expect(creates.length).toBe(1);
  expect(removes.length).toBe(0);
});
