import test from 'node:test';
import assert from 'node:assert/strict';
import { ChartTradingController } from '../../assisted_trading/frontendv2/js/chart/ChartTradingController.js';

test('starts unavailable until trading snapshot is ready', () => {
  const controller = new ChartTradingController();

  assert.equal(controller.getState().ready, false);
  assert.equal(controller.canSubmit(), false);
});

test('accepts a ready trading snapshot', () => {
  const controller = new ChartTradingController();

  controller.setTradingSnapshot({
    symbol: 'SPY',
    currentPrice: 745.64,
    strike: 746,
    dte: 2,
    premium: 2.75,
    contracts: 3,
    contractType: 'CALL'
  });

  assert.equal(controller.getState().ready, true);
  assert.equal(controller.canSubmit(), true);
});

test('rejects stale strike or dte snapshots', () => {
  const controller = new ChartTradingController();

  controller.setTradingSnapshot({
    symbol: 'SPY',
    currentPrice: 745.64,
    strike: 0,
    dte: 0,
    premium: 2.75,
    contracts: 3,
    contractType: 'CALL'
  });

  assert.equal(controller.getState().ready, false);
  assert.equal(controller.canSubmit(), false);
});

test('tracks target drag lifecycle', () => {
  const controller = new ChartTradingController();
  controller.setTradingSnapshot({
    symbol: 'SPY',
    currentPrice: 745.64,
    strike: 746,
    dte: 2,
    premium: 2.75,
    contracts: 3,
    contractType: 'CALL'
  });

  controller.startDrag('target', 745.64);
  controller.moveDrag(748.83);
  controller.endDrag();

  const state = controller.getState();
  assert.equal(state.mode, 'idle');
  assert.equal(state.targetPrice, 748.83);
});

test('rejects invalid call stop above current price', () => {
  const controller = new ChartTradingController();
  controller.setTradingSnapshot({
    symbol: 'SPY',
    currentPrice: 745.64,
    strike: 746,
    dte: 2,
    premium: 2.75,
    contracts: 3,
    contractType: 'CALL'
  });

  controller.startDrag('stop', 745.64);
  controller.moveDrag(748.83);

  assert.equal(controller.getState().valid, false);
});

test('panelReady=false forces not-ready even with valid data carry-over', () => {
  const controller = new ChartTradingController();
  controller.setTradingSnapshot({
    symbol: 'SPY',
    currentPrice: 745.64,
    strike: 746,
    dte: 2,
    premium: 2.75,
    contracts: 3,
    contractType: 'CALL'
  });
  assert.equal(controller.getState().ready, true);

  controller.setTradingSnapshot({
    symbol: 'QQQ',
    currentPrice: 745.64,
    strike: 746,
    dte: 2,
    premium: 2.75,
    contracts: 3,
    contractType: 'CALL',
    panelReady: false
  });

  assert.equal(controller.getState().ready, false);
  assert.equal(controller.canSubmit(), false);
});

test('republishing empty snapshot returns controller to not-ready', () => {
  const controller = new ChartTradingController();
  controller.setTradingSnapshot({
    symbol: 'SPY',
    currentPrice: 745.64,
    strike: 746,
    dte: 2,
    premium: 2.75,
    contracts: 3,
    contractType: 'CALL'
  });
  assert.equal(controller.getState().ready, true);

  controller.setTradingSnapshot({
    symbol: 'SPY',
    currentPrice: 745.64,
    strike: 0,
    dte: 0,
    premium: 0,
    contracts: 0,
    contractType: 'CALL'
  });

  assert.equal(controller.getState().ready, false);
  assert.equal(controller.canSubmit(), false);
});
